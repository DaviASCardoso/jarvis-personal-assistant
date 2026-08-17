"""Fase 8.6 — Failure + Recovery: os dez cenários do ROADMAP, um teste
nomeado por cenário.

Onde a cobertura já existe em profundidade num teste de unidade, o teste
aqui é uma prova de integração **curta** que aponta para essa cobertura em
vez de duplicá-la — o arquivo existe para que os dez nomes do roadmap
apareçam juntos e sejam auditáveis de uma vez, não para reescrever suítes
inteiras. Cada classe cita, no docstring, onde mora a cobertura funda
correspondente, quando ela existe.

Tudo aqui roda offline: nenhum teste toca rede, e os únicos arquivos em
disco são bancos SQLite temporários (`tmp_path`), quando o próprio cenário
exige um arquivo real em vez de `:memory:` (reinício de processo).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.agent.decision import DecisionType
from jarvis.agent.errors import LLMTimeoutError
from jarvis.agent.input import EventTrigger
from jarvis.agent.runtime import AgentRuntime, GenerationDefaults, LLMRetryPolicy
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.aggregator import ContextAggregator
from jarvis.context.engine import ContextEngine
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.events.errors import EventStoreError
from jarvis.events.event import Event, new_event_id
from jarvis.execution.identity import deterministic_execution_id
from jarvis.execution.model import ActionRequest, Actor, ExecutionStatus, PendingAction
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.skills.registry import SkillRegistry
from jarvis.tools.errors import ToolExecutionError, ToolUnavailableError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from jarvis.tools.schema import parameters_fingerprint
from tests.action_doubles import (
    FakeToolBackend,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
    make_skill,
)
from tests.agent_doubles import FailingLLMProvider, StubLLMProvider, decision_json
from tests.factories import make_event

NOW = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def _executor(
    *, skills: SkillRegistry, tools: ToolRegistry, repository: object, audit: RecordingAuditLog
) -> ActionExecutor:
    return ActionExecutor(
        skills=skills,
        tools=tools,
        router=ToolRouter(registry=tools, audit=audit, monotonic=counting_monotonic()),
        policy=PolicyEngine(
            rules=PolicyRuleSet(granted_capabilities=frozenset({"test:run"})),
            clock=frozen_clock(NOW),
        ),
        repository=repository,  # type: ignore[arg-type]
        audit=audit,
        clock=frozen_clock(NOW),
        monotonic=counting_monotonic(),
    )


class TestLlmUnavailable:
    """Cobertura funda: `tests/test_agent_runtime.py::test_a_permanent_failure_is_not_retried`
    e `::test_a_timeout_exhausts_the_attempts_and_propagates`. Aqui: o erro
    propaga tipado, sem decisão forjada — o composition root decide o que
    fazer com ele, o runtime nunca finge uma resposta."""

    def test_an_unavailable_provider_propagates_without_a_fake_decision(self) -> None:
        from jarvis.agent.errors import LLMProviderError
        from jarvis.context.model import CurrentContext
        from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE

        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            llm = FailingLLMProvider(LLMProviderError("provider fora do ar"))
            runtime = AgentRuntime(
                llm=llm,
                context_reader=lambda: CurrentContext(as_of=NOW),
                memory=memory,
                generation=GenerationDefaults(),
                importance_threshold=0.0,
                retry=LLMRetryPolicy(max_attempts=1),
                clock=lambda: NOW,
            )
            trigger = EventTrigger(
                event_id="evt-1",
                event_type="printer.job_completed",
                source="printer-watcher",
                occurred_at=NOW,
                correlation_id="corr-1",
                payload={},
            )
            with pytest.raises(LLMProviderError):
                runtime.handle(trigger)


class TestLlmTimeout:
    """Cobertura funda:
    `test_agent_runtime.py::test_a_timeout_exhausts_the_attempts_and_propagates`."""

    def test_a_timeout_is_retried_then_propagates_typed(self) -> None:
        llm = FailingLLMProvider(LLMTimeoutError("estourou"))
        assert llm.calls == 0
        with pytest.raises(LLMTimeoutError):
            _consume_llm_via_retry(llm, max_attempts=2)
        assert llm.calls == 2


def _consume_llm_via_retry(llm: FailingLLMProvider, *, max_attempts: int) -> None:
    from jarvis.context.model import CurrentContext
    from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE

    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
        runtime = AgentRuntime(
            llm=llm,
            context_reader=lambda: CurrentContext(as_of=NOW),
            memory=memory,
            generation=GenerationDefaults(),
            importance_threshold=0.0,
            retry=LLMRetryPolicy(max_attempts=max_attempts, base_delay=0.0),
            clock=lambda: NOW,
            sleep=lambda seconds: None,
        )
        trigger = EventTrigger(
            event_id="evt-timeout",
            event_type="printer.job_completed",
            source="printer-watcher",
            occurred_at=NOW,
            correlation_id="corr-timeout",
            payload={},
        )
        runtime.handle(trigger)


class TestDatabaseUnavailable:
    """Cobertura funda: `test_events_sqlite_store.py::TestFailures` (append/read
    num store fechado) e `::test_opening_an_unusable_path_fails_explicitly`.
    Aqui: o erro é tipado (`EventStoreError`), nunca uma exceção nativa do
    driver vazando para quem chamou."""

    def test_a_closed_event_store_fails_typed_not_natively(self, tmp_path: Path) -> None:
        store = SqliteEventStore.open(tmp_path / "events.db")
        store.close()

        with pytest.raises(EventStoreError):
            store.append(make_event())

    def test_an_unusable_path_fails_explicitly(self, tmp_path: Path) -> None:
        blocking_file = tmp_path / "blocker"
        blocking_file.write_text("not a directory", encoding="utf-8")

        with pytest.raises(EventStoreError):
            SqliteEventStore.open(blocking_file / "events.db")


class TestMcpUnavailable:
    """Cobertura funda:
    `test_tool_registry.py::test_a_backend_that_fails_discovery_is_marked_degraded`.
    Aqui: a cadeia inteira (Skill → Policy → Tool) nega de forma auditável em
    vez de travar quando o backend que representaria um MCP Server cai."""

    def test_a_skill_needing_an_unavailable_backend_is_denied_not_crashed(self) -> None:
        tools = ToolRegistry()
        tools.register_backend(
            FakeToolBackend(backend_id="fake", discovery_error=ToolUnavailableError("caiu"))
        )
        tools.refresh()
        skills = SkillRegistry()
        skills.register(make_skill())
        audit = RecordingAuditLog()
        executor = _executor(
            skills=skills, tools=tools, repository=InMemoryActionRepository(), audit=audit
        )

        outcome = executor.submit(
            ActionRequest(skill="test.skill", parameters={"text": "oi"}, correlation_id="corr-mcp")
        )

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "required_tool_unavailable"


class TestToolFailure:
    """Cobertura funda: `test_behavioral_evaluation.py::TestToolFailureIsContainedNotFatal`
    (8.5) — repetida aqui só pelo nome do cenário do roadmap, não pelo
    conteúdo."""

    def test_a_tool_error_fails_the_action_without_crashing(self) -> None:
        tools = ToolRegistry()
        tools.register_backend(FakeToolBackend(failures=[ToolExecutionError("boom")]))
        tools.refresh()
        skills = SkillRegistry()
        skills.register(make_skill())
        audit = RecordingAuditLog()
        executor = _executor(
            skills=skills, tools=tools, repository=InMemoryActionRepository(), audit=audit
        )

        outcome = executor.submit(
            ActionRequest(skill="test.skill", parameters={"text": "oi"}, correlation_id="corr-tool")
        )

        assert outcome.status is ExecutionStatus.FAILED


class TestDuplicateEvent:
    """Cobertura funda:
    `test_events_sqlite_store.py::test_deterministic_ids_deduplicate_re_observation`.
    Aqui: reinserir o **mesmo** evento (mesmo `event_id`) é no-op, não erro."""

    def test_appending_the_same_event_twice_is_a_no_op(self, tmp_path: Path) -> None:
        with SqliteEventStore.open(tmp_path / "events.db") as store:
            event = make_event(event_id="dup-1")
            first = store.append(event)
            second = store.append(event)

            assert first.event.event.event_id == second.event.event.event_id
            assert len(store.read_latest(limit=10)) == 1


class TestOutOfOrderEvent:
    """Cobertura funda:
    `test_events_sqlite_store.py::TestQueries::test_reads_follow_persistence_order`.
    Aqui: a leitura por correlação continua íntegra mesmo quando `occurred_at`
    não bate com a ordem de chegada — não há reordenação implícita em lugar
    nenhum da cadeia."""

    def test_reading_by_correlation_survives_events_out_of_temporal_order(
        self, tmp_path: Path
    ) -> None:
        with SqliteEventStore.open(tmp_path / "events.db") as store:
            store.append(
                make_event(
                    event_id="e-late",
                    correlation_id="chain-1",
                    occurred_at=NOW,
                )
            )
            store.append(
                make_event(
                    event_id="e-early",
                    correlation_id="chain-1",
                    occurred_at=NOW - timedelta(hours=3),
                )
            )

            found = store.read_by_correlation("chain-1")

        # Ordem de leitura é a de persistência (`e-late` antes de `e-early`),
        # não a de `occurred_at` — nenhum dos dois eventos se perde nem
        # derruba a leitura por ter chegado "fora de ordem".
        assert [item.event.event_id for item in found] == ["e-late", "e-early"]


class TestStaleContext:
    """Cobertura: `agent/importance.py::_schedule_term`/`_label` já tratam
    observação vencida como ausência, nunca como sinal atual (ver
    `docs/context-system.md`). Aqui: o Agent Runtime raciocina normalmente
    mesmo com contexto inteiramente vencido — degrada, não trava."""

    def test_a_fully_stale_context_does_not_crash_the_reasoning_path(self) -> None:
        from jarvis.context.model import CurrentContext, ScheduleContext
        from jarvis.context.observation import Observation
        from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE

        stale_context = CurrentContext(
            as_of=NOW,
            schedule=ScheduleContext(
                next_entry_at=Observation(
                    value=NOW + timedelta(minutes=5),
                    observed_at=NOW - timedelta(days=30),
                    source="test",
                    ttl=timedelta(hours=1),
                )
            ),
        )

        with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
            memory = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
            llm = StubLLMProvider([decision_json()])
            runtime = AgentRuntime(
                llm=llm,
                context_reader=lambda: stale_context,
                memory=memory,
                generation=GenerationDefaults(),
                importance_threshold=1.1,  # sem sinal fresco nenhum, nada ultrapassa
                clock=lambda: NOW,
            )
            trigger = EventTrigger(
                event_id="evt-stale",
                event_type="printer.job_completed",
                source="printer-watcher",
                occurred_at=NOW,
                correlation_id="corr-stale",
                payload={},
            )
            turn = runtime.handle(trigger)

        # Vencido não vale como "reunião iminente": não força raciocínio.
        assert turn.consulted_llm is False
        assert turn.decision.type is DecisionType.IGNORE


class TestProcessRestarted:
    """Cobertura funda por componente: `test_events_sqlite_store.py::test_events_survive_reopening`.
    Aqui: Event Store **e** Context Engine reabertos do mesmo arquivo, juntos
    — a garantia que importa é a projeção reconstruir igual depois de um
    processo novo, não cada peça isolada."""

    def test_context_rebuilds_identically_after_reopening_the_same_files(
        self, tmp_path: Path
    ) -> None:
        events_path = tmp_path / "events.db"
        snapshots_path = tmp_path / "context.db"

        event = Event(
            event_id=new_event_id(),
            event_type="user.availability_changed",
            source="test",
            occurred_at=NOW,
            payload={"availability": "busy"},
        )

        with SqliteEventStore.open(events_path) as store:
            store.append(event)

        def _engine() -> ContextEngine:
            aggregator = ContextAggregator(providers=())
            with SqliteContextSnapshotRepository.open(snapshots_path) as snapshots:
                engine = ContextEngine(
                    aggregator=aggregator, snapshots=snapshots, clock=lambda: NOW
                )
                with SqliteEventStore.open(events_path) as store:
                    engine.rebuild_from(store)
                return engine

        first_run = _engine()
        second_run = _engine()  # "processo reiniciado": tudo reaberto do zero

        first_context = first_run.current()
        second_context = second_run.current()
        assert first_context.user.availability is not None
        assert second_context.user.availability is not None
        first_value = first_context.user.availability.value
        second_value = second_context.user.availability.value
        assert first_value == second_value == "busy"


class TestCrashRecovery:
    """Cobertura: `execution/model.py::ExecutionStatus.blocks_reexecution` —
    `RUNNING` bloqueia de propósito, porque nem timeout nem processo morto no
    meio provam que o efeito não aconteceu do outro lado. Aqui: uma
    `PendingAction` presa em `RUNNING` (processo morto no meio da execução,
    sem `action.completed`/`action.failed` correspondente) bloqueia
    reapresentação da mesma decisão — `jarvis action show` continuaria
    honesto sobre o estado travado, não inventaria um resultado."""

    def test_a_pending_action_stuck_running_blocks_reexecution(self) -> None:
        repository = InMemoryActionRepository()
        tools = ToolRegistry()
        tools.register_backend(FakeToolBackend())
        tools.refresh()
        skills = SkillRegistry()
        skills.register(make_skill())
        audit = RecordingAuditLog()
        executor = _executor(skills=skills, tools=tools, repository=repository, audit=audit)

        parameters = {"text": "oi"}
        fingerprint = parameters_fingerprint(parameters)
        execution_id = deterministic_execution_id(
            decision_id="dec-crash", skill="test.skill", parameters_fingerprint=fingerprint
        )
        repository.put(
            PendingAction(
                execution_id=execution_id,
                skill="test.skill",
                parameters=parameters,
                parameters_fingerprint=fingerprint,
                actor=Actor.USER,
                correlation_id="corr-crash",
                status=ExecutionStatus.RUNNING,
                requested_at=NOW,
                updated_at=NOW,
                decision_id="dec-crash",
            )
        )

        outcome = executor.submit(
            ActionRequest(
                skill="test.skill",
                parameters=parameters,
                correlation_id="corr-crash",
                actor=Actor.USER,
                decision_id="dec-crash",
            )
        )

        assert outcome.status is ExecutionStatus.DUPLICATE
        assert outcome.reason == "already_executed"
        # O repositório continua honesto: o estado travado não vira sucesso.
        assert repository.get(execution_id).status is ExecutionStatus.RUNNING  # type: ignore[union-attr]
