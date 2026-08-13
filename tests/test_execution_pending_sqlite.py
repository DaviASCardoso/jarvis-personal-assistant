"""O repositório de ações em SQLite: estado operacional, com imutabilidade onde importa."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.execution.adapters.sqlite_actions import IN_MEMORY_DATABASE, SqliteActionRepository
from jarvis.execution.errors import ActionWriteError, UnknownExecutionError
from jarvis.execution.model import Actor, ExecutionStatus, PendingAction

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(minutes=10)


def make_pending(**changes: object) -> PendingAction:
    fields: dict[str, object] = {
        "execution_id": "exec-1",
        "skill": "file.write",
        "parameters": {"path": "nota.txt", "content": "olá"},
        "parameters_fingerprint": "f" * 64,
        "actor": Actor.USER,
        "correlation_id": "corr-1",
        "status": ExecutionStatus.AWAITING_CONFIRMATION,
        "requested_at": NOON,
        "updated_at": NOON,
        "expires_at": NOON + timedelta(minutes=15),
    }
    fields.update(changes)
    return PendingAction(**fields)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SqliteActionRepository:
    return SqliteActionRepository.open(IN_MEMORY_DATABASE)


class TestRoundTrip:
    def test_what_goes_in_comes_back(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending())

        found = repository.get("exec-1")

        assert found is not None
        assert found.skill == "file.write"
        assert dict(found.parameters) == {"path": "nota.txt", "content": "olá"}
        assert found.actor is Actor.USER
        assert found.status is ExecutionStatus.AWAITING_CONFIRMATION
        assert found.requested_at == NOON

    def test_nested_parameters_survive(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending(parameters={"a": {"b": [1, 2, True, None]}}))

        found = repository.get("exec-1")

        assert found is not None
        assert dict(found.parameters) == {"a": {"b": [1, 2, True, None]}}

    def test_an_absent_execution_is_none(self, repository: SqliteActionRepository) -> None:
        assert repository.get("nao-existe") is None


class TestImmutability:
    def test_put_is_not_an_upsert(self, repository: SqliteActionRepository) -> None:
        """Reescrever uma execução em silêncio apagaria a trilha do que foi pedido."""
        repository.put(make_pending())

        with pytest.raises(ActionWriteError, match="já registrada"):
            repository.put(make_pending(skill="outra.skill"))

    def test_marking_an_unknown_execution_raises(self, repository: SqliteActionRepository) -> None:
        with pytest.raises(UnknownExecutionError):
            repository.mark("nao-existe", status=ExecutionStatus.COMPLETED, moment=LATER)


class TestTransitions:
    def test_marking_changes_status_and_reason(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending())

        updated = repository.mark(
            "exec-1", status=ExecutionStatus.DENIED, moment=LATER, reason="skill_denylisted"
        )

        assert updated.status is ExecutionStatus.DENIED
        assert updated.reason == "skill_denylisted"
        assert updated.updated_at == LATER

    def test_marking_never_touches_the_parameters(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending())

        updated = repository.mark("exec-1", status=ExecutionStatus.COMPLETED, moment=LATER)

        assert dict(updated.parameters) == {"path": "nota.txt", "content": "olá"}
        assert updated.parameters_fingerprint == "f" * 64

    def test_confirming_records_the_moment_without_changing_the_status(
        self, repository: SqliteActionRepository
    ) -> None:
        """Confirmar é fato sobre o usuário; executar ainda passa pela política."""
        repository.put(make_pending())

        updated = repository.confirm("exec-1", moment=LATER)

        assert updated.confirmed_at == LATER
        assert updated.is_confirmed
        assert updated.status is ExecutionStatus.AWAITING_CONFIRMATION


class TestQueries:
    def test_listing_by_status_is_ordered_by_request_time(
        self, repository: SqliteActionRepository
    ) -> None:
        repository.put(make_pending(execution_id="segunda", requested_at=LATER))
        repository.put(make_pending(execution_id="primeira", requested_at=NOON))

        found = repository.list_by_status(ExecutionStatus.AWAITING_CONFIRMATION)

        assert [item.execution_id for item in found] == ["primeira", "segunda"]

    def test_listing_respects_the_limit(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending(execution_id="a"))
        repository.put(make_pending(execution_id="b", requested_at=LATER))

        assert len(repository.list_by_status(ExecutionStatus.AWAITING_CONFIRMATION, limit=1)) == 1

    def test_only_the_requested_status_comes_back(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending(execution_id="esperando"))
        repository.put(
            make_pending(execution_id="feita", status=ExecutionStatus.COMPLETED, expires_at=None)
        )

        found = repository.list_by_status(ExecutionStatus.AWAITING_CONFIRMATION)

        assert [item.execution_id for item in found] == ["esperando"]


class TestExpiry:
    def test_overdue_pendings_are_marked(self, repository: SqliteActionRepository) -> None:
        repository.put(make_pending())

        expired = repository.expire_pending(moment=NOON + timedelta(hours=1))

        assert [item.execution_id for item in expired] == ["exec-1"]
        found = repository.get("exec-1")
        assert found is not None
        assert found.status is ExecutionStatus.EXPIRED
        assert found.reason == "confirmation_expired"

    def test_a_pending_that_is_still_valid_is_untouched(
        self, repository: SqliteActionRepository
    ) -> None:
        repository.put(make_pending())

        assert repository.expire_pending(moment=NOON) == []

    def test_a_pending_without_a_deadline_never_expires(
        self, repository: SqliteActionRepository
    ) -> None:
        repository.put(make_pending(expires_at=None))

        assert repository.expire_pending(moment=NOON + timedelta(days=365)) == []


class TestSchema:
    def test_the_schema_version_is_recorded(self, repository: SqliteActionRepository) -> None:
        version = repository._connection.execute("PRAGMA user_version").fetchone()[0]

        assert version == 1

    def test_the_database_can_be_reopened(self, tmp_path: object) -> None:
        from pathlib import Path

        assert isinstance(tmp_path, Path)
        database = tmp_path / "actions.db"

        with SqliteActionRepository.open(database) as first:
            first.put(make_pending())
        with SqliteActionRepository.open(database) as second:
            assert second.get("exec-1") is not None
