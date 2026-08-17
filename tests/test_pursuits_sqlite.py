"""Testes de `SqlitePursuitRepository` (Fase 10.5)."""

import sqlite3
from datetime import UTC, datetime

import pytest

from jarvis.pursuits.adapters.sqlite_pursuits import SqlitePursuitRepository
from jarvis.pursuits.errors import PursuitWriteError, UnknownPursuitError
from jarvis.pursuits.model import PursuitState, PursuitStatus

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _pursuit(**overrides: object) -> PursuitState:
    kwargs: dict[str, object] = {
        "pursuit_id": "p1",
        "goal": "organize a pasta de notas",
        "conversation_id": "c1",
        "max_steps": 6,
        "step": 1,
        "status": PursuitStatus.RUNNING,
        "last_action_result": None,
        "previous_proposal": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    kwargs.update(overrides)
    return PursuitState(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SqlitePursuitRepository:
    return SqlitePursuitRepository.open(":memory:")


def test_put_and_get_roundtrip(repository: SqlitePursuitRepository) -> None:
    repository.put(_pursuit())
    found = repository.get("p1")
    assert found is not None
    assert found.goal == "organize a pasta de notas"
    assert found.status is PursuitStatus.RUNNING


def test_get_unknown_returns_none(repository: SqlitePursuitRepository) -> None:
    assert repository.get("missing") is None


def test_put_duplicate_pursuit_id_raises(repository: SqlitePursuitRepository) -> None:
    repository.put(_pursuit())
    with pytest.raises(PursuitWriteError):
        repository.put(_pursuit())


def test_advance_updates_step_status_and_context(repository: SqlitePursuitRepository) -> None:
    repository.put(_pursuit())

    settled = repository.advance(
        "p1",
        step=2,
        status=PursuitStatus.AWAITING_CONFIRMATION,
        last_action_result={
            "skill": "file.write",
            "status": "awaiting_confirmation",
            "execution_id": "exec-1",
            "summary": "",
            "reason": "",
        },
        previous_proposal={"skill": "file.write", "parameters": {"path": "nota.txt"}},
        moment=NOW,
    )

    assert settled.step == 2
    assert settled.status is PursuitStatus.AWAITING_CONFIRMATION
    assert settled.last_action_result is not None
    assert settled.last_action_result["execution_id"] == "exec-1"
    assert settled.previous_proposal == {"skill": "file.write", "parameters": {"path": "nota.txt"}}


def test_advance_unknown_pursuit_raises(repository: SqlitePursuitRepository) -> None:
    with pytest.raises(UnknownPursuitError):
        repository.advance(
            "missing",
            step=1,
            status=PursuitStatus.RUNNING,
            last_action_result=None,
            previous_proposal=None,
            moment=NOW,
        )


def test_identity_fields_are_immutable(repository: SqlitePursuitRepository) -> None:
    repository.put(_pursuit())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repository._connection.execute("UPDATE pursuits SET goal = 'outro' WHERE pursuit_id = 'p1'")


def test_only_completed_is_not_resumable() -> None:
    for status in PursuitStatus:
        expected = status is not PursuitStatus.COMPLETED
        assert status.is_resumable is expected
