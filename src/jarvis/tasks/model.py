"""`BackgroundTask`: uma `ActionRequest` cuja execução foi adiada e pode se
repetir.

Não é o mesmo conceito que `PendingAction` (Fase 5): uma `PendingAction`
espera uma **pessoa** confirmar; um `BackgroundTask` espera **tempo** passar
(ou uma tentativa anterior falhar de forma transitória). Misturar os dois
complicaria as invariantes de ambos — ver `docs/phase-7-plan.md §7.5`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from jarvis.execution.model import ActionRequest
from jarvis.tasks.errors import TaskError


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    @property
    def is_due_eligible(self) -> bool:
        """Estados que `TaskManager.run_due` considera."""
        return self in (TaskStatus.PENDING, TaskStatus.RETRYING)


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise TaskError(f"{field_name} precisa ser timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class BackgroundTask:
    task_id: str
    request: ActionRequest
    status: TaskStatus
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime
    last_error: str = ""

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        if not self.task_id.strip():
            raise TaskError("task_id não pode ser vazio")
        if self.max_attempts < 1:
            raise TaskError(f"max_attempts precisa ser >= 1, recebido {self.max_attempts}")
        if self.attempts < 0:
            raise TaskError(f"attempts não pode ser negativo, recebido {self.attempts}")
        overwrite(
            self,
            "next_attempt_at",
            _require_aware(self.next_attempt_at, field_name="next_attempt_at"),
        )
        overwrite(self, "created_at", _require_aware(self.created_at, field_name="created_at"))
        overwrite(self, "updated_at", _require_aware(self.updated_at, field_name="updated_at"))

    def is_due_at(self, moment: datetime) -> bool:
        return self.status.is_due_eligible and moment >= self.next_attempt_at
