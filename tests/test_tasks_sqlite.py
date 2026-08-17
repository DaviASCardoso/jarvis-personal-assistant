"""Testes de `SqliteTaskRepository` (Fase 7.5)."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.tasks.adapters.sqlite_tasks import SqliteTaskRepository
from jarvis.tasks.errors import TaskWriteError, UnknownTaskError
from jarvis.tasks.model import BackgroundTask, TaskStatus
from tests.tasks_doubles import make_request

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _task(**overrides: object) -> BackgroundTask:
    kwargs: dict[str, object] = {
        "task_id": "t1",
        "request": make_request(),
        "status": TaskStatus.PENDING,
        "attempts": 0,
        "max_attempts": 3,
        "next_attempt_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }
    kwargs.update(overrides)
    return BackgroundTask(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def repository() -> SqliteTaskRepository:
    return SqliteTaskRepository.open(":memory:")


def test_put_and_get_roundtrip(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    found = repository.get("t1")
    assert found is not None
    assert found.request.skill == "test.skill"
    assert found.status is TaskStatus.PENDING


def test_get_unknown_returns_none(repository: SqliteTaskRepository) -> None:
    assert repository.get("missing") is None


def test_put_duplicate_task_id_raises(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    with pytest.raises(TaskWriteError):
        repository.put(_task())


def test_list_by_status_filters(repository: SqliteTaskRepository) -> None:
    repository.put(_task(task_id="t1", status=TaskStatus.PENDING))
    repository.put(_task(task_id="t2", status=TaskStatus.FAILED))
    found = repository.list_by_status(TaskStatus.PENDING)
    assert [task.task_id for task in found] == ["t1"]


def test_due_only_returns_pending_or_retrying_before_the_moment(
    repository: SqliteTaskRepository,
) -> None:
    repository.put(_task(task_id="due", status=TaskStatus.PENDING, next_attempt_at=NOW))
    repository.put(
        _task(
            task_id="future",
            status=TaskStatus.PENDING,
            next_attempt_at=NOW + timedelta(hours=1),
        )
    )
    repository.put(_task(task_id="succeeded", status=TaskStatus.SUCCEEDED, next_attempt_at=NOW))

    found = repository.due(moment=NOW)
    assert [task.task_id for task in found] == ["due"]


def test_mark_running_then_succeeded(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    repository.mark_running("t1", moment=NOW)
    settled = repository.mark_succeeded("t1", moment=NOW)
    assert settled.status is TaskStatus.SUCCEEDED


def test_mark_failed_records_the_error(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    settled = repository.mark_failed("t1", moment=NOW, error="boom")
    assert settled.status is TaskStatus.FAILED
    assert settled.last_error == "boom"


def test_schedule_retry_increments_attempts(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    settled = repository.schedule_retry(
        "t1", moment=NOW, next_attempt_at=NOW + timedelta(seconds=30), error="transient"
    )
    assert settled.status is TaskStatus.RETRYING
    assert settled.attempts == 1
    assert settled.next_attempt_at == NOW + timedelta(seconds=30)


def test_cancel_sets_cancelled_status(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    settled = repository.cancel("t1", moment=NOW)
    assert settled.status is TaskStatus.CANCELLED


def test_mark_unknown_task_raises(repository: SqliteTaskRepository) -> None:
    with pytest.raises(UnknownTaskError):
        repository.mark_succeeded("missing", moment=NOW)


def test_request_parameters_are_immutable(repository: SqliteTaskRepository) -> None:
    repository.put(_task())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repository._connection.execute("UPDATE tasks SET skill = 'other' WHERE task_id = 't1'")
