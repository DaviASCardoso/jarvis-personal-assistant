"""Fluxo completo do Context Engine sobre SQLite em arquivo real (subfase 2.5).

Nenhum componente é substituído por double aqui: store, bus, publisher, consumer,
providers, engine e repositório são os de produção, e os dois bancos são arquivos
em disco.
"""

import itertools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.context.adapters.device_provider import LocalDeviceProvider
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.adapters.time_provider import SystemTimeProvider
from jarvis.context.aggregator import ContextAggregator
from jarvis.context.consumer import CONTEXT_EVENT_TYPES
from jarvis.context.engine import ContextEngine
from jarvis.context.observation import Freshness
from jarvis.events import Event, EventBus, EventPublisher, deterministic_event_id
from jarvis.events.adapters.logging_consumer import LoggingEventConsumer
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from tests.context_doubles import frozen_clock

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def event_database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "events.db"


@pytest.fixture
def context_database(tmp_path: Path) -> Path:
    return tmp_path / "data" / "context.db"


def ticking_clock(start: datetime) -> Callable[[], datetime]:
    """Relógio estritamente crescente para `recorded_at`.

    O store real usa `datetime.now(UTC)`, cuja resolução no Windows pode empatar
    entre duas publicações seguidas — e empate de `recorded_at` entre tipos
    diferentes é justamente a limitação registrada da reconstrução. Injetar o
    relógio mantém o teste determinístico sem fingir que a limitação não existe.
    """
    ticks = itertools.count()
    return lambda: start + timedelta(seconds=next(ticks))


@pytest.fixture
def store(event_database: Path) -> Iterator[SqliteEventStore]:
    with SqliteEventStore.open(event_database, clock=ticking_clock(NOON)) as opened:
        yield opened


@pytest.fixture
def snapshots(context_database: Path) -> Iterator[SqliteContextSnapshotRepository]:
    with SqliteContextSnapshotRepository.open(context_database) as opened:
        yield opened


def build_engine(
    snapshots: SqliteContextSnapshotRepository, *, moments: tuple[datetime, ...] = (NOON,)
) -> ContextEngine:
    aggregator = ContextAggregator(
        providers=[SystemTimeProvider(), LocalDeviceProvider(hostname=lambda: "notebook")],
        clock=frozen_clock(*moments),
    )
    return ContextEngine(aggregator=aggregator, snapshots=snapshots, clock=frozen_clock(*moments))


def activity_event(activity: str | None, *, occurred_at: datetime, key: str) -> Event:
    event_type = "user.activity_started" if activity else "user.activity_ended"
    return Event(
        event_id=deterministic_event_id(source="manual-cli", natural_key=key),
        event_type=event_type,
        source="manual-cli",
        occurred_at=occurred_at,
        payload={"activity": activity} if activity else {},
    )


def test_an_event_reaches_the_projection_and_a_snapshot(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository, context_database: Path
) -> None:
    engine = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(LoggingEventConsumer())
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    publisher = EventPublisher(store=store, bus=bus)

    # 1. Um fato é registrado e distribuído.
    publisher.publish(activity_event("working", occurred_at=NOON, key="a-1"))

    # 2. A projeção o incorporou, com a proveniência do evento.
    engine.refresh()
    context = engine.current()
    assert context.activity.current is not None
    assert context.activity.current.value == "working"
    assert context.activity.current.source == "event:user.activity_started"
    assert context.activity.current.observed_at == NOON

    # 3. Providers e eventos convivem no mesmo contexto.
    assert context.device.device_id is not None
    assert context.environment.utc_offset is not None

    # 4. A captura é persistida e recuperável depois de reabrir o banco.
    captured = engine.capture_snapshot()
    assert captured is not None

    with SqliteContextSnapshotRepository.open(context_database) as reopened:
        recovered = reopened.latest()

    assert recovered is not None
    assert recovered.snapshot_id == captured.snapshot_id
    recovered_activity = recovered.context.activity.current
    assert recovered_activity is not None
    assert recovered_activity.source == "event:user.activity_started"
    assert recovered_activity.freshness(recovered.captured_at) is Freshness.FRESH


def test_rebuilding_from_the_store_matches_the_incremental_projection(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    """Consistência: a projeção é derivada, e a ordem de persistência é respeitada."""
    incremental = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(incremental.consumer, event_types=CONTEXT_EVENT_TYPES)
    publisher = EventPublisher(store=store, bus=bus)

    publisher.publish(activity_event("working", occurred_at=NOON, key="a-1"))
    publisher.publish(activity_event("meeting", occurred_at=NOON, key="a-2"))
    # Mesmo `occurred_at` dos anteriores e tipo diferente: só a ordem de
    # persistência decide o desfecho, e a reconstrução tem de respeitá-la.
    publisher.publish(activity_event(None, occurred_at=NOON, key="a-3"))
    publisher.publish(
        Event(
            event_id="availability-1",
            event_type="user.availability_changed",
            source="manual-cli",
            occurred_at=NOON + timedelta(minutes=5),
            payload={"availability": "busy"},
        )
    )

    rebuilt = build_engine(snapshots)
    rebuilt.rebuild_from(store)

    assert rebuilt.current() == incremental.current()
    availability = rebuilt.current().user.availability
    assert availability is not None
    assert availability.value == "busy"

    # Discriminador da ordenação: os três fatos de atividade empatam em
    # `observed_at`, e empate mantém o incumbente — logo vence o **primeiro
    # registrado**. Se a reconstrução aplicasse na ordem alfabética dos tipos,
    # `user.activity_ended` chegaria primeiro e o valor seria `None`.
    activity = rebuilt.current().activity.current
    assert activity is not None
    assert activity.value == "working"


def test_a_later_fact_replaces_an_earlier_one(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    engine = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    publisher = EventPublisher(store=store, bus=bus)

    publisher.publish(activity_event("working", occurred_at=NOON, key="a-1"))
    publisher.publish(activity_event(None, occurred_at=NOON + timedelta(minutes=30), key="a-2"))

    rebuilt = build_engine(snapshots)
    rebuilt.rebuild_from(store)

    for projection in (engine.current(), rebuilt.current()):
        activity = projection.activity.current
        assert activity is not None
        # Ausência observada, com proveniência — não apagamento do campo.
        assert activity.value is None
        assert activity.source == "event:user.activity_ended"


def test_a_fresh_process_recovers_context_from_the_event_store(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository, event_database: Path
) -> None:
    bus = EventBus()
    EventPublisher(store=store, bus=bus).publish(
        activity_event("working", occurred_at=NOON, key="a-1")
    )
    store.close()

    with SqliteEventStore.open(event_database, clock=ticking_clock(NOON)) as reopened:
        engine = build_engine(snapshots)
        engine.rebuild_from(reopened)

    current = engine.current().activity.current
    assert current is not None
    assert current.value == "working"


def test_reobserving_the_same_fact_does_not_change_the_projection(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    engine = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    publisher = EventPublisher(store=store, bus=bus)

    first = publisher.publish(activity_event("working", occurred_at=NOON, key="a-1"))
    before = engine.current()
    second = publisher.publish(activity_event("working", occurred_at=NOON, key="a-1"))

    assert (first.is_duplicate, second.is_duplicate) == (False, True)
    assert engine.current() == before
    # Idempotência também na entrega direta, não só via deduplicação do publisher.
    engine.consumer.handle(second.event)
    assert engine.current() == before


def test_a_second_capture_without_changes_is_not_persisted(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    engine = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    EventPublisher(store=store, bus=bus).publish(
        activity_event("working", occurred_at=NOON, key="a-1")
    )
    engine.refresh()

    first = engine.capture_snapshot()
    second = engine.capture_snapshot()

    assert first is not None
    assert second is None
    history = engine.history(NOON - timedelta(days=1), NOON + timedelta(days=1))
    assert [item.snapshot_id for item in history] == [first.snapshot_id]


def test_a_failing_context_consumer_does_not_undo_the_event(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    engine = build_engine(snapshots)
    logging_consumer = LoggingEventConsumer()
    bus = EventBus()
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    bus.subscribe(logging_consumer)

    result = EventPublisher(store=store, bus=bus).publish(
        Event(
            event_id="broken-1",
            event_type="user.activity_started",
            source="manual-cli",
            occurred_at=NOON,
            payload={"activity": "MUITO Ocupado"},
        )
    )

    # O fato foi registrado apesar de o consumer ter recusado o payload.
    assert result.is_duplicate is False
    assert store.get("broken-1") is not None
    assert engine.current().activity.current is None


def test_history_stays_readable_after_an_explicit_expiration(
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> None:
    engine = build_engine(snapshots)
    bus = EventBus()
    bus.subscribe(engine.consumer, event_types=CONTEXT_EVENT_TYPES)
    EventPublisher(store=store, bus=bus).publish(
        activity_event("working", occurred_at=NOON, key="a-1")
    )
    captured = engine.capture_snapshot()
    assert captured is not None

    expired = engine.expire_before(NOON + timedelta(days=1))

    window = (NOON - timedelta(days=1), NOON + timedelta(days=1))
    assert expired == 1
    assert engine.history(*window) == []
    assert [item.snapshot_id for item in engine.history(*window, include_expired=True)] == [
        captured.snapshot_id
    ]
