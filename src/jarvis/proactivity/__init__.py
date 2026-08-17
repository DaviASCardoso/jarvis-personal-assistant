"""Proatividade: decide **se** e **quando** um evento merece raciocínio ou
automação — nunca **o que** fazer, e nunca executa nada sozinho.

API pública do componente. Não depende de `jarvis.agent`: os pontos de entrada
recebem callbacks injetados pelo composition root em vez de conhecerem o Agent
Runtime diretamente (`docs/phase-7-plan.md §1.1`).
"""

from jarvis.proactivity.errors import (
    InvalidConditionError,
    InvalidTriggerRuleError,
    ProactivityError,
)
from jarvis.proactivity.interruption import (
    DEFAULT_INTERRUPTION_SETTINGS,
    InterruptionDecision,
    InterruptionPolicy,
    InterruptionSettings,
    RecentNotification,
)
from jarvis.proactivity.triggers import TriggerEngine, TriggerEventConsumer, TriggerRule

__all__ = [
    "DEFAULT_INTERRUPTION_SETTINGS",
    "InterruptionDecision",
    "InterruptionPolicy",
    "InterruptionSettings",
    "InvalidConditionError",
    "InvalidTriggerRuleError",
    "ProactivityError",
    "RecentNotification",
    "TriggerEngine",
    "TriggerEventConsumer",
    "TriggerRule",
]
