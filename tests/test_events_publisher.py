from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from jarvis.events.bus import EventBus
from jarvis.events.errors import EventAppendError
from jarvis.events.event import Event, RecordedEvent
from jarvis.events.ports import AppendResult, EventStore
from jarvis.events.publisher import EventPublisher
from tests.factories import make_event

RECORDED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


class SpyStore:
    """Store fake que registra a ordem das chamadas, para verificar store→bus."""

    def __init__(self, *, calls: list[str], duplicate: bool = False) -> None:
        self.calls = calls
        self.duplicate = duplicate
        self.appended: list[Event] = []

    def append(self, event: Event) -> AppendResult:
        self.calls.append("store.append")
        self.appended.append(event)
        return AppendResult(
            event=RecordedEvent(event=event, recorded_at=RECORDED_AT),
            is_duplicate=self.duplicate,
        )

    def get(self, event_id: str) -> RecordedEvent | None:
        raise NotImplementedError

    def read_by_type(self, event_type: str, *, limit: int | None = None) -> Sequence[RecordedEvent]:
        raise NotImplementedError

    def read_by_correlation(self, correlation_id: str) -> Sequence[RecordedEvent]:
        raise NotImplementedError

    def read_occurred_between(
        self, start: datetime, end: datetime, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]:
        raise NotImplementedError

    def read_latest(self, *, limit: int) -> Sequence[RecordedEvent]:
        raise NotImplementedError


class ExplodingStore(SpyStore):
    def append(self, event: Event) -> AppendResult:
        self.calls.append("store.append")
        raise EventAppendError("disco cheio")


class SpyConsumer:
    def __init__(self, calls: list[str], *, name: str = "spy", fails: bool = False) -> None:
        self.name = name
        self._calls = calls
        self._fails = fails
        self.received: list[RecordedEvent] = []

    def handle(self, event: RecordedEvent) -> None:
        self._calls.append(f"{self.name}.handle")
        self.received.append(event)
        if self._fails:
            raise RuntimeError("consumer quebrou")


@pytest.fixture
def calls() -> list[str]:
    return []


def test_persists_before_distributing(calls: list[str]) -> None:
    store = SpyStore(calls=calls)
    bus = EventBus()
    bus.subscribe(SpyConsumer(calls))

    EventPublisher(store=store, bus=bus).publish(make_event())

    # Nenhum consumer vê um evento que ainda poderia falhar ao ser gravado.
    assert calls == ["store.append", "spy.handle"]


def test_returns_the_recorded_event(calls: list[str]) -> None:
    store = SpyStore(calls=calls)
    event = make_event()

    result = EventPublisher(store=store, bus=EventBus()).publish(event)

    assert result.is_duplicate is False
    assert result.event.event == event
    assert result.event.recorded_at == RECORDED_AT


def test_duplicates_are_not_republished(calls: list[str]) -> None:
    store = SpyStore(calls=calls, duplicate=True)
    bus = EventBus()
    consumer = SpyConsumer(calls)
    bus.subscribe(consumer)

    result = EventPublisher(store=store, bus=bus).publish(make_event())

    assert result.is_duplicate is True
    assert consumer.received == []
    assert calls == ["store.append"]


def test_persistence_failure_propagates_and_nothing_is_published(calls: list[str]) -> None:
    store = ExplodingStore(calls=calls)
    bus = EventBus()
    consumer = SpyConsumer(calls)
    bus.subscribe(consumer)

    with pytest.raises(EventAppendError, match="disco cheio"):
        EventPublisher(store=store, bus=bus).publish(make_event())

    assert consumer.received == []


def test_consumer_failure_does_not_fail_the_registration(calls: list[str]) -> None:
    store = SpyStore(calls=calls)
    bus = EventBus()
    bus.subscribe(SpyConsumer(calls, name="broken", fails=True))
    bus.subscribe(SpyConsumer(calls, name="healthy"))

    result = EventPublisher(store=store, bus=bus).publish(make_event())

    # O fato foi registrado; quem falhou em reagir a ele é problema do bus.
    assert result.is_duplicate is False
    assert calls == ["store.append", "broken.handle", "healthy.handle"]


def test_spy_store_satisfies_the_port(calls: list[str]) -> None:
    store: EventStore = SpyStore(calls=calls)

    assert store.append(make_event()).is_duplicate is False
