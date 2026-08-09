"""Event System: registro, distribuição e consulta de fatos imutáveis.

API pública do componente. As implementações concretas ficam em
`jarvis.events.adapters` e são escolhidas pelo composition root, não importadas
por quem apenas usa o Core.

Documentação: [`docs/event-system.md`](../../../docs/event-system.md).
"""

from jarvis.events.bus import DeadLetter, DeadLetterHandler, EventBus, RetryPolicy
from jarvis.events.errors import (
    EventAppendError,
    EventReadError,
    EventStoreError,
    InvalidEventError,
)
from jarvis.events.event import (
    Event,
    JsonValue,
    RecordedEvent,
    deterministic_event_id,
    new_event_id,
)
from jarvis.events.ports import AppendResult, EventConsumer, EventStore
from jarvis.events.publisher import EventPublisher

__all__ = [
    "AppendResult",
    "DeadLetter",
    "DeadLetterHandler",
    "Event",
    "EventAppendError",
    "EventBus",
    "EventConsumer",
    "EventPublisher",
    "EventReadError",
    "EventStore",
    "EventStoreError",
    "InvalidEventError",
    "JsonValue",
    "RecordedEvent",
    "RetryPolicy",
    "deterministic_event_id",
    "new_event_id",
]
