"""Testes de `decision_event`/`read_decision` (Fase 7.4)."""

from datetime import UTC, datetime

import pytest

from jarvis.decisions.errors import InvalidDecisionRecordError
from jarvis.decisions.events import DECISION_RECORDED, decision_event, read_decision
from jarvis.events.event import Event, RecordedEvent

DECIDED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _event(**overrides: object) -> Event:
    kwargs: dict[str, object] = {
        "decision_id": "d1",
        "decision_type": "notify",
        "reason": "test_reason",
        "message": "Olá",
        "decided_at": DECIDED_AT,
        "correlation_id": "corr-1",
        "causation_id": "evt-1",
        "consulted_llm": True,
        "importance": 0.7,
        "used_memory_ids": ("m1", "m2"),
        "context_as_of": DECIDED_AT,
        "action_skill": None,
        "source": "jarvis-agent",
    }
    kwargs.update(overrides)
    return decision_event(**kwargs)  # type: ignore[arg-type]


def _recorded(event: Event) -> RecordedEvent:
    return RecordedEvent(event=event, recorded_at=DECIDED_AT)


def test_builds_event_with_expected_type_and_correlation() -> None:
    event = _event()
    assert event.event_type == DECISION_RECORDED
    assert event.correlation_id == "corr-1"
    assert event.causation_id == "evt-1"
    assert event.occurred_at == DECIDED_AT


def test_same_decision_id_produces_the_same_event_id() -> None:
    first = _event()
    second = _event()
    assert first.event_id == second.event_id


def test_different_decision_id_produces_a_different_event_id() -> None:
    first = _event(decision_id="d1")
    second = _event(decision_id="d2")
    assert first.event_id != second.event_id


def test_roundtrip_preserves_fields() -> None:
    record = read_decision(_recorded(_event()))
    assert record is not None
    assert record.decision_id == "d1"
    assert record.decision_type == "notify"
    assert record.reason == "test_reason"
    assert record.message == "Olá"
    assert record.decided_at == DECIDED_AT
    assert record.correlation_id == "corr-1"
    assert record.causation_id == "evt-1"
    assert record.consulted_llm is True
    assert record.importance == 0.7
    assert record.used_memory_ids == ("m1", "m2")
    assert record.context_as_of == DECIDED_AT
    assert record.action_skill is None


def test_roundtrip_with_action_skill() -> None:
    record = read_decision(_recorded(_event(action_skill="file.read", decision_type="act")))
    assert record is not None
    assert record.action_skill == "file.read"


def test_optional_fields_are_omitted_cleanly() -> None:
    event = _event(message=None, importance=None, context_as_of=None)
    record = read_decision(_recorded(event))
    assert record is not None
    assert record.message is None
    assert record.importance is None
    assert record.context_as_of is None


def test_ignores_events_of_a_different_type() -> None:
    other = Event(
        event_id="e1",
        event_type="demo.happened",
        source="test",
        occurred_at=DECIDED_AT,
        payload={},
    )
    assert read_decision(_recorded(other)) is None


def test_ignores_unsupported_schema_version() -> None:
    event = _event()
    bumped = Event(
        event_id=event.event_id,
        event_type=event.event_type,
        source=event.source,
        occurred_at=event.occurred_at,
        payload=event.payload,
        schema_version=99,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
    )
    assert read_decision(_recorded(bumped)) is None


def test_missing_required_field_raises() -> None:
    event = Event(
        event_id="e2",
        event_type=DECISION_RECORDED,
        source="test",
        occurred_at=DECIDED_AT,
        payload={"decision_id": "d1"},
    )
    with pytest.raises(InvalidDecisionRecordError):
        read_decision(_recorded(event))
