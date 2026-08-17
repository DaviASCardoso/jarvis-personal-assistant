"""Testes de `BackgroundTask`/`TaskStatus` (Fase 7.5)."""

from datetime import UTC, datetime

import pytest

from jarvis.errors import DomainError
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


def test_valid_task_builds() -> None:
    task = _task()
    assert task.status is TaskStatus.PENDING


def test_rejects_empty_task_id() -> None:
    with pytest.raises(DomainError):
        _task(task_id=" ")


def test_rejects_max_attempts_below_one() -> None:
    with pytest.raises(DomainError):
        _task(max_attempts=0)


def test_rejects_negative_attempts() -> None:
    with pytest.raises(DomainError):
        _task(attempts=-1)


def test_rejects_naive_datetime() -> None:
    with pytest.raises(DomainError):
        _task(next_attempt_at=datetime(2026, 8, 17, 12, 0))


@pytest.mark.parametrize("status", [TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED])
def test_terminal_statuses(status: TaskStatus) -> None:
    assert status.is_terminal is True
    assert status.is_due_eligible is False


@pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.RETRYING])
def test_due_eligible_statuses(status: TaskStatus) -> None:
    assert status.is_terminal is False
    assert status.is_due_eligible is True


def test_running_is_neither_terminal_nor_due_eligible() -> None:
    assert TaskStatus.RUNNING.is_terminal is False
    assert TaskStatus.RUNNING.is_due_eligible is False


def test_is_due_at_respects_next_attempt_at() -> None:
    from datetime import timedelta

    task = _task(next_attempt_at=NOW + timedelta(minutes=5))
    assert task.is_due_at(NOW) is False
    assert task.is_due_at(NOW + timedelta(minutes=5)) is True


def test_terminal_task_is_never_due() -> None:
    task = _task(status=TaskStatus.SUCCEEDED)
    assert task.is_due_at(NOW) is False
