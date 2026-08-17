"""Testes do Trigger Engine (Fase 7.1)."""

import pytest

from jarvis.proactivity.errors import InvalidTriggerRuleError
from jarvis.proactivity.triggers import TriggerEngine, TriggerEventConsumer, TriggerRule
from tests.factories import make_recorded_event


def test_rule_requires_trigger_id() -> None:
    with pytest.raises(InvalidTriggerRuleError):
        TriggerRule(trigger_id="  ", event_types=frozenset({"printer.job_completed"}))


def test_rule_requires_at_least_one_event_type() -> None:
    with pytest.raises(InvalidTriggerRuleError):
        TriggerRule(trigger_id="printer", event_types=frozenset())


def test_empty_engine_never_matches() -> None:
    engine = TriggerEngine()
    event = make_recorded_event()
    assert engine.match(event) is None


def test_engine_matches_registered_event_type() -> None:
    rule = TriggerRule(trigger_id="printer", event_types=frozenset({"demo.happened"}))
    engine = TriggerEngine([rule])
    event = make_recorded_event()

    assert engine.match(event) is rule


def test_engine_ignores_unregistered_event_type() -> None:
    rule = TriggerRule(trigger_id="printer", event_types=frozenset({"printer.job_completed"}))
    engine = TriggerEngine([rule])
    event = make_recorded_event()

    assert engine.match(event) is None


def test_disabled_rule_never_matches() -> None:
    rule = TriggerRule(
        trigger_id="printer", event_types=frozenset({"demo.happened"}), enabled=False
    )
    engine = TriggerEngine([rule])
    event = make_recorded_event()

    assert engine.match(event) is None


def test_first_matching_rule_wins() -> None:
    first = TriggerRule(trigger_id="first", event_types=frozenset({"demo.happened"}))
    second = TriggerRule(trigger_id="second", event_types=frozenset({"demo.happened"}))
    engine = TriggerEngine([first, second])
    event = make_recorded_event()

    assert engine.match(event) is first


def test_consumer_calls_back_on_match() -> None:
    rule = TriggerRule(trigger_id="printer", event_types=frozenset({"demo.happened"}))
    engine = TriggerEngine([rule])
    calls: list[tuple[str, str]] = []

    def on_match(event: object, matched: TriggerRule) -> None:
        calls.append((event.event.event_id, matched.trigger_id))  # type: ignore[attr-defined]

    consumer = TriggerEventConsumer(engine, on_match=on_match)
    event = make_recorded_event()
    consumer.handle(event)

    assert calls == [(event.event.event_id, "printer")]


def test_consumer_ignores_unmatched_event_without_calling_back() -> None:
    engine = TriggerEngine()
    calls: list[object] = []
    consumer = TriggerEventConsumer(engine, on_match=lambda event, rule: calls.append(event))

    consumer.handle(make_recorded_event())

    assert calls == []


def test_consumer_has_a_stable_name() -> None:
    consumer = TriggerEventConsumer(TriggerEngine(), on_match=lambda event, rule: None)
    assert consumer.name == "proactivity-triggers"
