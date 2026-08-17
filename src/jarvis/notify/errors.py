"""Erros do Notification Manager (Fase 7.3)."""

from jarvis.errors import DomainError


class NotifyError(DomainError):
    """Raiz das falhas de domínio de notificação."""


class InvalidNotificationError(NotifyError):
    """Uma `Notification` viola uma invariante."""
