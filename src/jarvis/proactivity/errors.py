"""Erros do pacote de proatividade (Fase 7)."""

from jarvis.errors import DomainError


class ProactivityError(DomainError):
    """Raiz das falhas de domínio da proatividade."""


class InvalidTriggerRuleError(ProactivityError):
    """Uma `TriggerRule` viola uma invariante."""


class InvalidConditionError(ProactivityError):
    """Uma `Condition`/`ConditionalRule` é malformada."""
