"""Camada de execução: o único caminho entre uma `Decision` e uma Skill executada.

API pública do componente. É o único pacote autorizado a conhecer
`jarvis.policy`, `jarvis.skills` e `jarvis.tools` ao mesmo tempo — e é justamente
por isso que ele existe separado
([ADR-0016](../../../docs/adr/0016-action-execution-orchestrator.md)).

`jarvis.agent` **não** importa nada daqui, e um teste arquitetural garante que
continue assim: o agente entrega a `Decision` e para
([ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md)).
"""

from jarvis.execution.consumer import ActionEventConsumer
from jarvis.execution.errors import (
    ActionReadError,
    ActionRepositoryError,
    ActionWriteError,
    ExecutionError,
    InvalidActionEventError,
    InvalidActionRequestError,
    UnknownExecutionError,
)
from jarvis.execution.events import (
    ACTION_EVENT_TYPES,
    ACTION_SOURCE,
    AUDIT_EVENT_TYPES,
    CONFIRMATION_DENIED,
    CONFIRMATION_EVENT_TYPES,
    CONFIRMATION_GRANTED,
    audit_event,
    confirmation_event,
)
from jarvis.execution.identity import deterministic_execution_id, new_execution_id
from jarvis.execution.model import (
    ActionRequest,
    Actor,
    ExecutionOutcome,
    ExecutionStatus,
    PendingAction,
)
from jarvis.execution.orchestrator import DEFAULT_CONFIRMATION_TTL_SECONDS, ActionExecutor
from jarvis.execution.ports import ActionRepository

__all__ = [
    "ACTION_EVENT_TYPES",
    "ACTION_SOURCE",
    "AUDIT_EVENT_TYPES",
    "CONFIRMATION_DENIED",
    "CONFIRMATION_EVENT_TYPES",
    "CONFIRMATION_GRANTED",
    "DEFAULT_CONFIRMATION_TTL_SECONDS",
    "ActionEventConsumer",
    "ActionExecutor",
    "ActionReadError",
    "ActionRepository",
    "ActionRepositoryError",
    "ActionRequest",
    "ActionWriteError",
    "Actor",
    "ExecutionError",
    "ExecutionOutcome",
    "ExecutionStatus",
    "InvalidActionEventError",
    "InvalidActionRequestError",
    "PendingAction",
    "UnknownExecutionError",
    "audit_event",
    "confirmation_event",
    "deterministic_execution_id",
    "new_execution_id",
]
