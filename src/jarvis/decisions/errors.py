"""Erros do Decision Log (Fase 7.4)."""

from jarvis.errors import DomainError


class DecisionLogError(DomainError):
    """Raiz das falhas de domínio do log de decisões."""


class InvalidDecisionRecordError(DecisionLogError):
    """Um evento `agent.decision_recorded` não tem a forma esperada."""
