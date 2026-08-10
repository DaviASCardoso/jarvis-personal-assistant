"""Context Engine: projeção consultável do estado atual.

API pública do componente. As implementações concretas ficam em
`jarvis.context.adapters` e são escolhidas pelo composition root, não importadas
por quem apenas usa o Core.

Documentação: [`docs/context-system.md`](../../../docs/context-system.md).
"""

from jarvis.context.errors import (
    ContextProviderError,
    ContextSnapshotError,
    ContextSnapshotReadError,
    ContextSnapshotWriteError,
    InvalidContextError,
)
from jarvis.context.freshness import DEFAULT_TTL_POLICY, TtlPolicy
from jarvis.context.model import (
    ActivityContext,
    ContextField,
    ContextUpdate,
    ConversationContext,
    CurrentContext,
    DeviceContext,
    EnvironmentContext,
    ScheduleContext,
    TaskContext,
    UserContext,
    iter_fields,
)
from jarvis.context.observation import (
    Freshness,
    Observation,
    require_aware,
    require_identifier,
    require_label,
)
from jarvis.context.ports import ContextProvider

__all__ = [
    "DEFAULT_TTL_POLICY",
    "ActivityContext",
    "ContextField",
    "ContextProvider",
    "ContextProviderError",
    "ContextSnapshotError",
    "ContextSnapshotReadError",
    "ContextSnapshotWriteError",
    "ContextUpdate",
    "ConversationContext",
    "CurrentContext",
    "DeviceContext",
    "EnvironmentContext",
    "Freshness",
    "InvalidContextError",
    "Observation",
    "ScheduleContext",
    "TaskContext",
    "TtlPolicy",
    "UserContext",
    "iter_fields",
    "require_aware",
    "require_identifier",
    "require_label",
]
