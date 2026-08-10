import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.context.adapters.sqlite_snapshots import (
    IN_MEMORY_DATABASE,
    SqliteContextSnapshotRepository,
)
from jarvis.context.errors import (
    ContextSnapshotError,
    ContextSnapshotReadError,
    ContextSnapshotWriteError,
)
from jarvis.context.model import CurrentContext, UserContext
from jarvis.context.snapshot import ContextSnapshot
from tests.context_doubles import frozen_clock, make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
WINDOW_START = NOON - timedelta(days=1)
WINDOW_END = NOON + timedelta(days=1)


def snapshot(
    identifier: str, *, captured_at: datetime, availability: str = "busy"
) -> ContextSnapshot:
    return ContextSnapshot(
        snapshot_id=identifier,
        captured_at=captured_at,
        context=CurrentContext(
            as_of=captured_at,
            user=UserContext(availability=make_observation(availability, observed_at=captured_at)),
        ),
    )


@pytest.fixture
def repository() -> Iterator[SqliteContextSnapshotRepository]:
    with SqliteContextSnapshotRepository.open(
        IN_MEMORY_DATABASE, clock=frozen_clock(NOON)
    ) as open_repository:
        yield open_repository


class TestPersistence:
    def test_saves_and_reads_back_intact(self, repository: SqliteContextSnapshotRepository) -> None:
        original = snapshot("s-1", captured_at=NOON)

        repository.save(original)

        assert repository.latest() == original

    def test_latest_is_none_when_nothing_was_captured(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        assert repository.latest() is None

    def test_survives_reopening_the_file(self, tmp_path: Path) -> None:
        database = tmp_path / "data" / "context.db"
        with SqliteContextSnapshotRepository.open(database) as repository:
            repository.save(snapshot("s-1", captured_at=NOON))

        with SqliteContextSnapshotRepository.open(database) as reopened:
            recovered = reopened.latest()

        assert recovered is not None
        assert recovered.snapshot_id == "s-1"
        assert recovered.context.user.availability is not None
        assert recovered.context.user.availability.source == "provider:test"

    def test_opening_twice_is_idempotent(self, tmp_path: Path) -> None:
        database = tmp_path / "context.db"

        with SqliteContextSnapshotRepository.open(database):
            pass
        with SqliteContextSnapshotRepository.open(database) as second:
            assert second.latest() is None

    def test_duplicate_id_is_a_write_error(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.save(snapshot("s-1", captured_at=NOON))

        with pytest.raises(ContextSnapshotWriteError):
            repository.save(snapshot("s-1", captured_at=NOON))


class TestHistory:
    def test_reads_a_half_open_window_in_capture_order(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        for index in range(3):
            repository.save(snapshot(f"s-{index}", captured_at=NOON + timedelta(hours=index)))

        found = repository.read_captured_between(NOON, NOON + timedelta(hours=2))

        assert [item.snapshot_id for item in found] == ["s-0", "s-1"]

    def test_honours_the_limit(self, repository: SqliteContextSnapshotRepository) -> None:
        for index in range(3):
            repository.save(snapshot(f"s-{index}", captured_at=NOON + timedelta(hours=index)))

        found = repository.read_captured_between(WINDOW_START, WINDOW_END, limit=2)

        assert [item.snapshot_id for item in found] == ["s-0", "s-1"]


class TestImmutability:
    def test_content_cannot_be_updated_even_from_outside_the_adapter(self, tmp_path: Path) -> None:
        database = tmp_path / "context.db"
        with SqliteContextSnapshotRepository.open(database) as repository:
            repository.save(snapshot("s-1", captured_at=NOON))

        with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE context_snapshots SET document = '{}'")

    def test_rows_cannot_be_deleted(self, tmp_path: Path) -> None:
        database = tmp_path / "context.db"
        with SqliteContextSnapshotRepository.open(database) as repository:
            repository.save(snapshot("s-1", captured_at=NOON))

        with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM context_snapshots")


class TestExpiration:
    def test_marks_older_captures_and_reports_how_many(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.save(snapshot("old", captured_at=NOON - timedelta(days=2)))
        repository.save(snapshot("recent", captured_at=NOON, availability="available"))

        expired = repository.expire_before(NOON - timedelta(days=1))

        assert expired == 1

    def test_expired_captures_leave_the_default_queries(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.save(snapshot("old", captured_at=NOON - timedelta(days=2)))
        repository.save(snapshot("recent", captured_at=NOON, availability="available"))
        repository.expire_before(NOON - timedelta(days=1))

        found = repository.read_captured_between(WINDOW_START - timedelta(days=7), WINDOW_END)

        assert [item.snapshot_id for item in found] == ["recent"]
        assert repository.latest() is not None
        assert repository.latest().snapshot_id == "recent"  # type: ignore[union-attr]

    def test_expired_evidence_is_still_readable(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.save(snapshot("old", captured_at=NOON - timedelta(days=2)))
        repository.expire_before(NOON - timedelta(days=1))

        found = repository.read_captured_between(
            WINDOW_START - timedelta(days=7), WINDOW_END, include_expired=True
        )

        assert [item.snapshot_id for item in found] == ["old"]

    def test_expiring_twice_is_idempotent(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.save(snapshot("old", captured_at=NOON - timedelta(days=2)))

        first = repository.expire_before(NOON)
        second = repository.expire_before(NOON)

        assert (first, second) == (1, 0)

    def test_nothing_is_removed_from_the_database(self, tmp_path: Path) -> None:
        database = tmp_path / "context.db"
        with SqliteContextSnapshotRepository.open(database) as repository:
            repository.save(snapshot("old", captured_at=NOON - timedelta(days=2)))
            repository.expire_before(NOON)

        with sqlite3.connect(database) as connection:
            rows = connection.execute("SELECT count(*) FROM context_snapshots").fetchone()[0]

        assert rows == 1


class TestFailures:
    def test_a_closed_connection_becomes_an_infrastructure_error(
        self, repository: SqliteContextSnapshotRepository
    ) -> None:
        repository.close()

        with pytest.raises(ContextSnapshotWriteError):
            repository.save(snapshot("s-1", captured_at=NOON))
        with pytest.raises(ContextSnapshotReadError):
            repository.latest()
        with pytest.raises(ContextSnapshotWriteError):
            repository.expire_before(NOON)

    def test_an_unopenable_database_is_reported(self, tmp_path: Path) -> None:
        occupied = tmp_path / "occupied"
        occupied.write_text("not a directory", encoding="utf-8")

        with pytest.raises(ContextSnapshotError):
            SqliteContextSnapshotRepository.open(occupied / "context.db")

    def test_a_corrupted_row_is_reported(self, tmp_path: Path) -> None:
        database = tmp_path / "context.db"
        with SqliteContextSnapshotRepository.open(database) as repository:
            repository.save(snapshot("s-1", captured_at=NOON))

        # Escrita direta, por fora do adapter: o trigger só protege UPDATE/DELETE.
        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO context_snapshots "
                "(snapshot_id, captured_at, schema_version, fingerprint, document) "
                "VALUES ('s-2', ?, 1, 'x', '{quebrado')",
                (NOON.isoformat(),),
            )

        with (
            SqliteContextSnapshotRepository.open(database) as reopened,
            pytest.raises(ContextSnapshotReadError),
        ):
            reopened.latest()
