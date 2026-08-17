"""Doubles do Background Task Manager (Fase 7.5)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from jarvis.execution.model import ActionRequest, ExecutionOutcome, ExecutionStatus
from jarvis.tasks.errors import TaskWriteError, UnknownTaskError
from jarvis.tasks.model import BackgroundTask, TaskStatus

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def make_request(
    *,
    skill: str = "test.skill",
    correlation_id: str = "corr-1",
    decision_id: str | None = None,
) -> ActionRequest:
    return ActionRequest(skill=skill, correlation_id=correlation_id, decision_id=decision_id)


def make_outcome(
    *,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    execution_id: str = "exec-1",
    skill: str = "test.skill",
    correlation_id: str = "corr-1",
    reason: str = "",
) -> ExecutionOutcome:
    return ExecutionOutcome(
        execution_id=execution_id,
        status=status,
        skill=skill,
        correlation_id=correlation_id,
        reason=reason,
    )


class FakeExecutor:
    """Devolve os desfechos programados, um por chamada de `submit`."""

    def __init__(self, outcomes: Sequence[ExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.submitted: list[ActionRequest] = []

    def submit(self, request: ActionRequest) -> ExecutionOutcome:
        self.submitted.append(request)
        if not self._outcomes:
            raise AssertionError("o teste não programou desfecho suficiente")
        return self._outcomes.pop(0)


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self.rows: dict[str, BackgroundTask] = {}

    def put(self, task: BackgroundTask) -> None:
        if task.task_id in self.rows:
            raise TaskWriteError(f"tarefa já registrada: {task.task_id}")
        self.rows[task.task_id] = task

    def get(self, task_id: str) -> BackgroundTask | None:
        return self.rows.get(task_id)

    def list_by_status(
        self, status: TaskStatus, *, limit: int | None = None
    ) -> Sequence[BackgroundTask]:
        found = [row for row in self.rows.values() if row.status is status]
        found.sort(key=lambda row: row.created_at)
        return found if limit is None else found[:limit]

    def due(self, *, moment: datetime, limit: int | None = None) -> Sequence[BackgroundTask]:
        found = [row for row in self.rows.values() if row.is_due_at(moment)]
        found.sort(key=lambda row: row.next_attempt_at)
        return found if limit is None else found[:limit]

    def mark_running(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        return self._replace(task_id, status=TaskStatus.RUNNING, updated_at=moment)

    def mark_succeeded(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        return self._replace(task_id, status=TaskStatus.SUCCEEDED, updated_at=moment)

    def mark_failed(self, task_id: str, *, moment: datetime, error: str) -> BackgroundTask:
        return self._replace(task_id, status=TaskStatus.FAILED, updated_at=moment, last_error=error)

    def schedule_retry(
        self, task_id: str, *, moment: datetime, next_attempt_at: datetime, error: str
    ) -> BackgroundTask:
        current = self._get_or_raise(task_id)
        return self._replace(
            task_id,
            status=TaskStatus.RETRYING,
            attempts=current.attempts + 1,
            next_attempt_at=next_attempt_at,
            updated_at=moment,
            last_error=error,
        )

    def cancel(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        return self._replace(task_id, status=TaskStatus.CANCELLED, updated_at=moment)

    def _get_or_raise(self, task_id: str) -> BackgroundTask:
        current = self.rows.get(task_id)
        if current is None:
            raise UnknownTaskError(f"tarefa não registrada: {task_id}")
        return current

    def _replace(self, task_id: str, **changes: object) -> BackgroundTask:
        current = self._get_or_raise(task_id)
        fields = {
            "task_id": current.task_id,
            "request": current.request,
            "status": current.status,
            "attempts": current.attempts,
            "max_attempts": current.max_attempts,
            "next_attempt_at": current.next_attempt_at,
            "created_at": current.created_at,
            "updated_at": current.updated_at,
            "last_error": current.last_error,
        }
        fields.update(changes)
        updated = BackgroundTask(**fields)  # type: ignore[arg-type]
        self.rows[task_id] = updated
        return updated
