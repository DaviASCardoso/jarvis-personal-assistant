"""Construtores de eventos para os testes, com defaults válidos.

Evita repetir o envelope completo em cada teste quando só um campo importa.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from jarvis.events.event import Event, JsonValue, RecordedEvent, new_event_id

DEFAULT_OCCURRED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def make_event(
    *,
    event_id: str | None = None,
    event_type: str = "demo.happened",
    source: str = "test-suite",
    occurred_at: datetime = DEFAULT_OCCURRED_AT,
    payload: Mapping[str, JsonValue] | None = None,
    schema_version: int = 1,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> Event:
    return Event(
        event_id=event_id if event_id is not None else new_event_id(),
        event_type=event_type,
        source=source,
        occurred_at=occurred_at,
        payload={"value": 1} if payload is None else payload,
        schema_version=schema_version,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata={} if metadata is None else metadata,
    )


def make_recorded_event(
    event: Event | None = None, *, recorded_at: datetime = DEFAULT_OCCURRED_AT
) -> RecordedEvent:
    return RecordedEvent(
        event=event if event is not None else make_event(), recorded_at=recorded_at
    )
