"""Erros do Background Task Manager (Fase 7.5)."""

from jarvis.errors import DomainError, InfrastructureError


class TaskError(DomainError):
    """Raiz das falhas de domínio de tarefas em background."""


class UnknownTaskError(TaskError):
    """Nenhuma tarefa registrada com esse `task_id`."""


class InvalidTaskTransitionError(TaskError):
    """Uma transição de estado não é permitida a partir do estado atual."""


class TaskRepositoryError(InfrastructureError):
    """Falha na persistência de tarefas."""


class TaskWriteError(TaskRepositoryError):
    """Falha ao gravar ou atualizar uma tarefa."""


class TaskReadError(TaskRepositoryError):
    """Falha ao ler ou decodificar uma tarefa."""
