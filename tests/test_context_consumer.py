import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.consumer import CONTEXT_EVENT_TYPES, ContextEventConsumer
from jarvis.context.engine import ContextEngine
from jarvis.context.errors import InvalidContextError
from jarvis.errors import DomainError
from jarvis.events.event import JsonValue
from jarvis.events.ports import EventConsumer
from tests.context_doubles import SpyRepository, frozen_clock
from tests.factories import make_event, make_recorded_event

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


def build() -> tuple[ContextEventConsumer, ContextAggregator]:
    aggregator = ContextAggregator(clock=frozen_clock(NOON + timedelta(days=1)))
    return ContextEventConsumer(aggregator), aggregator


def deliver(
    consumer: ContextEventConsumer,
    event_type: str,
    payload: Mapping[str, JsonValue] | None = None,
    *,
    occurred_at: datetime = NOON,
    schema_version: int = 1,
    event_id: str = "e-1",
) -> None:
    consumer.handle(
        make_recorded_event(
            make_event(
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                payload={} if payload is None else payload,
                schema_version=schema_version,
            ),
            recorded_at=NOON,
        )
    )


def test_the_subscribed_types_are_exactly_what_can_be_translated() -> None:
    translated = {
        "user.availability_changed",
        "user.activity_started",
        "user.activity_ended",
        # A Fase 6 trouxe a fonte de conversa que o campo esperava desde a Fase 2.
        "voice.session_started",
        "voice.session_ended",
    }

    assert set(CONTEXT_EVENT_TYPES) == translated


def test_it_satisfies_the_event_consumer_port_structurally() -> None:
    consumer, _ = build()

    accepted: EventConsumer = consumer

    assert accepted.name == "context"


class TestTranslation:
    def test_availability_changed(self) -> None:
        consumer, aggregator = build()

        deliver(consumer, "user.availability_changed", {"availability": "busy"})

        availability = aggregator.get_current_context().user.availability
        assert availability is not None
        assert availability.value == "busy"
        assert availability.source == "event:user.availability_changed"
        assert availability.confidence == 1.0

    def test_activity_started(self) -> None:
        consumer, aggregator = build()

        deliver(consumer, "user.activity_started", {"activity": "working"})

        current = aggregator.get_current_context().activity.current
        assert current is not None
        assert current.value == "working"

    def test_activity_ended_records_an_observed_absence(self) -> None:
        consumer, aggregator = build()
        deliver(consumer, "user.activity_started", {"activity": "working"})

        deliver(consumer, "user.activity_ended", occurred_at=LATER, event_id="e-2")

        current = aggregator.get_current_context().activity.current
        assert current is not None
        # Fato positivo com proveniência, não apagamento do campo.
        assert current.value is None
        assert current.source == "event:user.activity_ended"

    def test_a_voice_session_fills_the_conversation_field(self) -> None:
        consumer, aggregator = build()

        # Session IDs reais são UUID4 (36 caracteres)
        session_id = "2a9bc41d-b834-4e85-b5ec-26732dc212be"
        deliver(consumer, "voice.session_started", {"session_id": session_id})

        active = aggregator.get_current_context().conversation.active_id
        assert active is not None
        assert active.value == session_id
        assert active.source == "event:voice.session_started"

    def test_ending_a_session_records_an_observed_absence(self) -> None:
        consumer, aggregator = build()
        deliver(consumer, "voice.session_started", {"session_id": "s-1"})

        deliver(
            consumer,
            "voice.session_ended",
            {"session_id": "s-1"},
            occurred_at=LATER,
            event_id="e-2",
        )

        active = aggregator.get_current_context().conversation.active_id
        assert active is not None
        # "a conversa acabou" não é a mesma coisa que "nunca houve conversa".
        assert active.value is None

    def test_a_session_event_without_an_id_is_refused(self) -> None:
        consumer, _ = build()

        with pytest.raises(InvalidContextError):
            deliver(consumer, "voice.session_started", {})

    def test_observed_at_comes_from_occurred_at_not_recorded_at(self) -> None:
        consumer, aggregator = build()

        consumer.handle(
            make_recorded_event(
                make_event(
                    event_type="user.activity_started",
                    occurred_at=NOON,
                    payload={"activity": "working"},
                ),
                recorded_at=LATER,
            )
        )

        current = aggregator.get_current_context().activity.current
        assert current is not None
        assert current.observed_at == NOON


class TestFiltering:
    def test_an_unsubscribed_type_is_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        consumer, aggregator = build()

        with caplog.at_level(logging.DEBUG, logger="jarvis.context.consumer"):
            deliver(consumer, "email.received", {"subject": "reunião"})

        context = aggregator.get_current_context()
        assert all(item is None for item in (context.user.availability, context.activity.current))
        record = next(item for item in caplog.records if item.message == "context.event_ignored")
        assert record.reason == "unsubscribed_type"  # type: ignore[attr-defined]

    def test_an_unknown_schema_version_is_ignored_explicitly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        consumer, aggregator = build()

        with caplog.at_level(logging.INFO, logger="jarvis.context.consumer"):
            deliver(
                consumer, "user.availability_changed", {"availability": "busy"}, schema_version=2
            )

        assert aggregator.get_current_context().user.availability is None
        record = next(item for item in caplog.records if item.message == "context.event_ignored")
        assert record.reason == "unsupported_schema_version"  # type: ignore[attr-defined]


class TestInvalidPayload:
    @pytest.mark.parametrize(
        ("event_type", "payload"),
        [
            ("user.availability_changed", {}),
            ("user.availability_changed", {"availability": 7}),
            ("user.availability_changed", {"availability": "Muito Ocupado"}),
            ("user.activity_started", {}),
            ("user.activity_started", {"activity": ""}),
        ],
    )
    def test_a_malformed_payload_is_a_permanent_domain_error(
        self, event_type: str, payload: Mapping[str, JsonValue]
    ) -> None:
        consumer, _ = build()

        with pytest.raises(InvalidContextError) as exc_info:
            deliver(consumer, event_type, payload)

        # DomainError permanente: o bus manda para dead-letter sem retry, porque
        # repetir produziria exatamente o mesmo erro.
        assert isinstance(exc_info.value, DomainError)
        assert exc_info.value.retryable is False

    def test_a_failure_leaves_the_projection_untouched(self) -> None:
        consumer, aggregator = build()
        deliver(consumer, "user.availability_changed", {"availability": "busy"})

        with pytest.raises(InvalidContextError):
            deliver(
                consumer,
                "user.availability_changed",
                {"availability": "OCUPADO"},
                occurred_at=LATER,
                event_id="e-2",
            )

        availability = aggregator.get_current_context().user.availability
        assert availability is not None
        assert availability.value == "busy"


class TestIdempotence:
    def test_handling_the_same_event_five_times_changes_nothing(self) -> None:
        consumer, aggregator = build()
        recorded = make_recorded_event(
            make_event(
                event_type="user.availability_changed",
                occurred_at=NOON,
                payload={"availability": "busy"},
            ),
            recorded_at=NOON,
        )

        consumer.handle(recorded)
        once = aggregator.get_current_context()
        for _ in range(4):
            consumer.handle(recorded)

        assert aggregator.get_current_context() == once

    def test_a_repeat_reports_no_conflict(self, caplog: pytest.LogCaptureFixture) -> None:
        consumer, _ = build()
        recorded = make_recorded_event(
            make_event(
                event_type="user.activity_started",
                occurred_at=NOON,
                payload={"activity": "working"},
            ),
            recorded_at=NOON,
        )
        consumer.handle(recorded)

        with caplog.at_level(logging.INFO, logger="jarvis.context.projection"):
            consumer.handle(recorded)

        assert "context.conflict" not in caplog.text


def test_handle_never_touches_a_repository() -> None:
    """`handle` roda no dispatch síncrono do bus: I/O ali prenderia quem publicou."""
    aggregator = ContextAggregator(clock=frozen_clock(NOON))
    spy = SpyRepository()
    engine = ContextEngine(aggregator=aggregator, snapshots=spy)

    for _ in range(3):
        engine.consumer.handle(
            make_recorded_event(
                make_event(
                    event_type="user.availability_changed",
                    occurred_at=NOON,
                    payload={"availability": "busy"},
                ),
                recorded_at=NOON,
            )
        )

    assert spy.calls == []
