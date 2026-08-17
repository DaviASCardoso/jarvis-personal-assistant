"""Comportamento proativo completo, de ponta a ponta (Fase 7.7).

O que este arquivo prova, e os testes unitários de cada subfase não: que
Trigger Engine (7.1) → Agent Runtime (Fase 4, com LLM substituído — é a
única peça que exigiria rede) → Decision Log (7.4) → Notification Manager
(7.3, com Interruption Policy da 7.2) → Action Executor (Fase 5) encaixam
numa cadeia só, e que o caminho paralelo e determinístico do Conditional
Trigger (7.6) e do Background Task Manager (7.5) também chegam à mesma
`ActionExecutor` sem passar pelo LLM.

Mesmo espírito de `test_agent_integration.py`: componentes reais (SQLite em
memória, Policy Engine real, Tool Router real), só o LLM é `StubLLMProvider`.
`uv run pytest` continua sem rede, sem credencial e sem quota.
"""

from jarvis.agent.input import EventTrigger
from jarvis.agent.runtime import AgentRuntime, GenerationDefaults
from jarvis.context.model import CurrentContext
from jarvis.decisions.events import decision_event
from jarvis.decisions.query import project_decisions
from jarvis.events.event import Event, RecordedEvent, new_event_id
from jarvis.execution.model import ActionRequest, Actor, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE as MEMORY_IN_MEMORY
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.notify.manager import NotificationManager
from jarvis.notify.notification import Notification, NotificationPriority
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.proactivity.adapters.memory_bridge import MemoryPresenceBridge
from jarvis.proactivity.conditions import (
    ActionTemplate,
    ConditionalRule,
    ConditionEngine,
    always,
    memory_present,
    not_,
)
from jarvis.proactivity.interruption import InterruptionPolicy, InterruptionSettings
from jarvis.proactivity.triggers import TriggerEngine, TriggerRule
from jarvis.skills.registry import SkillRegistry
from jarvis.tasks.manager import TaskManager
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import (
    NOON,
    FakeToolBackend,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
    make_skill,
)
from tests.agent_doubles import StubLLMProvider, decision_json
from tests.notify_doubles import FakeChannel
from tests.tasks_doubles import InMemoryTaskRepository

DECIDED_AT = NOON


def _context() -> CurrentContext:
    return CurrentContext(as_of=DECIDED_AT)


def _event() -> RecordedEvent:
    event = Event(
        event_id=new_event_id(),
        event_type="printer.job_completed",
        source="printer-watcher",
        occurred_at=DECIDED_AT,
        payload={"job_id": "42"},
    )
    return RecordedEvent(event=event, recorded_at=DECIDED_AT)


def _skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(make_skill())
    return registry


def _build_executor(
    *, audit: RecordingAuditLog, repository: InMemoryActionRepository
) -> ActionExecutor:
    tools = ToolRegistry()
    tools.register_backend(FakeToolBackend())
    tools.refresh()
    return ActionExecutor(
        skills=_skill_registry(),
        tools=tools,
        router=ToolRouter(registry=tools, audit=audit, monotonic=counting_monotonic()),
        policy=PolicyEngine(
            rules=PolicyRuleSet(granted_capabilities=frozenset({"test:run"})),
            clock=frozen_clock(DECIDED_AT),
        ),
        repository=repository,
        audit=audit,
        clock=frozen_clock(DECIDED_AT),
        monotonic=counting_monotonic(),
    )


def test_trigger_engine_matches_the_configured_event_type() -> None:
    engine = TriggerEngine(
        [TriggerRule(trigger_id="printer", event_types=frozenset({"printer.job_completed"}))]
    )
    assert engine.match(_event()) is not None


def test_full_reasoning_path_produces_decision_notification_and_action() -> None:
    """evento → Trigger Engine → Agent Runtime → Decision Log → Notification
    → Action Executor, tudo numa cadeia só."""
    llm = StubLLMProvider(
        [
            decision_json(
                type="act_and_notify",
                message="Vou cuidar disso agora.",
                action={"skill": "test.skill", "parameters": {"text": "oi"}},
            )
        ]
    )
    with SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository:
        memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
        runtime = AgentRuntime(
            llm=llm,
            context_reader=_context,
            memory=memory,
            generation=GenerationDefaults(),
            importance_threshold=0.0,
            clock=lambda: DECIDED_AT,
        )

        event = _event()
        trigger_engine = TriggerEngine(
            [TriggerRule(trigger_id="printer", event_types=frozenset({event.event.event_type}))]
        )
        matched = trigger_engine.match(event)
        assert matched is not None

        turn = runtime.handle(EventTrigger.from_recorded(event))

    assert turn.decision.type.value == "act_and_notify"
    assert turn.decision.message == "Vou cuidar disso agora."

    # Decision Log (7.4): a decisão vira evento e volta.
    event_record = decision_event(
        decision_id=turn.decision.decision_id,
        decision_type=turn.decision.type.value,
        reason=turn.decision.reason,
        message=turn.decision.message,
        decided_at=turn.decision.decided_at,
        correlation_id=turn.decision.correlation_id,
        causation_id=turn.decision.causation_id,
        consulted_llm=turn.consulted_llm,
        importance=turn.importance.total if turn.importance is not None else None,
        used_memory_ids=turn.used_memory_ids,
        context_as_of=DECIDED_AT,
        action_skill=turn.decision.action.skill if turn.decision.action is not None else None,
        source="jarvis-agent",
    )
    recorded = RecordedEvent(event=event_record, recorded_at=DECIDED_AT)
    records = project_decisions([recorded])
    assert len(records) == 1
    assert records[0].decision_type == "act_and_notify"
    assert records[0].action_skill == "test.skill"

    # Notification Manager (7.3 + 7.2): mensagem não vazia vira notificação.
    channel = FakeChannel()
    notifications = NotificationManager(
        channels=[channel],
        # Limiar baixo de propósito: este teste prova a entrega mecânica da
        # notificação, não a calibração numérica do Importance Engine (já
        # coberta por `test_agent_importance.py`).
        interruption_policy=InterruptionPolicy(InterruptionSettings(importance_threshold=0.1)),
    )
    outcome = notifications.notify(
        Notification(
            notification_id=turn.decision.decision_id,
            subject=event.event.event_type,
            title="Jarvis",
            body=turn.decision.message,
            priority=NotificationPriority.NORMAL,
            correlation_id=turn.decision.correlation_id,
            created_at=turn.decision.decided_at,
        ),
        importance=turn.importance.total if turn.importance is not None else 1.0,
        context=_context(),
    )
    assert outcome.delivered is True
    assert channel.sent

    # Action Executor (Fase 5): a proposta da decisão executa de verdade.
    audit = RecordingAuditLog()
    action_repository = InMemoryActionRepository()
    executor = _build_executor(audit=audit, repository=action_repository)
    proposal = turn.decision.action
    assert proposal is not None
    execution = executor.submit(
        ActionRequest(
            skill=proposal.skill,
            parameters=dict(proposal.parameters),
            correlation_id=turn.decision.correlation_id,
            actor=Actor.EVENT,
            decision_id=turn.decision.decision_id,
            causation_id=turn.decision.causation_id,
        )
    )
    assert execution.status is ExecutionStatus.COMPLETED


def test_low_importance_event_is_not_reasoned_about() -> None:
    """Abaixo do limiar, o Importance Engine silencia — nem o LLM é chamado."""
    llm = StubLLMProvider([decision_json()])
    with SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository:
        memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
        runtime = AgentRuntime(
            llm=llm,
            context_reader=_context,
            memory=memory,
            generation=GenerationDefaults(),
            importance_threshold=1.1,  # inalcançável
        )
        turn = runtime.handle(EventTrigger.from_recorded(_event()))

    assert turn.consulted_llm is False
    assert llm.calls == 0


def test_conditional_trigger_executes_without_any_llm() -> None:
    """7.6: regra determinística casa e executa direto, sem Agent Runtime."""
    rule = ConditionalRule(
        rule_id="auto_ack",
        when=frozenset({"printer.job_completed"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill", parameters={"text": "$event.job_id"}),
    )
    engine = ConditionEngine([rule])
    event = _event()

    request = engine.evaluate(event, context=_context())

    assert request is not None
    assert request.actor is Actor.SYSTEM
    assert dict(request.parameters) == {"text": "42"}

    audit = RecordingAuditLog()
    repository = InMemoryActionRepository()
    executor = _build_executor(audit=audit, repository=repository)
    outcome = executor.submit(request)

    assert outcome.status is ExecutionStatus.COMPLETED


def test_background_task_manager_retries_then_succeeds() -> None:
    """7.5: uma tarefa submetida é executada no próximo tick e conclui."""
    audit = RecordingAuditLog()
    action_repository = InMemoryActionRepository()
    executor = _build_executor(audit=audit, repository=action_repository)

    task_repository = InMemoryTaskRepository()
    manager = TaskManager(
        repository=task_repository,
        max_attempts=3,
        retry_base_delay_seconds=1.0,
        clock=lambda: NOON,
    )
    task = manager.submit(
        ActionRequest(skill="test.skill", parameters={"text": "oi"}, correlation_id="corr-task")
    )

    settled = manager.run_due(executor=executor, moment=NOON)

    assert len(settled) == 1
    assert settled[0].task_id == task.task_id
    assert settled[0].status.value == "succeeded"


def test_a_quiet_hours_memory_suppresses_a_conditional_trigger() -> None:
    """Fase 9.3/9.4: `not_(memory_present(...))` suprime a regra enquanto a
    preferência estiver vigente — sem tocar `InterruptionPolicy` nem o Agent
    Runtime, exatamente o cenário do ADR-0032."""
    rule = ConditionalRule(
        rule_id="notify_unless_quiet_hours",
        when=frozenset({"printer.job_completed"}),
        condition=not_(memory_present("quiet_hours_preference")),
        then=ActionTemplate(skill="test.skill"),
    )
    engine = ConditionEngine([rule])
    event = _event()

    with SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository:
        memory = MemoryManager(repository=repository, clock=lambda: DECIDED_AT)
        bridge = MemoryPresenceBridge(memory, clock=lambda: DECIDED_AT)

        # Sem a preferência gravada, a regra casa normalmente.
        assert engine.evaluate(event, context=_context(), memory=bridge) is not None

        memory.remember(
            type=MemoryType.PREFERENCE,
            content="não notificar depois das 22h",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="quiet_hours_preference",
        )

        # Com a preferência vigente, a mesma regra deixa de casar.
        assert engine.evaluate(event, context=_context(), memory=bridge) is None


def test_conditional_trigger_never_calls_the_llm() -> None:
    """Cinto e suspensório: o caminho condicional realmente nunca chama `generate`."""
    llm = StubLLMProvider([decision_json()])
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"printer.job_completed"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill"),
    )
    engine = ConditionEngine([rule])
    engine.evaluate(_event(), context=_context())
    assert llm.calls == 0
