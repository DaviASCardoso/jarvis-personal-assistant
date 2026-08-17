"""Erros do Goal Pursuit Loop (Fase 10.5)."""

from jarvis.errors import DomainError, InfrastructureError


class PursuitError(DomainError):
    """Raiz das falhas de domínio de checkpoints de perseguição de objetivo."""


class UnknownPursuitError(PursuitError):
    """Nenhum checkpoint registrado com esse `pursuit_id`."""


class PursuitRepositoryError(InfrastructureError):
    """Falha na persistência de checkpoints."""


class PursuitWriteError(PursuitRepositoryError):
    """Falha ao gravar ou atualizar um checkpoint."""


class PursuitReadError(PursuitRepositoryError):
    """Falha ao ler ou decodificar um checkpoint."""
