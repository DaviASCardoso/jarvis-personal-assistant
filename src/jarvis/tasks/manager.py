"""`TaskManager`: enfileira uma `ActionRequest` para execução adiada/repetível.

Aciona `ActionExecutor` — não reimplementa a cadeia de autorização
([ADR-0016](../../../docs/adr/0016-action-execution-orchestrator.md), que já
nomeia esta subfase explicitamente). Nenhuma thread nova: `run_due` é
**ticado**, nunca agendado — mesmo padrão que `ActionExecutor.expire()` já usa
(chamado explicitamente por `jarvis action pending`, não por um timer). Ver
[ADR-0027](../../../docs/adr/0027-background-tasks-ticked-not-scheduled.md).
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from jarvis.execution.model import ActionRequest, ExecutionOutcome, ExecutionStatus
from jarvis.tasks.errors import InvalidTaskTransitionError, UnknownTaskError
from jarvis.tasks.identity import new_task_id
from jarvis.tasks.model import BackgroundTask, TaskStatus
from jarvis.tasks.ports import ActionSubmitter, TaskRepository

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS: Final = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS: Final = 30.0
DEFAULT_RETRY_BACKOFF: Final = 2.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TaskManager:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay_seconds
        self._retry_backoff = retry_backoff
        self._clock = clock

    def submit(
        self,
        request: ActionRequest,
        *,
        max_attempts: int | None = None,
        delay_seconds: float = 0.0,
    ) -> BackgroundTask:
        now = self._clock()
        task = BackgroundTask(
            task_id=new_task_id(),
            request=request,
            status=TaskStatus.PENDING,
            attempts=0,
            max_attempts=max_attempts if max_attempts is not None else self._max_attempts,
            next_attempt_at=now + timedelta(seconds=delay_seconds),
            created_at=now,
            updated_at=now,
        )
        self._repository.put(task)
        logger.info("task.submitted", extra={"task_id": task.task_id, "skill": request.skill})
        return task

    def cancel(self, task_id: str) -> BackgroundTask:
        task = self._repository.get(task_id)
        if task is None:
            raise UnknownTaskError(f"tarefa não registrada: {task_id}")
        if task.status.is_terminal:
            raise InvalidTaskTransitionError(
                f"tarefa {task_id} já está em {task.status.value}, terminal"
            )
        cancelled = self._repository.cancel(task_id, moment=self._clock())
        logger.info("task.cancelled", extra={"task_id": task_id})
        return cancelled

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._repository.get(task_id)

    def list_by_status(
        self, status: TaskStatus, *, limit: int | None = None
    ) -> Sequence[BackgroundTask]:
        return self._repository.list_by_status(status, limit=limit)

    def run_due(
        self, *, executor: ActionSubmitter, moment: datetime | None = None
    ) -> Sequence[BackgroundTask]:
        """Executa toda tarefa devida agora. Devolve as que mudaram de estado."""
        now = moment if moment is not None else self._clock()
        due = self._repository.due(moment=now)
        return tuple(self._run_one(task, executor=executor, now=now) for task in due)

    def _run_one(
        self, task: BackgroundTask, *, executor: ActionSubmitter, now: datetime
    ) -> BackgroundTask:
        self._repository.mark_running(task.task_id, moment=now)
        outcome = executor.submit(task.request)
        return self._settle(task, outcome, now=now)

    def _settle(
        self, task: BackgroundTask, outcome: ExecutionOutcome, *, now: datetime
    ) -> BackgroundTask:
        if outcome.status is ExecutionStatus.COMPLETED:
            logger.info("task.succeeded", extra={"task_id": task.task_id})
            return self._repository.mark_succeeded(task.task_id, moment=now)

        if outcome.status in (ExecutionStatus.DENIED, ExecutionStatus.REJECTED):
            # Negação de política não é transitória: repetir sem intervenção
            # humana produziria o mesmo veredito.
            logger.info(
                "task.failed_permanently",
                extra={"task_id": task.task_id, "reason": outcome.reason},
            )
            return self._repository.mark_failed(task.task_id, moment=now, error=outcome.reason)

        if outcome.status is ExecutionStatus.AWAITING_CONFIRMATION:
            # Uma tarefa em background não tem quem confirmar.
            logger.info("task.requires_confirmation", extra={"task_id": task.task_id})
            return self._repository.mark_failed(
                task.task_id, moment=now, error="awaiting_confirmation"
            )

        return self._retry_or_exhaust(task, outcome, now=now)

    def _retry_or_exhaust(
        self, task: BackgroundTask, outcome: ExecutionOutcome, *, now: datetime
    ) -> BackgroundTask:
        next_attempt = task.attempts + 1
        if next_attempt >= task.max_attempts:
            logger.warning(
                "task.exhausted", extra={"task_id": task.task_id, "attempts": next_attempt}
            )
            return self._repository.mark_failed(task.task_id, moment=now, error=outcome.reason)

        delay = self._retry_base_delay * (self._retry_backoff**task.attempts)
        logger.info(
            "task.retrying",
            extra={"task_id": task.task_id, "attempt": next_attempt, "delay_seconds": delay},
        )
        return self._repository.schedule_retry(
            task.task_id,
            moment=now,
            next_attempt_at=now + timedelta(seconds=delay),
            error=outcome.reason,
        )
