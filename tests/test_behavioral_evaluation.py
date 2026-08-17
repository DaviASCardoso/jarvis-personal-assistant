"""Fase 8.5 — Behavioral Evaluation: os oito cenários do ROADMAP, cada um
contra componentes reais (Context/Memory/Execution de verdade — só o LLM é
`StubLLMProvider`, mesmo espírito de `test_agent_integration.py` e
`test_proactivity_integration.py`).

Onde um cenário do roadmap não tem contrapartida literal na arquitetura (ex.
"solicitação para enviar email", quando nenhuma Skill de e-mail existe em
nenhuma fase — ver `docs/skills.md`), o teste exercita a adaptação fiel mais
próxima e documenta a adaptação no próprio docstring, em vez de simular um
comportamento que o sistema não tem.
"""

from datetime import UTC, datetime, timedelta

from jarvis.agent.decision import DecisionType
from jarvis.agent.importance import assess
from jarvis.agent.input import EventTrigger, UserMessage
from jarvis.agent.runtime import AgentRuntime, GenerationDefaults
from jarvis.context.model import ActivityContext, CurrentContext, ScheduleContext, UserContext
from jarvis.context.observation import Observation
from jarvis.execution.model import ActionRequest, Actor, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.memory.retrieval import RetrievalQuery
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.skills.registry import SkillRegistry
from jarvis.tools.errors import ToolExecutionError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import (
    FakeToolBackend,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
    make_skill,
)
from tests.agent_doubles import StubLLMProvider, decision_json

NOW = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def _runtime(*, memory: MemoryManager, context: CurrentContext, threshold: float) -> AgentRuntime:
    return AgentRuntime(
        llm=StubLLMProvider([decision_json()]),
        context_reader=lambda: context,
        memory=memory,
        generation=GenerationDefaults(),
        importance_threshold=threshold,
        clock=lambda: NOW,
    )


def _busy_context() -> CurrentContext:
    return CurrentContext(
        as_of=NOW,
        user=UserContext(availability=Observation(value="busy", observed_at=NOW, source="test")),
        activity=ActivityContext(
            current=Observation(value="focus", observed_at=NOW, source="test")
        ),
    )


def _neutral_context() -> CurrentContext:
    return CurrentContext(as_of=NOW)


class TestEmailDuringFocusOutweighsTheInterruptionCost:
    """Cenário 1 do roadmap: e-mail importante durante foco.

    Prova a troca entre `interruption_cost` alto (usuário ocupado, em foco) e
    `personal_relevance` alto (memória relevante recuperada de verdade) — o
    segundo consegue elevar a importância total acima do primeiro cenário
    apesar do custo de interrupção maior.
    """

    def test_a_relevant_memory_raises_importance_above_an_irrelevant_one(self) -> None:
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            memory.remember(
                type=MemoryType.SEMANTIC,
                content="A diretora pediu aprovacao urgente do contrato ate amanha",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="contrato",
                created_at=NOW - timedelta(days=1),
            )

            relevant_trigger = EventTrigger(
                event_id="evt-relevant",
                event_type="email.received",
                source="email-watcher",
                occurred_at=NOW,
                correlation_id="corr-relevant",
                payload={"sender": "diretora", "subject": "aprovacao urgente do contrato"},
            )
            irrelevant_trigger = EventTrigger(
                event_id="evt-irrelevant",
                event_type="printer.job_completed",
                source="printer-watcher",
                occurred_at=NOW,
                correlation_id="corr-irrelevant",
                payload={"job_id": "42"},
            )

            relevant_memories = memory.retrieve(
                RetrievalQuery(text=relevant_trigger.retrieval_text())
            ).results
            irrelevant_memories = memory.retrieve(
                RetrievalQuery(text=irrelevant_trigger.retrieval_text())
            ).results

        busy = assess(
            relevant_trigger, context=_busy_context(), memories=relevant_memories, now=NOW
        )
        neutral = assess(
            irrelevant_trigger, context=_neutral_context(), memories=irrelevant_memories, now=NOW
        )

        assert busy.interruption_cost > neutral.interruption_cost
        assert busy.personal_relevance > neutral.personal_relevance
        assert busy.total > neutral.total

    def test_the_relevant_case_reaches_the_llm_and_the_irrelevant_one_does_not(self) -> None:
        """Mesmo cálculo do teste acima, agora através do `AgentRuntime` inteiro,
        com um limiar calibrado entre as duas importâncias reais."""
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            memory.remember(
                type=MemoryType.SEMANTIC,
                content="A diretora pediu aprovacao urgente do contrato ate amanha",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="contrato",
                created_at=NOW - timedelta(days=1),
            )

            relevant_trigger = EventTrigger(
                event_id="evt-relevant",
                event_type="email.received",
                source="email-watcher",
                occurred_at=NOW,
                correlation_id="corr-relevant",
                payload={"sender": "diretora", "subject": "aprovacao urgente do contrato"},
            )
            irrelevant_trigger = EventTrigger(
                event_id="evt-irrelevant",
                event_type="printer.job_completed",
                source="printer-watcher",
                occurred_at=NOW,
                correlation_id="corr-irrelevant",
                payload={"job_id": "42"},
            )

            probe_busy = _runtime(memory=memory, context=_busy_context(), threshold=0.0).handle(
                relevant_trigger
            )
            probe_neutral = _runtime(
                memory=memory, context=_neutral_context(), threshold=0.0
            ).handle(irrelevant_trigger)
            assert probe_busy.importance is not None
            assert probe_neutral.importance is not None
            threshold = (probe_busy.importance.total + probe_neutral.importance.total) / 2

            relevant_turn = _runtime(
                memory=memory, context=_busy_context(), threshold=threshold
            ).handle(relevant_trigger)
            irrelevant_turn = _runtime(
                memory=memory, context=_neutral_context(), threshold=threshold
            ).handle(irrelevant_trigger)

        assert relevant_turn.consulted_llm is True
        assert irrelevant_turn.consulted_llm is False
        assert irrelevant_turn.decision.type is DecisionType.IGNORE


class TestUpcomingMeetingRaisesUrgency:
    """Cenário 3 do roadmap: reunião próxima eleva `urgency` para 1.0."""

    def test_an_imminent_meeting_maximizes_urgency(self) -> None:
        trigger = EventTrigger(
            event_id="evt-meeting",
            event_type="calendar.reminder",
            source="calendar-watcher",
            occurred_at=NOW - timedelta(hours=2),
            correlation_id="corr-meeting",
            payload={},
        )
        context = CurrentContext(
            as_of=NOW,
            schedule=ScheduleContext(
                next_entry_at=Observation(
                    value=NOW + timedelta(minutes=10), observed_at=NOW, source="test"
                )
            ),
        )

        assessment = assess(trigger, context=context, memories=(), now=NOW)

        assert assessment.urgency == 1.0
        assert "schedule_imminent" in assessment.reasons

    def test_the_imminent_meeting_reaches_the_llm(self) -> None:
        trigger = EventTrigger(
            event_id="evt-meeting",
            event_type="calendar.reminder",
            source="calendar-watcher",
            occurred_at=NOW - timedelta(hours=2),
            correlation_id="corr-meeting",
            payload={},
        )
        context = CurrentContext(
            as_of=NOW,
            schedule=ScheduleContext(
                next_entry_at=Observation(
                    value=NOW + timedelta(minutes=10), observed_at=NOW, source="test"
                )
            ),
        )
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            # Limiar abaixo do que `urgency=1.0` sozinho já entrega
            # (`weights.urgency * 1.0`, ver `agent/importance.py`) — o ponto do
            # cenário é que a proximidade do compromisso basta, não que
            # qualquer limiar configurado seria ultrapassado.
            turn = _runtime(memory=memory, context=context, threshold=0.25).handle(trigger)

        assert turn.consulted_llm is True


class TestRequestToSendAnEmailIsDeniedNotFaked:
    """Cenário 4 do roadmap: "solicitação para enviar e-mail".

    Adaptação fiel: nenhuma fase do projeto implementa uma Skill de e-mail
    (fora de escopo em todas as fases, ver `docs/skills.md`). O cenário fiel
    ao que o sistema realmente faz é o modelo propor uma Skill que não
    existe, e o `ActionExecutor` negar em vez de fingir sucesso.
    """

    def test_a_proposed_unregistered_skill_is_denied_not_executed(self) -> None:
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            llm = StubLLMProvider(
                [
                    decision_json(
                        type="act",
                        message=None,
                        action={
                            "skill": "email.send",
                            "parameters": {"to": "chefe@empresa.com", "body": "oi"},
                        },
                    )
                ]
            )
            runtime = AgentRuntime(
                llm=llm,
                context_reader=_neutral_context,
                memory=memory,
                generation=GenerationDefaults(),
                importance_threshold=0.0,
                clock=lambda: NOW,
            )
            turn = runtime.handle(
                UserMessage(text="manda um email pro chefe", at=NOW, conversation_id="corr-email")
            )

        assert turn.decision.type.value == "act"
        proposal = turn.decision.action
        assert proposal is not None
        assert proposal.skill == "email.send"

        tools = ToolRegistry()
        tools.register_backend(FakeToolBackend())
        tools.refresh()
        executor = ActionExecutor(
            skills=SkillRegistry(),  # "email.send" nunca foi registrada
            tools=tools,
            router=ToolRouter(registry=tools, monotonic=counting_monotonic()),
            policy=PolicyEngine(
                rules=PolicyRuleSet(granted_capabilities=frozenset({"test:run"})),
                clock=frozen_clock(NOW),
            ),
            repository=InMemoryActionRepository(),
            audit=RecordingAuditLog(),
            clock=frozen_clock(NOW),
            monotonic=counting_monotonic(),
        )
        outcome = executor.submit(
            ActionRequest(
                skill=proposal.skill,
                parameters=dict(proposal.parameters),
                correlation_id=turn.decision.correlation_id,
                actor=Actor.USER,
            )
        )

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "skill_not_registered"


class TestToolFailureIsContainedNotFatal:
    """Cenário: falha de ferramenta não derruba o processo, e a execução
    reflete o que realmente aconteceu."""

    def test_a_tool_error_fails_the_action_without_crashing(self) -> None:
        tools = ToolRegistry()
        tools.register_backend(FakeToolBackend(failures=[ToolExecutionError("boom")]))
        tools.refresh()
        audit = RecordingAuditLog()
        skills = SkillRegistry()
        skills.register(make_skill())
        executor = ActionExecutor(
            skills=skills,
            tools=tools,
            router=ToolRouter(registry=tools, audit=audit, monotonic=counting_monotonic()),
            policy=PolicyEngine(
                rules=PolicyRuleSet(granted_capabilities=frozenset({"test:run"})),
                clock=frozen_clock(NOW),
            ),
            repository=InMemoryActionRepository(),
            audit=audit,
            clock=frozen_clock(NOW),
            monotonic=counting_monotonic(),
        )

        outcome = executor.submit(
            ActionRequest(
                skill="test.skill",
                parameters={"text": "oi"},
                correlation_id="corr-fail",
                actor=Actor.USER,
            )
        )

        assert outcome.status is ExecutionStatus.FAILED
        assert any(entry.kind.value == "tool.execution_failed" for entry in audit.entries)


class TestContradictoryMemoriesOnlyExposeTheCurrentOne:
    """Cenário: duas memórias `PREFERENCE` com o mesmo `subject`, conteúdo
    diferente — o retrieval só devolve a vigente (supersessão da Fase 3)."""

    def test_the_older_contradicting_preference_is_not_retrieved(self) -> None:
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            memory.remember(
                type=MemoryType.PREFERENCE,
                content="prefere reunioes de manha",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="horario_de_reuniao",
                created_at=NOW - timedelta(days=2),
            )
            current = memory.remember(
                type=MemoryType.PREFERENCE,
                content="prefere reunioes a tarde",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="horario_de_reuniao",
                created_at=NOW,
            )

            outcome = memory.retrieve(RetrievalQuery(text="reunioes horario preferencia", now=NOW))

        subjects = [result.memory.memory.subject for result in outcome.results]
        assert subjects.count("horario_de_reuniao") == 1
        matching = next(
            result
            for result in outcome.results
            if result.memory.memory.subject == "horario_de_reuniao"
        )
        assert matching.memory.memory.memory_id == current.memory.memory_id
        assert matching.memory.memory.content == "prefere reunioes a tarde"


class TestPreferenceChangeClosesTheOldOneAndKeepsTheNew:
    """Cenário: mudança de preferência — a antiga fecha `valid_until`, a nova
    vigora, e o próximo prompt reflete só a atual."""

    def test_the_superseded_memory_gets_a_valid_until_at_the_new_ones_start(self) -> None:
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            old = memory.remember(
                type=MemoryType.PREFERENCE,
                content="prefere cafe sem acucar",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="preferencia_cafe",
                created_at=NOW - timedelta(days=5),
            )
            new = memory.remember(
                type=MemoryType.PREFERENCE,
                content="prefere cafe com adocante",
                provenance=Provenance(origin=MemoryOrigin.USER),
                subject="preferencia_cafe",
                created_at=NOW,
            )

            refreshed_old = repository.get(old.memory.memory_id)

        assert refreshed_old is not None
        assert refreshed_old.memory.valid_until == new.memory.valid_from
        assert refreshed_old.is_active_at(NOW) is False


class TestAppropriateSilenceProducesNoLlmCallNoNotificationNoAction:
    """Cenário 8 do roadmap: importância abaixo do limiar — `Decision.ignore`,
    sem LLM, sem notificação, sem ação."""

    def test_a_low_importance_event_is_silently_ignored(self) -> None:
        trigger = EventTrigger(
            event_id="evt-quiet",
            event_type="printer.job_completed",
            source="printer-watcher",
            occurred_at=NOW - timedelta(hours=6),
            correlation_id="corr-quiet",
            payload={"job_id": "1"},
        )
        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            llm = StubLLMProvider([decision_json()])
            runtime = AgentRuntime(
                llm=llm,
                context_reader=_neutral_context,
                memory=memory,
                generation=GenerationDefaults(),
                importance_threshold=1.1,  # inalcançável de propósito
                clock=lambda: NOW,
            )
            turn = runtime.handle(trigger)

        assert turn.consulted_llm is False
        assert llm.calls == 0
        assert turn.decision.type is DecisionType.IGNORE
        assert turn.decision.message is None
        assert turn.decision.action is None
