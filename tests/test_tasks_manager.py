"""Testes de `TaskManager` (Fase 7.5)."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.execution.model import ExecutionStatus
from jarvis.tasks.errors import InvalidTaskTransitionError, UnknownTaskError
from jarvis.tasks.manager import TaskManager
from jarvis.tasks.model import TaskStatus
from tests.tasks_doubles import FakeExecutor, InMemoryTaskRepository, make_outcome, make_request

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _manager(**kwargs: object) -> TaskManager:
    return TaskManager(
        repository=InMemoryTaskRepository(),
        clock=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


def test_submit_creates_a_pending_task_due_immediately_by_default() -> None:
    manager = _manager()
    task = manager.submit(make_request())

    assert task.status is TaskStatus.PENDING
    assert task.attempts == 0
    assert task.next_attempt_at == NOW


def test_submit_with_delay_is_not_due_immediately() -> None:
    manager = _manager()
    task = manager.submit(make_request(), delay_seconds=60.0)
    assert task.next_attempt_at == NOW + timedelta(seconds=60)


def test_submit_does_not_execute_anything() -> None:
    manager = _manager()
    manager.submit(make_request())
    assert manager.list_by_status(TaskStatus.PENDING)
    assert manager.list_by_status(TaskStatus.SUCCEEDED) == []


def test_run_due_executes_a_due_task_and_marks_it_succeeded() -> None:
    manager = _manager()
    task = manager.submit(make_request())
    executor = FakeExecutor([make_outcome(status=ExecutionStatus.COMPLETED)])

    settled = manager.run_due(executor=executor)

    assert len(settled) == 1
    assert settled[0].task_id == task.task_id
    assert settled[0].status is TaskStatus.SUCCEEDED
    assert len(executor.submitted) == 1


def test_run_due_skips_tasks_not_yet_due() -> None:
    manager = _manager()
    manager.submit(make_request(), delay_seconds=3600.0)
    executor = FakeExecutor([])

    settled = manager.run_due(executor=executor)

    assert settled == ()
    assert executor.submitted == []


def test_denied_outcome_fails_permanently_without_retry() -> None:
    manager = _manager()
    manager.submit(make_request())
    executor = FakeExecutor([make_outcome(status=ExecutionStatus.DENIED, reason="policy_denied")])

    settled = manager.run_due(executor=executor)

    assert settled[0].status is TaskStatus.FAILED
    assert settled[0].last_error == "policy_denied"


def test_awaiting_confirmation_fails_permanently() -> None:
    manager = _manager()
    manager.submit(make_request())
    executor = FakeExecutor([make_outcome(status=ExecutionStatus.AWAITING_CONFIRMATION)])

    settled = manager.run_due(executor=executor)

    assert settled[0].status is TaskStatus.FAILED
    assert settled[0].last_error == "awaiting_confirmation"


def test_generic_failure_schedules_a_retry_with_backoff() -> None:
    manager = _manager(retry_base_delay_seconds=10.0, retry_backoff=2.0)
    manager.submit(make_request(), max_attempts=5)
    executor = FakeExecutor([make_outcome(status=ExecutionStatus.FAILED, reason="boom")])

    settled = manager.run_due(executor=executor)

    assert settled[0].status is TaskStatus.RETRYING
    assert settled[0].attempts == 1
    assert settled[0].next_attempt_at == NOW + timedelta(seconds=10.0)


def test_retries_exhaust_after_max_attempts() -> None:
    manager = _manager(retry_base_delay_seconds=1.0, retry_backoff=1.0)
    manager.submit(make_request(), max_attempts=2)
    executor = FakeExecutor(
        [
            make_outcome(status=ExecutionStatus.FAILED, reason="boom"),
            make_outcome(status=ExecutionStatus.FAILED, reason="boom-again"),
        ]
    )

    first = manager.run_due(executor=executor)
    assert first[0].status is TaskStatus.RETRYING

    second = manager.run_due(executor=executor, moment=first[0].next_attempt_at)
    assert second[0].status is TaskStatus.FAILED
    assert second[0].last_error == "boom-again"


def test_cancel_non_terminal_task_succeeds() -> None:
    manager = _manager()
    task = manager.submit(make_request())
    cancelled = manager.cancel(task.task_id)
    assert cancelled.status is TaskStatus.CANCELLED


def test_cancel_terminal_task_raises() -> None:
    manager = _manager()
    manager.submit(make_request())
    executor = FakeExecutor([make_outcome(status=ExecutionStatus.COMPLETED)])
    settled = manager.run_due(executor=executor)

    with pytest.raises(InvalidTaskTransitionError):
        manager.cancel(settled[0].task_id)


def test_cancel_unknown_task_raises() -> None:
    manager = _manager()
    with pytest.raises(UnknownTaskError):
        manager.cancel("does-not-exist")
