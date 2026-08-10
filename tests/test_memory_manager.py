from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.embedding import EmbeddingModel
from jarvis.memory.errors import InvalidMemoryError, MemoryWriteError
from jarvis.memory.manager import (
    REINFORCEMENT_CAP,
    REINFORCEMENT_RATE,
    MemoryManager,
    reinforced_confidence,
)
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.memory.ports import MemoryCriteria
from jarvis.memory.retrieval import RetrievalQuery
from tests.memory_doubles import (
    FailingEmbeddingProvider,
    FakeMemoryRepository,
    StubEmbeddingProvider,
    frozen_clock,
    make_embedding,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)
MUCH_LATER = NOON + timedelta(hours=2)


class TestReinforcementCurve:
    def test_matches_the_documented_sequence(self) -> None:
        value = 0.50
        expected = [0.67, 0.78, 0.85, 0.90]
        for target in expected:
            value = reinforced_confidence(value)
            assert value == pytest.approx(target, abs=0.01)

    def test_never_reaches_the_cap(self) -> None:
        value = 0.50
        for _ in range(200):
            value = reinforced_confidence(value)
        assert value < 1.0
        assert value < REINFORCEMENT_CAP

    def test_rate_and_cap_constants_are_the_documented_values(self) -> None:
        assert REINFORCEMENT_CAP == 0.99
        assert REINFORCEMENT_RATE == 0.34


class TestRecordAccess:
    def test_increments_the_counter_and_stamps_the_moment(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        accessed = manager.record_access(stored.memory.memory_id)

        assert accessed.access_count == 1
        assert accessed.last_accessed_at == LATER

    def test_retrieve_never_calls_record_access_on_its_own(self) -> None:
        """Consultar não é usar — só quem efetivamente usa a memória registra."""
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        manager.retrieve(RetrievalQuery())
        manager.retrieve(RetrievalQuery())

        results = manager.retrieve(RetrievalQuery()).results
        assert results[0].memory.access_count == 0


class TestExplicitReinforce:
    def test_increases_confidence_and_count(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
            confidence=0.5,
        )

        reinforced = manager.reinforce(stored.memory.memory_id)

        assert reinforced.confidence == pytest.approx(reinforced_confidence(0.5))
        assert reinforced.reinforced_count == 1
        assert reinforced.updated_at == LATER

    def test_missing_memory_is_a_write_error(self) -> None:
        manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))

        with pytest.raises(MemoryWriteError, match="não encontrada"):
            manager.reinforce("does-not-exist")


class TestForget:
    def test_invalidates_without_erasing(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        forgotten = manager.forget(stored.memory.memory_id, reason="usuário pediu")

        assert forgotten.invalidated_at == LATER
        assert forgotten.invalidation_reason == "usuário pediu"
        assert repository.get(stored.memory.memory_id) is not None

    def test_forgotten_memory_leaves_the_default_retrieval(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )
        manager.forget(stored.memory.memory_id, reason="usuário pediu")

        outcome = manager.retrieve(RetrievalQuery())

        assert outcome.results == ()


class TestForgetScope:
    def test_invalidates_every_memory_in_the_scope(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        manager.remember(
            type=MemoryType.TASK,
            content="passo 1",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="x"),
            scope="task-1",
            confidence=0.5,
        )
        manager.remember(
            type=MemoryType.TASK,
            content="passo 2",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="y"),
            scope="task-1",
            confidence=0.5,
        )
        manager.remember(
            type=MemoryType.TASK,
            content="outra tarefa",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="z"),
            scope="task-2",
            confidence=0.5,
        )

        forgotten = manager.forget_scope("task-1", reason="tarefa concluída")

        assert len(forgotten) == 2
        assert all(item.invalidated_at == LATER for item in forgotten)
        remaining = manager.retrieve(RetrievalQuery()).results
        assert [item.memory.memory.scope for item in remaining] == ["task-2"]

    def test_an_empty_scope_forgets_nothing(self) -> None:
        manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))

        assert manager.forget_scope("no-such-task", reason="x") == ()


class TestPurge:
    def test_removes_the_memory_physically(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="x",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        assert manager.purge(stored.memory.memory_id) is True
        assert repository.get(stored.memory.memory_id) is None

    def test_missing_memory_returns_false(self) -> None:
        manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))

        assert manager.purge("does-not-exist") is False


class TestReembed:
    OLD_MODEL = EmbeddingModel(provider="old", model="v1", dimensions=4)
    NEW_MODEL = EmbeddingModel(provider="new", model="v2", dimensions=4)

    def test_replaces_incompatible_embeddings(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            embed=False,
        )
        repository.replace_embedding(
            stored.memory.memory_id, make_embedding(model=self.OLD_MODEL), moment=NOON
        )
        new_provider = StubEmbeddingProvider(model=self.NEW_MODEL)

        updated = manager.reembed(embeddings=new_provider)

        assert updated == 1
        recovered = repository.get(stored.memory.memory_id)
        assert recovered is not None
        assert recovered.memory.embedding is not None
        assert recovered.memory.embedding.model == self.NEW_MODEL

    def test_compatible_embeddings_are_left_untouched(self) -> None:
        repository = FakeMemoryRepository()
        provider = StubEmbeddingProvider(model=self.NEW_MODEL)
        manager = MemoryManager(
            repository=repository, embeddings=provider, clock=frozen_clock(NOON)
        )
        manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        updated = manager.reembed()

        assert updated == 0

    def test_memories_without_an_embedding_are_never_touched(self) -> None:
        """Ausência intencional (ex. WORKING) não é incompatibilidade."""
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        manager.remember(
            type=MemoryType.WORKING,
            content="lembrete",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="x"),
            confidence=0.5,
            valid_until=NOON + timedelta(hours=1),
        )
        provider = StubEmbeddingProvider(model=self.NEW_MODEL)

        updated = manager.reembed(embeddings=provider)

        assert updated == 0
        assert provider.embedded == []

    def test_provider_failure_is_skipped_and_reported(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            embed=False,
        )
        repository.replace_embedding(
            stored.memory.memory_id, make_embedding(model=self.OLD_MODEL), moment=NOON
        )
        failing = FailingEmbeddingProvider(model=self.NEW_MODEL)

        updated = manager.reembed(embeddings=failing)

        assert updated == 0
        recovered = repository.get(stored.memory.memory_id)
        assert recovered is not None
        assert recovered.memory.embedding is not None
        assert recovered.memory.embedding.model == self.OLD_MODEL

    def test_requires_a_configured_provider(self) -> None:
        manager = MemoryManager(repository=FakeMemoryRepository(), clock=frozen_clock(NOON))

        with pytest.raises(InvalidMemoryError, match="EmbeddingProvider"):
            manager.reembed()


def test_memory_manager_works_without_any_embedding_provider_at_all() -> None:
    """PHASE-3.md §17: o Memory System funciona mesmo sem nenhum LLM configurado."""
    repository = FakeMemoryRepository()
    manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER, MUCH_LATER))

    stored = manager.remember(
        type=MemoryType.PREFERENCE,
        content="prefere python",
        provenance=Provenance(origin=MemoryOrigin.USER),
        subject="preference.language",
    )
    manager.record_access(stored.memory.memory_id)
    manager.reinforce(stored.memory.memory_id)
    outcome = manager.retrieve(RetrievalQuery(criteria=MemoryCriteria()))
    manager.forget(stored.memory.memory_id, reason="fim do teste")

    assert outcome.results[0].memory.memory.memory_id == stored.memory.memory_id
