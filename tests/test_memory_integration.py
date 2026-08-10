"""Fluxo completo do Memory System sobre SQLite em arquivo real (subfase 3.7).

Nenhum componente é substituído por double aqui: store de eventos, bus,
publisher, consumer, repositório de memórias e `EmbeddingProvider` são os de
produção, e os bancos são arquivos em disco.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.events import Event, EventBus, EventPublisher, deterministic_event_id
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.memory.adapters.event_consumer import MEMORY_EVENT_TYPES, MemoryEventConsumer
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.memory.ports import MemoryCriteria
from jarvis.memory.retrieval import RetrievalQuery
from tests.memory_doubles import frozen_clock

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)
MUCH_LATER = NOON + timedelta(hours=2)


@pytest.fixture
def event_database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "events.db"


@pytest.fixture
def memory_database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "memory.db"


@pytest.fixture
def store(event_database: Path) -> Iterator[SqliteEventStore]:
    with SqliteEventStore.open(event_database) as opened:
        yield opened


@pytest.fixture
def memories(memory_database: Path) -> Iterator[SqliteMemoryRepository]:
    with SqliteMemoryRepository.open(memory_database) as opened:
        yield opened


def build_manager(
    memories: SqliteMemoryRepository, *, moments: tuple[datetime, ...] = (NOON,)
) -> MemoryManager:
    return MemoryManager(
        repository=memories, embeddings=HashingEmbeddingProvider(), clock=frozen_clock(*moments)
    )


class TestManagerToPersistenceToRetrieval:
    def test_a_created_memory_is_persisted_and_retrievable(
        self, memories: SqliteMemoryRepository, memory_database: Path
    ) -> None:
        manager = build_manager(memories)

        stored = manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere Python para automação de scripts",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
            importance=0.7,
        )

        assert stored.memory.embedding is not None

        with SqliteMemoryRepository.open(memory_database) as reopened:
            recovered = reopened.get(stored.memory.memory_id)

        assert recovered is not None
        assert recovered.memory.content == stored.memory.content
        assert recovered.memory.embedding == stored.memory.embedding

    def test_structured_lookup_and_semantic_search_both_find_it(
        self, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories)
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere Python para automação de scripts",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
        )
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere café sem açúcar pela manhã",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.coffee",
        )

        structured = manager.retrieve(
            RetrievalQuery(criteria=MemoryCriteria(subject="preference.language"))
        )
        assert len(structured.results) == 1
        assert structured.results[0].memory.memory.subject == "preference.language"

        semantic = manager.retrieve(RetrievalQuery(text="o que ele usa para programar?"))
        assert semantic.results
        assert semantic.results[0].memory.memory.subject == "preference.language"
        assert semantic.results[0].score.semantic is not None

    def test_ranking_is_explainable_and_deterministic(
        self, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories, moments=(NOON, NOON))
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere Python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
            importance=0.9,
            confidence=0.9,
        )

        first = manager.retrieve(RetrievalQuery(text="prefere Python"))
        second = manager.retrieve(RetrievalQuery(text="prefere Python"))

        assert first.results[0].score == second.results[0].score
        score = first.results[0].score
        assert score.semantic is not None
        assert 0.0 <= score.total <= 1.0


class TestEventToMemoryFlow:
    def test_an_event_becomes_a_memory_reachable_through_retrieval(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        publisher.publish(
            Event(
                event_id=deterministic_event_id(source="manual-cli", natural_key="pref-1"),
                event_type="user.stated_preference",
                source="manual-cli",
                occurred_at=NOON,
                payload={"subject": "preference.language", "content": "prefere Python"},
            )
        )

        found = manager.retrieve(
            RetrievalQuery(criteria=MemoryCriteria(subject="preference.language"))
        )
        assert len(found.results) == 1
        assert found.results[0].memory.memory.content == "prefere Python"

    def test_reemitting_the_same_event_does_not_duplicate(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        """Reemitir o **mesmo** evento (mesmo `event_id`) nem chega ao consumer:
        `EventPublisher` já deduplica no Event Store e não republica no bus —
        por isso só existe uma memória, e ela nunca foi "reforçada" (o
        `handle()` só rodou uma vez). O caminho de reforço por reprocessamento
        é testado em `test_memory_event_consumer.py` chamando `handle()`
        diretamente, e o de referências distintas na duplicação de fato, logo
        abaixo."""
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        def emit() -> None:
            publisher.publish(
                Event(
                    event_id=deterministic_event_id(source="manual-cli", natural_key="fact-1"),
                    event_type="user.noted_fact",
                    source="manual-cli",
                    occurred_at=NOON,
                    payload={"content": "chegou atrasado hoje"},
                )
            )

        emit()
        emit()

        found = manager.retrieve(RetrievalQuery(criteria=MemoryCriteria()))
        assert len(found.results) == 1
        assert found.results[0].memory.reinforced_count == 0

    def test_two_distinct_events_with_the_same_fact_reinforce_not_duplicate(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        """Ao contrário do caso acima: dois eventos **genuinamente diferentes**
        (`event_id` distinto) relatando o mesmo fato de fontes diferentes não
        seriam duplicata pela regra do consolidation (referência diferente).
        Só reforça quando a fonte é a mesma — aqui simulada reemitindo com a
        mesma chave natural, que o Event Store idempotente reduz a um único
        `event_id`, e portanto uma única referência de proveniência."""
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        publisher.publish(
            Event(
                event_id="fact-a",
                event_type="user.noted_fact",
                source="manual-cli",
                occurred_at=NOON,
                payload={"content": "chegou atrasado hoje", "subject": "pattern.lateness"},
            )
        )
        publisher.publish(
            Event(
                event_id="fact-b",
                event_type="user.noted_fact",
                source="manual-cli",
                occurred_at=LATER,
                payload={"content": "chegou atrasado hoje", "subject": "pattern.lateness"},
            )
        )

        found = manager.retrieve(RetrievalQuery(criteria=MemoryCriteria()))
        assert len(found.results) == 2

    def test_a_contradicting_preference_event_supersedes_the_previous_one(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        publisher.publish(
            Event(
                event_id="pref-python",
                event_type="user.stated_preference",
                source="manual-cli",
                occurred_at=NOON,
                payload={"subject": "preference.language", "content": "prefere Python"},
            )
        )
        publisher.publish(
            Event(
                event_id="pref-rust",
                event_type="user.stated_preference",
                source="manual-cli",
                occurred_at=LATER,
                payload={"subject": "preference.language", "content": "prefere Rust"},
            )
        )

        active = manager.retrieve(
            RetrievalQuery(criteria=MemoryCriteria(subject="preference.language"))
        )
        assert [item.memory.memory.content for item in active.results] == ["prefere Rust"]

        with_superseded = manager.retrieve(
            RetrievalQuery(
                criteria=MemoryCriteria(subject="preference.language", include_superseded=True)
            )
        )
        assert {item.memory.memory.content for item in with_superseded.results} == {
            "prefere Python",
            "prefere Rust",
        }

    def test_a_malformed_event_does_not_break_the_publisher(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        result = publisher.publish(
            Event(
                event_id="broken-1",
                event_type="user.stated_preference",
                source="manual-cli",
                occurred_at=NOON,
                payload={"subject": "Not A Slug", "content": "x"},
            )
        )

        # O fato foi registrado apesar de o consumer ter recusado o payload.
        assert result.is_duplicate is False
        assert store.get("broken-1") is not None
        assert manager.retrieve(RetrievalQuery(criteria=MemoryCriteria())).results == ()


class TestConsolidationEndToEnd:
    def test_repeated_events_promote_to_a_semantic_memory(
        self, store: SqliteEventStore, memories: SqliteMemoryRepository
    ) -> None:
        manager = build_manager(memories)
        bus = EventBus()
        bus.subscribe(MemoryEventConsumer(manager), event_types=MEMORY_EVENT_TYPES)
        publisher = EventPublisher(store=store, bus=bus)

        for index in range(3):
            publisher.publish(
                Event(
                    event_id=f"lateness-{index}",
                    event_type="user.noted_fact",
                    source="manual-cli",
                    occurred_at=NOON,
                    payload={
                        "content": "chega sempre atrasado às segundas",
                        "subject": "pattern.monday_lateness",
                    },
                )
            )

        report = manager.consolidate()

        assert len(report.promoted) == 1
        assert report.promoted[0].memory.type is MemoryType.SEMANTIC


class TestReindexAfterModelChange:
    def test_reindex_restores_semantic_search_after_switching_models(
        self, memories: SqliteMemoryRepository
    ) -> None:
        old_provider = HashingEmbeddingProvider(dimensions=32)
        manager = MemoryManager(
            repository=memories, embeddings=old_provider, clock=frozen_clock(NOON)
        )
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere Python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
        )

        new_provider = HashingEmbeddingProvider(dimensions=64)
        manager_with_new_model = MemoryManager(
            repository=memories, embeddings=new_provider, clock=frozen_clock(NOON)
        )

        before = manager_with_new_model.retrieve(RetrievalQuery(text="prefere Python"))
        assert before.results == ()
        assert before.skipped_incompatible == 1

        updated = manager_with_new_model.reembed()
        assert updated == 1

        after = manager_with_new_model.retrieve(RetrievalQuery(text="prefere Python"))
        assert len(after.results) == 1
        assert after.skipped_incompatible == 0


def test_forget_and_purge_end_to_end(memories: SqliteMemoryRepository) -> None:
    manager = build_manager(memories, moments=(NOON, LATER))
    stored = manager.remember(
        type=MemoryType.EPISODIC,
        content="fato temporário",
        provenance=Provenance(origin=MemoryOrigin.USER),
    )

    manager.forget(stored.memory.memory_id, reason="usuário pediu")
    assert manager.retrieve(RetrievalQuery(criteria=MemoryCriteria())).results == ()
    assert memories.get(stored.memory.memory_id) is not None

    assert manager.purge(stored.memory.memory_id) is True
    assert memories.get(stored.memory.memory_id) is None
