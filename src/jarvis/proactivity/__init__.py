"""Proatividade: decide **se** e **quando** um evento merece raciocínio ou
automação — nunca **o que** fazer, e nunca executa nada sozinho.

API pública do componente. Não depende de `jarvis.agent`: os pontos de entrada
recebem callbacks injetados pelo composition root em vez de conhecerem o Agent
Runtime diretamente (`docs/phase-7-plan.md §1.1`).
"""

from jarvis.proactivity.conditions import (
    ActionTemplate,
    Condition,
    ConditionalRule,
    ConditionalTriggerConsumer,
    ConditionEngine,
    ConditionOp,
    always,
    and_,
    context_equals,
    context_present,
    evaluate_condition,
    memory_equals,
    memory_present,
    not_,
    or_,
    payload_equals,
)
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
from jarvis.proactivity.ports import MemoryPresence
from jarvis.proactivity.triggers import TriggerEngine, TriggerEventConsumer, TriggerRule

__all__ = [
    "DEFAULT_INTERRUPTION_SETTINGS",
    "ActionTemplate",
    "Condition",
    "ConditionEngine",
    "ConditionOp",
    "ConditionalRule",
    "ConditionalTriggerConsumer",
    "InterruptionDecision",
    "InterruptionPolicy",
    "InterruptionSettings",
    "InvalidConditionError",
    "InvalidTriggerRuleError",
    "MemoryPresence",
    "ProactivityError",
    "RecentNotification",
    "TriggerEngine",
    "TriggerEventConsumer",
    "TriggerRule",
    "always",
    "and_",
    "context_equals",
    "context_present",
    "evaluate_condition",
    "memory_equals",
    "memory_present",
    "not_",
    "or_",
    "payload_equals",
]
