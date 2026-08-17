"""Testes de `project_decisions` (Fase 7.4)."""

from datetime import UTC, datetime

from jarvis.decisions.events import decision_event
from jarvis.decisions.query import project_decisions
from jarvis.events.event import Event, RecordedEvent

AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _decision(decision_id: str, *, correlation_id: str = "corr-1") -> RecordedEvent:
    event = decision_event(
        decision_id=decision_id,
        decision_type="notify",
        reason="r",
        message=None,
        decided_at=AT,
        correlation_id=correlation_id,
        consulted_llm=False,
        source="jarvis-agent",
    )
    return RecordedEvent(event=event, recorded_at=AT)


def _other_event() -> RecordedEvent:
    event = Event(
        event_id="e-other",
        event_type="demo.happened",
        source="test",
        occurred_at=AT,
        payload={},
    )
    return RecordedEvent(event=event, recorded_at=AT)


def test_projects_only_decision_events_in_order() -> None:
    events = [_decision("d1"), _other_event(), _decision("d2")]
    records = project_decisions(events)
    assert [record.decision_id for record in records] == ["d1", "d2"]


def test_empty_input_produces_empty_output() -> None:
    assert project_decisions(()) == ()


def test_malformed_decision_event_is_skipped_not_raised() -> None:
    malformed = Event(
        event_id="e-bad",
        event_type="agent.decision_recorded",
        source="test",
        occurred_at=AT,
        payload={"decision_id": "d1"},
    )
    events = [RecordedEvent(event=malformed, recorded_at=AT), _decision("d2")]
    records = project_decisions(events)
    assert [record.decision_id for record in records] == ["d2"]
