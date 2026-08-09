import logging

import pytest

from jarvis.events.adapters.logging_consumer import LoggingEventConsumer
from jarvis.events.bus import EventBus
from jarvis.events.ports import EventConsumer
from tests.factories import make_event, make_recorded_event

LOGGER_NAME = "jarvis.events.adapters.logging_consumer"


def test_satisfies_the_consumer_port() -> None:
    consumer: EventConsumer = LoggingEventConsumer()

    assert consumer.name == "logging"


def test_logs_event_metadata(caplog: pytest.LogCaptureFixture) -> None:
    consumer = LoggingEventConsumer()
    event = make_recorded_event(
        make_event(event_id="e-1", event_type="email.received", source="gmail-watcher")
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        consumer.handle(event)

    record = caplog.records[0]
    assert record.message == "event.observed"
    assert record.event_id == "e-1"  # type: ignore[attr-defined]
    assert record.event_type == "email.received"  # type: ignore[attr-defined]
    assert record.correlation_id == "e-1"  # type: ignore[attr-defined]


def test_never_logs_the_payload(caplog: pytest.LogCaptureFixture) -> None:
    consumer = LoggingEventConsumer()
    event = make_recorded_event(
        make_event(payload={"subject": "assunto sigiloso", "body": "conteúdo sensível"})
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        consumer.handle(event)

    logged = "".join(str(record.__dict__) for record in caplog.records)
    assert "assunto sigiloso" not in logged
    assert "conteúdo sensível" not in logged
    # As chaves ajudam o diagnóstico sem revelar o conteúdo.
    assert caplog.records[0].payload_keys == ["body", "subject"]  # type: ignore[attr-defined]


def test_custom_name_and_level(caplog: pytest.LogCaptureFixture) -> None:
    consumer = LoggingEventConsumer(name="audit-trail", level=logging.DEBUG)

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        consumer.handle(make_recorded_event())

    assert consumer.name == "audit-trail"
    assert caplog.records[0].levelno == logging.DEBUG
    assert caplog.records[0].consumer == "audit-trail"  # type: ignore[attr-defined]


def test_receives_events_through_the_bus(caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    bus.subscribe(LoggingEventConsumer())

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        bus.publish(make_recorded_event())

    assert [record.message for record in caplog.records] == ["event.observed"]
