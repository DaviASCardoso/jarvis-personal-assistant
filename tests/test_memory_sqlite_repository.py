import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.embedding import EmbeddingModel
from jarvis.memory.errors import (
    InvalidMemoryError,
    MemoryReadError,
    MemoryRepositoryError,
    MemoryWriteError,
)
from jarvis.memory.memory import MemoryType
from jarvis.memory.ports import MemoryCriteria
from tests.memory_doubles import frozen_clock, make_embedding, make_memory

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


@pytest.fixture
def repository() -> Iterator[SqliteMemoryRepository]:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE, clock=frozen_clock(NOON)) as opened:
        yield opened


class TestAddAndGet:
    def test_round_trips_intact(self, repository: SqliteMemoryRepository) -> None:
        memory = make_memory(content="prefere python", tags=["dev"])

        stored = repository.add(memory, recorded_at=NOON)

        assert repository.get(memory.memory_id) == stored
        assert stored.memory == memory
        assert stored.confidence == memory.confidence

    def test_get_missing_id_is_none(self, repository: SqliteMemoryRepository) -> None:
        assert repository.get("does-not-exist") is None

    def test_duplicate_memory_id_is_a_write_error(self, repository: SqliteMemoryRepository) -> None:
        memory = make_memory(memory_id="dup-1")
        repository.add(memory, recorded_at=NOON)

        with pytest.raises(MemoryWriteError, match="já existe"):
            repository.add(make_memory(memory_id="dup-1"), recorded_at=NOON)

    def test_survives_reopening_the_file(self, tmp_path: Path) -> None:
        database = tmp_path / "data" / "memory.db"
        memory = make_memory(memory_id="m-1", content="prefere rust")
        with SqliteMemoryRepository.open(database) as repository:
            repository.add(memory, recorded_at=NOON)

        with SqliteMemoryRepository.open(database) as reopened:
            recovered = reopened.get("m-1")

        assert recovered is not None
        assert recovered.memory.content == "prefere rust"

    def test_opening_twice_is_idempotent(self, tmp_path: Path) -> None:
        database = tmp_path / "memory.db"

        with SqliteMemoryRepository.open(database):
            pass
        with SqliteMemoryRepository.open(database) as second:
            assert second.get("anything") is None


class TestSearchFilters:
    def test_filters_by_type(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="a", type=MemoryType.EPISODIC), recorded_at=NOON)
        repository.add(make_memory(memory_id="b", type=MemoryType.SEMANTIC), recorded_at=NOON)

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.SEMANTIC})))

        assert [item.memory.memory_id for item in found] == ["b"]

    def test_filters_by_subject(self, repository: SqliteMemoryRepository) -> None:
        repository.add(
            make_memory(memory_id="a", type=MemoryType.PREFERENCE, subject="preference.language"),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(memory_id="b", type=MemoryType.PREFERENCE, subject="preference.coffee"),
            recorded_at=NOON,
        )

        found = repository.search(MemoryCriteria(subject="preference.language"))

        assert [item.memory.memory_id for item in found] == ["a"]

    def test_filters_by_scope(self, repository: SqliteMemoryRepository) -> None:
        repository.add(
            make_memory(memory_id="a", type=MemoryType.TASK, scope="task-1"), recorded_at=NOON
        )
        repository.add(
            make_memory(memory_id="b", type=MemoryType.TASK, scope="task-2"), recorded_at=NOON
        )

        found = repository.search(MemoryCriteria(scope="task-1"))

        assert [item.memory.memory_id for item in found] == ["a"]

    def test_filters_by_created_at_window(self, repository: SqliteMemoryRepository) -> None:
        repository.add(
            make_memory(memory_id="a", created_at=NOON - timedelta(days=2)), recorded_at=NOON
        )
        repository.add(make_memory(memory_id="b", created_at=NOON), recorded_at=NOON)
        repository.add(
            make_memory(memory_id="c", created_at=NOON + timedelta(days=2)), recorded_at=NOON
        )

        found = repository.search(
            MemoryCriteria(
                created_from=NOON - timedelta(days=1), created_until=NOON + timedelta(days=1)
            )
        )

        assert [item.memory.memory_id for item in found] == ["b"]

    def test_filters_by_minimum_importance(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="low", importance=0.2), recorded_at=NOON)
        repository.add(make_memory(memory_id="high", importance=0.9), recorded_at=NOON)

        found = repository.search(MemoryCriteria(minimum_importance=0.5))

        assert [item.memory.memory_id for item in found] == ["high"]

    def test_filters_by_tags_requiring_all_present(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a", tags=["dev", "python"]), recorded_at=NOON)
        repository.add(make_memory(memory_id="b", tags=["dev"]), recorded_at=NOON)

        found = repository.search(MemoryCriteria(tags=frozenset({"dev", "python"})))

        assert [item.memory.memory_id for item in found] == ["a"]

    def test_filters_by_entities_requiring_all_present(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a", entities=["python", "rust"]), recorded_at=NOON)
        repository.add(make_memory(memory_id="b", entities=["python"]), recorded_at=NOON)

        found = repository.search(MemoryCriteria(entities=frozenset({"python", "rust"})))

        assert [item.memory.memory_id for item in found] == ["a"]

    def test_filters_by_active_at_excludes_not_yet_valid_and_expired(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(
            make_memory(memory_id="future", valid_from=NOON + timedelta(days=1)),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(
                memory_id="past",
                type=MemoryType.WORKING,
                valid_from=NOON - timedelta(days=2),
                valid_until=NOON - timedelta(days=1),
            ),
            recorded_at=NOON,
        )
        repository.add(make_memory(memory_id="current", valid_from=NOON), recorded_at=NOON)

        found = repository.search(MemoryCriteria(active_at=NOON))

        assert [item.memory.memory_id for item in found] == ["current"]

    def test_filters_by_embedding_model(self, repository: SqliteMemoryRepository) -> None:
        model_a = EmbeddingModel(provider="a", model="v1", dimensions=4)
        model_b = EmbeddingModel(provider="b", model="v1", dimensions=4)
        repository.add(
            make_memory(memory_id="a", embedding=make_embedding(model=model_a)),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(memory_id="b", embedding=make_embedding(model=model_b)),
            recorded_at=NOON,
        )
        repository.add(make_memory(memory_id="c"), recorded_at=NOON)

        found = repository.search(MemoryCriteria(embedding_model=model_a))

        assert [item.memory.memory_id for item in found] == ["a"]

    def test_excludes_invalidated_by_default_and_includes_when_asked(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.invalidate("a", reason="usuário pediu", moment=NOON)

        assert repository.search(MemoryCriteria()) == []
        included = repository.search(MemoryCriteria(include_invalidated=True))
        assert [item.memory.memory_id for item in included] == ["a"]

    def test_excludes_superseded_by_default_and_includes_when_asked(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.add(make_memory(memory_id="b"), recorded_at=NOON)
        repository.supersede("a", by="b", moment=LATER)

        found_default = {item.memory.memory_id for item in repository.search(MemoryCriteria())}
        assert found_default == {"b"}
        found_all = {
            item.memory.memory_id
            for item in repository.search(MemoryCriteria(include_superseded=True))
        }
        assert found_all == {"a", "b"}

    def test_honours_limit_after_all_filters(self, repository: SqliteMemoryRepository) -> None:
        for index in range(3):
            repository.add(make_memory(memory_id=f"m-{index}"), recorded_at=NOON)

        found = repository.search(MemoryCriteria(limit=2))

        assert len(found) == 2

    def test_results_are_ordered_by_persistence(self, repository: SqliteMemoryRepository) -> None:
        for index in range(3):
            repository.add(make_memory(memory_id=f"m-{index}"), recorded_at=NOON)

        found = repository.search(MemoryCriteria())

        assert [item.memory.memory_id for item in found] == ["m-0", "m-1", "m-2"]

    def test_combined_filters_apply_as_and(self, repository: SqliteMemoryRepository) -> None:
        repository.add(
            make_memory(memory_id="match", type=MemoryType.EPISODIC, importance=0.8, tags=["x"]),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(
                memory_id="wrong-type", type=MemoryType.SEMANTIC, importance=0.8, tags=["x"]
            ),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(
                memory_id="low-importance", type=MemoryType.EPISODIC, importance=0.1, tags=["x"]
            ),
            recorded_at=NOON,
        )

        found = repository.search(
            MemoryCriteria(
                types=frozenset({MemoryType.EPISODIC}),
                minimum_importance=0.5,
                tags=frozenset({"x"}),
            )
        )

        assert [item.memory.memory_id for item in found] == ["match"]


class TestLifecycleOperations:
    def test_record_access_increments_and_stamps(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        first = repository.record_access("a", moment=NOON)
        second = repository.record_access("a", moment=LATER)

        assert (first.access_count, second.access_count) == (1, 2)
        assert second.last_accessed_at == LATER
        # Acesso não é evidência nova: não mexe em updated_at.
        assert second.updated_at == NOON

    def test_reinforce_updates_confidence_and_count(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a", confidence=0.5), recorded_at=NOON)

        stored = repository.reinforce("a", confidence=0.67, moment=LATER)

        assert stored.confidence == 0.67
        assert stored.reinforced_count == 1
        assert stored.updated_at == LATER
        # O valor inicial afirmado permanece intacto.
        assert stored.memory.confidence == 0.5

    def test_reinforce_rejects_out_of_range_confidence(
        self, repository: SqliteMemoryRepository
    ) -> None:
        """Validação de domínio, não falha de I/O — levanta antes de tocar o banco."""
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        with pytest.raises(InvalidMemoryError, match="confidence"):
            repository.reinforce("a", confidence=1.5, moment=NOON)

    def test_invalidate_sets_reason_and_timestamp(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        stored = repository.invalidate("a", reason="usuário pediu", moment=LATER)

        assert stored.invalidated_at == LATER
        assert stored.invalidation_reason == "usuário pediu"

    def test_invalidate_is_idempotent(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        first = repository.invalidate("a", reason="motivo 1", moment=NOON)

        second = repository.invalidate("a", reason="motivo 2", moment=LATER)

        assert second == first
        assert second.invalidation_reason == "motivo 1"

    def test_supersede_closes_valid_until_and_links(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a", valid_from=NOON), recorded_at=NOON)
        repository.add(make_memory(memory_id="b", valid_from=LATER), recorded_at=NOON)

        stored = repository.supersede("a", by="b", moment=LATER)

        assert stored.superseded_by == "b"
        assert stored.memory.valid_until == LATER

    def test_supersede_does_not_extend_an_already_expired_memory(
        self, repository: SqliteMemoryRepository
    ) -> None:
        expiry = NOON + timedelta(minutes=30)
        repository.add(
            make_memory(
                memory_id="a", type=MemoryType.WORKING, valid_from=NOON, valid_until=expiry
            ),
            recorded_at=NOON,
        )
        repository.add(make_memory(memory_id="b"), recorded_at=NOON)

        stored = repository.supersede("a", by="b", moment=LATER)

        assert stored.memory.valid_until == expiry

    def test_supersede_is_idempotent_for_the_same_successor(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.add(make_memory(memory_id="b"), recorded_at=NOON)
        first = repository.supersede("a", by="b", moment=LATER)

        second = repository.supersede("a", by="b", moment=LATER + timedelta(hours=1))

        assert second == first

    def test_supersede_rejects_a_conflicting_successor(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.add(make_memory(memory_id="b"), recorded_at=NOON)
        repository.add(make_memory(memory_id="c"), recorded_at=NOON)
        repository.supersede("a", by="b", moment=LATER)

        with pytest.raises(MemoryWriteError, match="já foi superseded"):
            repository.supersede("a", by="c", moment=LATER)

    def test_replace_embedding_swaps_the_vector_and_model(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(
            make_memory(memory_id="a", embedding=make_embedding((1.0, 0.0, 0.0, 0.0))),
            recorded_at=NOON,
        )
        new_model = EmbeddingModel(provider="new", model="v2", dimensions=3)

        stored = repository.replace_embedding(
            "a", make_embedding((0.1, 0.2, 0.3), model=new_model), moment=LATER
        )

        assert stored.memory.embedding is not None
        assert stored.memory.embedding.model == new_model
        assert stored.updated_at == LATER

    @pytest.mark.parametrize(
        "call",
        [
            lambda repo: repo.record_access("missing", moment=NOON),
            lambda repo: repo.reinforce("missing", confidence=0.5, moment=NOON),
            lambda repo: repo.invalidate("missing", reason="x", moment=NOON),
            lambda repo: repo.supersede("missing", by="other", moment=NOON),
        ],
    )
    def test_lifecycle_operations_on_a_missing_memory_are_write_errors(
        self, repository: SqliteMemoryRepository, call: object
    ) -> None:
        with pytest.raises(MemoryWriteError, match="não encontrada"):
            call(repository)  # type: ignore[operator]


class TestPurge:
    def test_removes_the_row(self, repository: SqliteMemoryRepository) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        assert repository.purge("a") is True
        assert repository.get("a") is None

    def test_missing_id_returns_false(self, repository: SqliteMemoryRepository) -> None:
        assert repository.purge("does-not-exist") is False


class TestImmutability:
    def test_content_cannot_be_updated_even_from_outside_the_adapter(self, tmp_path: Path) -> None:
        database = tmp_path / "memory.db"
        with SqliteMemoryRepository.open(database) as repository:
            repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE memories SET content = 'outro'")

    def test_valid_until_is_the_one_column_the_trigger_lets_through(self, tmp_path: Path) -> None:
        """`valid_until` é a exceção nomeada — só ela escapa do trigger de conteúdo."""
        database = tmp_path / "memory.db"
        with SqliteMemoryRepository.open(database) as repository:
            repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        closing = (NOON + timedelta(days=1)).isoformat()
        with sqlite3.connect(database) as raw:
            raw.execute("UPDATE memories SET valid_until = ? WHERE memory_id = 'a'", (closing,))
            stored_value = raw.execute(
                "SELECT valid_until FROM memories WHERE memory_id = 'a'"
            ).fetchone()[0]

        assert stored_value == closing


class TestFailures:
    def test_a_closed_connection_becomes_an_infrastructure_error(
        self, repository: SqliteMemoryRepository
    ) -> None:
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.close()

        with pytest.raises(MemoryWriteError):
            repository.add(make_memory(memory_id="b"), recorded_at=NOON)
        with pytest.raises(MemoryReadError):
            repository.get("a")

    def test_an_unopenable_database_is_reported(self, tmp_path: Path) -> None:
        occupied = tmp_path / "occupied"
        occupied.write_text("not a directory", encoding="utf-8")

        with pytest.raises(MemoryRepositoryError):
            SqliteMemoryRepository.open(occupied / "memory.db")

    def test_a_corrupted_row_is_reported(self, tmp_path: Path) -> None:
        database = tmp_path / "memory.db"
        with SqliteMemoryRepository.open(database) as repository:
            repository.add(make_memory(memory_id="a"), recorded_at=NOON)

        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO memories (memory_id, type, content, content_fingerprint, "
                "origin, created_at, recorded_at, valid_from, importance, "
                "initial_confidence, confidence, entities, tags, derived_from, updated_at) "
                "VALUES ('b', 'not-a-type', 'x', 'fp', 'user', ?, ?, ?, 0.5, 0.5, 0.5, "
                "'[]', '[]', '[]', ?)",
                (NOON.isoformat(), NOON.isoformat(), NOON.isoformat(), NOON.isoformat()),
            )

        with (
            SqliteMemoryRepository.open(database) as reopened,
            pytest.raises(MemoryReadError),
        ):
            reopened.get("b")
