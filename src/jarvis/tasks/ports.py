"""Port de persistência de tarefas em background.

Sem `update` genérico, mesmo desenho de `ActionRepository`: cada método nomeia
exatamente a transição que autoriza. Os parâmetros da `ActionRequest`
embutida nunca mudam depois de gravados — só o estado da tarefa em torno dela.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from jarvis.execution.model import ActionRequest, ExecutionOutcome
from jarvis.tasks.model import BackgroundTask, TaskStatus


class ActionSubmitter(Protocol):
    """O único método de `ActionExecutor` que `TaskManager` usa.

    Um port próprio, mais estreito que a classe concreta — não porque
    `ActionExecutor` tenha um substituto real em produção (não tem: é o
    único caminho até uma Skill, ADR-0016), mas porque um teste de
    `TaskManager` não deveria precisar montar Policy Engine, Skill Registry
    e Tool Router só para verificar retry/backoff.
    """

    def submit(self, request: ActionRequest) -> ExecutionOutcome: ...


class TaskRepository(Protocol):
    def put(self, task: BackgroundTask) -> None:
        """Grava a tarefa. Reescrever um `task_id` existente é erro, não upsert."""
        ...

    def get(self, task_id: str) -> BackgroundTask | None: ...

    def list_by_status(
        self, status: TaskStatus, *, limit: int | None = None
    ) -> Sequence[BackgroundTask]: ...

    def due(self, *, moment: datetime, limit: int | None = None) -> Sequence[BackgroundTask]:
        """Tarefas `pending`/`retrying` com `next_attempt_at <= moment`."""
        ...

    def mark_running(self, task_id: str, *, moment: datetime) -> BackgroundTask: ...

    def mark_succeeded(self, task_id: str, *, moment: datetime) -> BackgroundTask: ...

    def mark_failed(self, task_id: str, *, moment: datetime, error: str) -> BackgroundTask:
        """Falha terminal: as tentativas se esgotaram, ou a política negou."""
        ...

    def schedule_retry(
        self, task_id: str, *, moment: datetime, next_attempt_at: datetime, error: str
    ) -> BackgroundTask:
        """Incrementa `attempts`, agenda a próxima tentativa, volta para `retrying`."""
        ...

    def cancel(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        """Só de tarefas não terminais."""
        ...
