"""Fluxo completo do Event System sobre SQLite em arquivo real (subfase 1.5).

Nenhum componente é substituído por fake aqui: store, bus, consumer e publisher são
os de produção, e o banco é um arquivo em disco.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.events import (
    Event,
    EventBus,
    EventPublisher,
    EventStoreError,
    RecordedEvent,
    deterministic_event_id,
    new_event_id,
)
from jarvis.events.adapters.sqlite_store import SqliteEventStore


class CollectingConsumer:
    def __init__(self) -> None:
        self.name = "collecting"
        self.received: list[RecordedEvent] = []

    def handle(self, event: RecordedEvent) -> None:
        self.received.append(event)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "events.db"


@pytest.fixture
def consumer() -> CollectingConsumer:
    return CollectingConsumer()


@pytest.fixture
def store(database: Path) -> Iterator[SqliteEventStore]:
    with SqliteEventStore.open(database) as opened:
        yield opened


@pytest.fixture
def publisher(store: SqliteEventStore, consumer: CollectingConsumer) -> EventPublisher:
    bus = EventBus()
    bus.subscribe(consumer)
    return EventPublisher(store=store, bus=bus)


def _email_received(event_id: str) -> Event:
    return Event(
        event_id=event_id,
        event_type="email.received",
        source="gmail-watcher",
        occurred_at=datetime(2026, 8, 9, 14, 0, tzinfo=UTC),
        payload={"from": "chefe@empresa.com", "subject": "reunião"},
    )


def test_causal_chain_is_recorded_distributed_and_reconstructable(
    publisher: EventPublisher,
    consumer: CollectingConsumer,
    store: SqliteEventStore,
    database: Path,
) -> None:
    root = _email_received(new_event_id())
    root_result = publisher.publish(root)

    reply = Event(
        event_id=new_event_id(),
        event_type="email.sent",
        source="manual-cli",
        occurred_at=datetime(2026, 8, 9, 14, 30, tzinfo=UTC),
        payload={"to": "chefe@empresa.com"},
        correlation_id=root.correlation_id,
        causation_id=root.event_id,
    )
    reply_result = publisher.publish(reply)

    # 1. Ambos foram registrados, com recorded_at atribuído pelo store.
    assert (root_result.is_duplicate, reply_result.is_duplicate) == (False, False)
    assert root_result.event.recorded_at.tzinfo is UTC

    # 2. O consumer recebeu os dois, na ordem de publicação.
    assert [item.event.event_id for item in consumer.received] == [root.event_id, reply.event_id]

    # 3. A cadeia é recuperável depois de reabrir o banco.
    store.close()
    with SqliteEventStore.open(database) as reopened:
        chain = reopened.read_by_correlation(root.event_id)

    assert [item.event.event_id for item in chain] == [root.event_id, reply.event_id]

    # 4. A causalidade permite remontar pai → filho sem depender da posição no stream.
    by_id = {item.event.event_id: item.event for item in chain}
    assert by_id[reply.event_id].causation_id == root.event_id
    assert by_id[root.event_id].causation_id is None
    assert {item.event.correlation_id for item in chain} == {root.event_id}


def test_reobserving_the_same_fact_is_a_no_op_end_to_end(
    publisher: EventPublisher, consumer: CollectingConsumer, store: SqliteEventStore
) -> None:
    event_id = deterministic_event_id(source="gmail-watcher", natural_key="<msg-42@empresa.com>")

    first = publisher.publish(_email_received(event_id))
    second = publisher.publish(_email_received(event_id))

    assert first.is_duplicate is False
    assert second.is_duplicate is True
    # Nem o store nem o consumer processam o mesmo fato duas vezes.
    assert len(store.read_latest(limit=10)) == 1
    assert len(consumer.received) == 1
    assert second.event.recorded_at == first.event.recorded_at


def test_stored_content_survives_intact(publisher: EventPublisher, database: Path) -> None:
    event = Event(
        event_id="rich",
        event_type="calendar.meeting_starting",
        source="calendar-watcher",
        occurred_at=datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
        payload={"attendees": ["a@b.c", "d@e.f"], "minutes": 15, "recurring": False},
        schema_version=2,
        metadata={"poll": "manual"},
    )

    publisher.publish(event)

    with SqliteEventStore.open(database) as reopened:
        stored = reopened.get("rich")

    assert stored is not None
    assert stored.event == event


def test_query_paths_agree_on_the_same_events(
    publisher: EventPublisher, store: SqliteEventStore
) -> None:
    for index in range(3):
        publisher.publish(_email_received(f"e-{index}"))

    by_type = store.read_by_type("email.received")
    by_window = store.read_occurred_between(
        datetime(2026, 8, 9, 13, tzinfo=UTC), datetime(2026, 8, 9, 15, tzinfo=UTC)
    )
    latest = store.read_latest(limit=10)

    assert list(by_type) == list(by_window) == list(latest)


def test_infrastructure_failure_is_exposed(
    publisher: EventPublisher, store: SqliteEventStore
) -> None:
    store.close()

    with pytest.raises(EventStoreError):
        publisher.publish(_email_received("after-close"))
