"""Evento → contexto → memória → decisão, com os componentes reais.

O que este arquivo prova, e os testes unitários não: que as quatro fases
montadas até aqui encaixam. Usa Event Store, Context Engine e Memory Repository
**de verdade** (SQLite em memória) e só substitui o provider de LLM — que é
justamente a única peça que exigiria rede.

`uv run pytest` continua sem depender de API key, internet ou quota.
"""

import json
from datetime import UTC, datetime, timedelta

from jarvis.agent.conversation import Conversation, ConversationTurn
from jarvis.agent.decision import DecisionType
from jarvis.agent.input import EventSummary, EventTrigger, UserMessage
from jarvis.agent.messages import Role
from jarvis.agent.runtime import AgentRuntime, GenerationDefaults
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.adapters.time_provider import SystemTimeProvider
from jarvis.context.aggregator import ContextAggregator
from jarvis.context.engine import ContextEngine
from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE as EVENTS_IN_MEMORY
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.events.bus import EventBus
from jarvis.events.event import Event, new_event_id
from jarvis.events.publisher import EventPublisher
from jarvis.memory.adapters.event_consumer import MEMORY_EVENT_TYPES, MemoryEventConsumer
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE as MEMORY_IN_MEMORY
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.ports import MemoryCriteria
from tests.agent_doubles import StubLLMProvider, decision_json

NOW = datetime.now(UTC)


def stated_preference(content: str, subject: str) -> Event:
    return Event(
        event_id=new_event_id(),
        event_type="user.stated_preference",
        source="manual-cli",
        occurred_at=NOW - timedelta(minutes=1),
        payload={"subject": subject, "content": content},
    )


def test_an_event_becomes_memory_and_then_informs_a_decision() -> None:
    """O ciclo inteiro da Fase 4, com um único fake: o modelo.

    evento → Event Store → consumer → memória → contexto → Agent → Decision.
    """
    llm = StubLLMProvider([decision_json(type="notify", message="você prefere café sem açúcar")])

    with (
        SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
        SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository,
        SqliteContextSnapshotRepository.open(":memory:") as snapshots,
    ):
        manager = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        EventPublisher(store=store, bus=bus).publish(
            stated_preference("prefere café sem açúcar", "cafe.acucar")
        )

        engine = ContextEngine(
            aggregator=ContextAggregator(providers=[SystemTimeProvider()]), snapshots=snapshots
        )
        engine.rebuild_from(store)
        engine.refresh()

        runtime = AgentRuntime(
            llm=llm,
            context_reader=engine.current,
            memory=manager,
            generation=GenerationDefaults(),
        )
        turn = runtime.handle(
            UserMessage(text="como eu gosto de café?", at=NOW, conversation_id="conv-integration")
        )

    assert turn.decision.type is DecisionType.NOTIFY
    assert turn.used_memory_ids, "a memória criada pelo evento chegou ao raciocínio"

    envelope = json.loads(llm.requests[0].messages[0].content)
    assert "café sem açúcar" in json.dumps(envelope["relevant_memories"], ensure_ascii=False)
    assert envelope["current_context"], "o contexto reconstruído chegou ao envelope"


def test_a_recorded_event_can_be_evaluated_proactively() -> None:
    llm = StubLLMProvider([decision_json(type="ignore", message=None, reason="rotina")])

    with (
        SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
        SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository,
    ):
        recorded = store.append(stated_preference("prefere silêncio à noite", "ruido.noite"))
        manager = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())

        runtime = AgentRuntime(
            llm=llm,
            context_reader=lambda: ContextEngine(
                aggregator=ContextAggregator(providers=[SystemTimeProvider()]),
                snapshots=_NullSnapshots(),
            ).current(),
            memory=manager,
            importance_threshold=0.0,
        )
        turn = runtime.handle(
            EventTrigger.from_recorded(recorded.event),
            recent_events=(EventSummary.from_recorded(recorded.event),),
        )

    assert turn.decision.type is DecisionType.IGNORE
    assert turn.decision.causation_id == recorded.event.event.event_id
    assert turn.decision.correlation_id == recorded.event.event.correlation_id
    assert turn.importance is not None, "o caminho proativo sempre avalia importância"


def test_a_trivial_event_stays_silent_without_calling_the_model() -> None:
    """Controle de ruído (`PHASE-4.md §14`) com componentes reais: evento velho,
    memória vazia, nenhuma chamada."""
    llm = StubLLMProvider()

    with SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository:
        runtime = AgentRuntime(
            llm=llm,
            context_reader=lambda: ContextEngine(
                aggregator=ContextAggregator(providers=[SystemTimeProvider()]),
                snapshots=_NullSnapshots(),
            ).current(),
            memory=MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider()),
            importance_threshold=0.9,
        )
        turn = runtime.handle(
            EventTrigger(
                event_id="evt-antigo",
                event_type="demo.happened",
                source="test-suite",
                occurred_at=NOW - timedelta(days=3),
                correlation_id="corr-antigo",
            )
        )

    assert llm.calls == 0
    assert turn.decision.type is DecisionType.IGNORE
    assert turn.consulted_llm is False


def test_a_three_turn_conversation_keeps_its_history_in_order() -> None:
    llm = StubLLMProvider(
        [
            decision_json(type="notify", message="primeira resposta"),
            decision_json(type="notify", message="segunda resposta"),
            decision_json(type="notify", message="terceira resposta"),
        ]
    )

    with SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository:
        runtime = AgentRuntime(
            llm=llm,
            context_reader=lambda: ContextEngine(
                aggregator=ContextAggregator(providers=[SystemTimeProvider()]),
                snapshots=_NullSnapshots(),
            ).current(),
            memory=MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider()),
        )

        conversation = Conversation(conversation_id="conv-3")
        for text in ("oi", "tudo bem?", "e depois?"):
            turn = runtime.handle(
                UserMessage(text=text, at=NOW, conversation_id="conv-3"),
                conversation=conversation,
            )
            conversation = conversation.append(ConversationTurn(role=Role.USER, text=text, at=NOW))
            assert turn.decision.message is not None
            conversation = conversation.append(
                ConversationTurn(role=Role.ASSISTANT, text=turn.decision.message, at=NOW)
            )

    third = json.loads(llm.requests[2].messages[0].content)
    assert [entry["text"] for entry in third["conversation"]] == [
        "oi",
        "primeira resposta",
        "tudo bem?",
        "segunda resposta",
    ]
    assert all(
        json.loads(request.messages[0].content)["trigger"]["kind"] == "user_message"
        for request in llm.requests
    )


def test_the_agent_writes_nothing_to_memory_or_to_the_event_store() -> None:
    """Fim de escopo da Fase 4: o agente decide e para. Aplicar a decisão
    depende do Policy Engine (Fase 5) e do Notification System (7.3)."""
    llm = StubLLMProvider(
        [
            decision_json(
                type="remember",
                message=None,
                memory={"type": "semantic", "content": "o usuário mora em São Paulo"},
            )
        ]
    )

    with (
        SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
        SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as repository,
    ):
        manager = MemoryManager(repository=repository, embeddings=HashingEmbeddingProvider())
        runtime = AgentRuntime(
            llm=llm,
            context_reader=lambda: ContextEngine(
                aggregator=ContextAggregator(providers=[SystemTimeProvider()]),
                snapshots=_NullSnapshots(),
            ).current(),
            memory=manager,
        )

        turn = runtime.handle(UserMessage(text="moro em SP", at=NOW, conversation_id="c-1"))

        assert turn.decision.type is DecisionType.REMEMBER
        assert repository.search(MemoryCriteria()) == []
        assert list(store.read_latest(limit=10)) == []


class _NullSnapshots:
    """O Context Engine exige um repositório de snapshot; estes testes nunca
    capturam um. Um double vazio é mais honesto que abrir um banco só para
    satisfazer a assinatura."""

    def save(self, snapshot: object) -> None:  # pragma: no cover - nunca chamado
        raise AssertionError("nenhum destes testes captura snapshot")

    def latest(self) -> None:  # pragma: no cover - nunca chamado
        return None

    def read_captured_between(self, *args: object, **kwargs: object) -> tuple[()]:
        return ()  # pragma: no cover - nunca chamado

    def expire_before(self, cutoff: object) -> int:  # pragma: no cover - nunca chamado
        return 0
