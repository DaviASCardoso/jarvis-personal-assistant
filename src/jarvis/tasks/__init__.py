"""Background Task Manager (Fase 7.5): execução adiada/repetível de uma
`ActionRequest`, sem thread nova.

API pública do componente. Aciona `ActionExecutor` (Fase 5) —
[ADR-0016](../../../docs/adr/0016-action-execution-orchestrator.md) já nomeia
esta subfase como um dos chamadores previstos.
"""

from jarvis.tasks.errors import (
    InvalidTaskTransitionError,
    TaskError,
    TaskReadError,
    TaskRepositoryError,
    TaskWriteError,
    UnknownTaskError,
)
from jarvis.tasks.identity import new_task_id
from jarvis.tasks.manager import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_BACKOFF,
    DEFAULT_RETRY_BASE_DELAY_SECONDS,
    TaskManager,
)
from jarvis.tasks.model import BackgroundTask, TaskStatus
from jarvis.tasks.ports import TaskRepository

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_RETRY_BASE_DELAY_SECONDS",
    "BackgroundTask",
    "InvalidTaskTransitionError",
    "TaskError",
    "TaskManager",
    "TaskReadError",
    "TaskRepository",
    "TaskRepositoryError",
    "TaskStatus",
    "TaskWriteError",
    "UnknownTaskError",
    "new_task_id",
]
