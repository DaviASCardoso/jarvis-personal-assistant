"""Testes de Conditional Triggers (Fase 7.6)."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.model import ActivityContext, CurrentContext, UserContext
from jarvis.execution.model import ActionRequest, Actor
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
from jarvis.proactivity.errors import InvalidConditionError
from tests.context_doubles import make_observation
from tests.factories import make_event, make_recorded_event

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _context(**kwargs: object) -> CurrentContext:
    return CurrentContext(as_of=NOW, **kwargs)  # type: ignore[arg-type]


def _event(**kwargs: object) -> object:
    return make_recorded_event(make_event(**kwargs))  # type: ignore[arg-type]


class FakeMemoryPresence:
    """Double de `jarvis.proactivity.ports.MemoryPresence` — um dict basta."""

    def __init__(self, content_by_subject: dict[str, str] | None = None) -> None:
        self._content_by_subject = content_by_subject or {}

    def content_for(self, subject: str) -> str | None:
        return self._content_by_subject.get(subject)


def test_context_equals_requires_a_valid_field() -> None:
    with pytest.raises(InvalidConditionError):
        context_equals("not_a_field", "x")


def test_payload_equals_requires_a_key() -> None:
    with pytest.raises(InvalidConditionError):
        Condition(op=ConditionOp.PAYLOAD_EQUALS, key="")


def test_and_requires_children() -> None:
    with pytest.raises(InvalidConditionError):
        Condition(op=ConditionOp.AND)


def test_not_requires_exactly_one_child() -> None:
    with pytest.raises(InvalidConditionError):
        Condition(op=ConditionOp.NOT, children=(always(), always()))


def test_always_matches() -> None:
    assert evaluate_condition(always(), event=_event(), context=_context()) is True  # type: ignore[arg-type]


def test_context_equals_matches_fresh_observation() -> None:
    context = _context(user=UserContext(availability=make_observation("free", observed_at=NOW)))
    condition = context_equals("availability", "free")
    assert evaluate_condition(condition, event=_event(), context=context) is True  # type: ignore[arg-type]


def test_context_equals_does_not_match_stale_observation() -> None:
    old = NOW - timedelta(hours=1)
    context = _context(
        user=UserContext(
            availability=make_observation("free", observed_at=old, ttl=timedelta(minutes=5))
        )
    )
    condition = context_equals("availability", "free")
    assert evaluate_condition(condition, event=_event(), context=context) is False  # type: ignore[arg-type]


def test_context_present_is_false_for_an_explicitly_absent_value() -> None:
    """`context_present` exige um valor **utilizável**, não só um registro.

    Uma fonte que afirma "não há atividade" (`ActivityContext.current=None`)
    não dá a uma regra nada para comparar — tratar isso como "presente"
    obrigaria toda regra a checar `None` de novo depois.
    """
    context = _context(activity=ActivityContext(current=make_observation(None, observed_at=NOW)))
    condition = context_present("activity")
    assert evaluate_condition(condition, event=_event(), context=context) is False  # type: ignore[arg-type]


def test_context_present_is_true_for_a_fresh_value() -> None:
    context = _context(user=UserContext(availability=make_observation("busy", observed_at=NOW)))
    condition = context_present("availability")
    assert evaluate_condition(condition, event=_event(), context=context) is True  # type: ignore[arg-type]


def test_payload_equals_matches_event_payload() -> None:
    condition = payload_equals("job_id", "42")
    event = _event(payload={"job_id": "42"})
    assert evaluate_condition(condition, event=event, context=_context()) is True  # type: ignore[arg-type]


def test_and_requires_all_children() -> None:
    condition = and_(always(), payload_equals("x", "y"))
    event = _event(payload={"x": "y"})
    assert evaluate_condition(condition, event=event, context=_context()) is True  # type: ignore[arg-type]
    assert evaluate_condition(condition, event=_event(), context=_context()) is False  # type: ignore[arg-type]


def test_or_requires_any_child() -> None:
    condition = or_(payload_equals("x", "y"), always())
    assert evaluate_condition(condition, event=_event(), context=_context()) is True  # type: ignore[arg-type]


def test_not_inverts() -> None:
    condition = not_(always())
    assert evaluate_condition(condition, event=_event(), context=_context()) is False  # type: ignore[arg-type]


def test_rule_requires_rule_id() -> None:
    with pytest.raises(InvalidConditionError):
        ConditionalRule(
            rule_id=" ",
            when=frozenset({"demo.happened"}),
            condition=always(),
            then=ActionTemplate(skill="test.skill"),
        )


def test_rule_requires_when() -> None:
    with pytest.raises(InvalidConditionError):
        ConditionalRule(
            rule_id="r1", when=frozenset(), condition=always(), then=ActionTemplate(skill="s")
        )


def test_engine_produces_action_request_when_rule_matches() -> None:
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"demo.happened"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill", parameters={"topic": "$event.job_id"}),
    )
    engine = ConditionEngine([rule])
    event = _event(payload={"job_id": "42"})

    request = engine.evaluate(event, context=_context())  # type: ignore[arg-type]

    assert request is not None
    assert request.skill == "test.skill"
    assert request.actor is Actor.SYSTEM
    assert dict(request.parameters) == {"topic": "42"}


def test_engine_returns_none_when_condition_does_not_match() -> None:
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"demo.happened"}),
        condition=payload_equals("job_id", "does-not-match"),
        then=ActionTemplate(skill="test.skill"),
    )
    engine = ConditionEngine([rule])
    event = _event(payload={"job_id": "42"})
    assert engine.evaluate(event, context=_context()) is None  # type: ignore[arg-type]


def test_engine_returns_none_when_event_type_does_not_match() -> None:
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"other.type"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill"),
    )
    engine = ConditionEngine([rule])
    assert engine.evaluate(_event(), context=_context()) is None  # type: ignore[arg-type]


def test_disabled_rule_never_matches() -> None:
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"demo.happened"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill"),
        enabled=False,
    )
    engine = ConditionEngine([rule])
    assert engine.evaluate(_event(), context=_context()) is None  # type: ignore[arg-type]


def test_consumer_calls_back_with_the_action_request() -> None:
    rule = ConditionalRule(
        rule_id="r1",
        when=frozenset({"demo.happened"}),
        condition=always(),
        then=ActionTemplate(skill="test.skill"),
    )
    engine = ConditionEngine([rule])
    calls: list[ActionRequest] = []
    consumer = ConditionalTriggerConsumer(
        engine, context_reader=lambda: _context(), on_action=calls.append
    )

    consumer.handle(_event())  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0].skill == "test.skill"


def test_consumer_does_not_call_back_without_a_match() -> None:
    engine = ConditionEngine([])
    calls: list[ActionRequest] = []
    consumer = ConditionalTriggerConsumer(
        engine, context_reader=lambda: _context(), on_action=calls.append
    )

    consumer.handle(_event())  # type: ignore[arg-type]

    assert calls == []


class TestMemoryAwareConditions:
    """Fase 9.3: `memory_present`/`memory_equals` — a condição nunca importa
    `jarvis.memory`; quem responde é o `MemoryPresence` injetado."""

    def test_memory_present_requires_a_subject(self) -> None:
        with pytest.raises(InvalidConditionError):
            Condition(op=ConditionOp.MEMORY_PRESENT, subject="")

    def test_memory_equals_requires_a_subject(self) -> None:
        with pytest.raises(InvalidConditionError):
            Condition(op=ConditionOp.MEMORY_EQUALS, subject="", value="x")

    def test_memory_present_never_matches_without_a_port_injected(self) -> None:
        """Sem port, a condição nunca inventa presença — nunca casa."""
        condition = memory_present("quiet_hours_preference")
        assert evaluate_condition(condition, event=_event(), context=_context()) is False  # type: ignore[arg-type]

    def test_memory_present_matches_when_the_subject_has_content(self) -> None:
        memory = FakeMemoryPresence({"quiet_hours_preference": "não notificar depois das 22h"})
        condition = memory_present("quiet_hours_preference")
        matched = evaluate_condition(
            condition,
            event=_event(),  # type: ignore[arg-type]
            context=_context(),
            memory=memory,
        )
        assert matched is True

    def test_memory_present_does_not_match_an_absent_subject(self) -> None:
        memory = FakeMemoryPresence()
        condition = memory_present("quiet_hours_preference")
        matched = evaluate_condition(
            condition,
            event=_event(),  # type: ignore[arg-type]
            context=_context(),
            memory=memory,
        )
        assert matched is False

    def test_memory_equals_matches_on_exact_content(self) -> None:
        memory = FakeMemoryPresence({"language_preference": "python"})
        condition = memory_equals("language_preference", "python")
        matched = evaluate_condition(
            condition,
            event=_event(),  # type: ignore[arg-type]
            context=_context(),
            memory=memory,
        )
        assert matched is True

    def test_memory_equals_does_not_match_different_content(self) -> None:
        memory = FakeMemoryPresence({"language_preference": "python"})
        condition = memory_equals("language_preference", "rust")
        matched = evaluate_condition(
            condition,
            event=_event(),  # type: ignore[arg-type]
            context=_context(),
            memory=memory,
        )
        assert matched is False

    def test_engine_evaluates_a_memory_present_rule(self) -> None:
        rule = ConditionalRule(
            rule_id="quiet_hours",
            when=frozenset({"notification.candidate"}),
            condition=memory_present("quiet_hours_preference"),
            then=ActionTemplate(skill="test.skill"),
        )
        engine = ConditionEngine([rule])
        memory = FakeMemoryPresence({"quiet_hours_preference": "não notificar depois das 22h"})
        event = _event(event_type="notification.candidate")

        request = engine.evaluate(event, context=_context(), memory=memory)  # type: ignore[arg-type]

        assert request is not None
        assert request.skill == "test.skill"

    def test_consumer_forwards_the_injected_memory_port(self) -> None:
        rule = ConditionalRule(
            rule_id="quiet_hours",
            when=frozenset({"notification.candidate"}),
            condition=memory_present("quiet_hours_preference"),
            then=ActionTemplate(skill="test.skill"),
        )
        engine = ConditionEngine([rule])
        memory = FakeMemoryPresence({"quiet_hours_preference": "não notificar depois das 22h"})
        calls: list[ActionRequest] = []
        consumer = ConditionalTriggerConsumer(
            engine, context_reader=lambda: _context(), on_action=calls.append, memory=memory
        )

        consumer.handle(_event(event_type="notification.candidate"))  # type: ignore[arg-type]

        assert len(calls) == 1
