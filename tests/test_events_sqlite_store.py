import logging
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE, SqliteEventStore
from jarvis.events.errors import EventAppendError, EventReadError, EventStoreError
from jarvis.events.event import Event, deterministic_event_id
from jarvis.events.ports import EventStore
from tests.factories import make_event


class FrozenClock:
    """Relógio controlável: torna `recorded_at` verificável sem depender do relógio real."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))


@pytest.fixture
def store(clock: FrozenClock) -> Iterator[SqliteEventStore]:
    with SqliteEventStore.open(IN_MEMORY_DATABASE, clock=clock) as opened:
        yield opened


class TestAppendAndGet:
    def test_stored_event_round_trips(self, store: SqliteEventStore) -> None:
        event = make_event(payload={"subject": "olá", "tags": ["a", "b"]})

        result = store.append(event)

        assert result.is_duplicate is False
        assert result.event.event == event
        assert store.get(event.event_id) == result.event

    def test_unknown_id_returns_none(self, store: SqliteEventStore) -> None:
        assert store.get("não existe") is None

    def test_recorded_at_is_assigned_by_the_store(
        self, store: SqliteEventStore, clock: FrozenClock
    ) -> None:
        clock.now = datetime(2026, 8, 9, 14, 30, tzinfo=UTC)

        # `occurred_at` fica no passado: o watcher só observou o fato depois.
        result = store.append(make_event(occurred_at=datetime(2026, 8, 9, 14, 0, tzinfo=UTC)))

        assert result.event.recorded_at == datetime(2026, 8, 9, 14, 30, tzinfo=UTC)
        assert result.event.event.occurred_at == datetime(2026, 8, 9, 14, 0, tzinfo=UTC)

    def test_recorded_at_may_precede_occurred_at(
        self, store: SqliteEventStore, clock: FrozenClock
    ) -> None:
        # Nada garante relógio monotônico global entre source e store (ADR-0004):
        # o store aceita e preserva os dois tempos como vieram.
        future = datetime(2026, 8, 9, 23, 0, tzinfo=UTC)

        result = store.append(make_event(occurred_at=future))

        assert result.event.event.occurred_at > result.event.recorded_at


class TestIdempotency:
    def test_reappending_the_same_id_is_a_no_op(
        self, store: SqliteEventStore, clock: FrozenClock
    ) -> None:
        event = make_event(event_id="repeated")
        first = store.append(event)
        clock.advance(60)

        second = store.append(event)

        assert second.is_duplicate is True
        assert second.event.recorded_at == first.event.recorded_at
        assert len(store.read_latest(limit=10)) == 1

    def test_divergent_duplicate_keeps_the_original_and_warns(
        self, store: SqliteEventStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        original = make_event(event_id="repeated", payload={"amount": 1})
        store.append(original)
        divergent = make_event(event_id="repeated", payload={"amount": 999})

        with caplog.at_level(logging.WARNING, logger="jarvis.events.adapters.sqlite_store"):
            result = store.append(divergent)

        assert result.is_duplicate is True
        assert result.event.event.payload == {"amount": 1}
        assert "event.duplicate_divergent" in [record.message for record in caplog.records]

    def test_divergence_warning_never_contains_the_payload(
        self, store: SqliteEventStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        store.append(make_event(event_id="repeated", payload={"secret": "hunter2"}))

        with caplog.at_level(logging.WARNING, logger="jarvis.events.adapters.sqlite_store"):
            store.append(make_event(event_id="repeated", payload={"secret": "outro-valor"}))

        logged = "".join(str(record.__dict__) for record in caplog.records)
        assert "hunter2" not in logged
        assert "outro-valor" not in logged

    def test_identical_duplicate_does_not_warn(
        self, store: SqliteEventStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        event = make_event(event_id="repeated")
        store.append(event)

        with caplog.at_level(logging.WARNING, logger="jarvis.events.adapters.sqlite_store"):
            store.append(event)

        assert caplog.records == []

    def test_deterministic_ids_deduplicate_re_observation(self, store: SqliteEventStore) -> None:
        event_id = deterministic_event_id(source="gmail-watcher", natural_key="msg-42")

        store.append(make_event(event_id=event_id, source="gmail-watcher"))
        second = store.append(make_event(event_id=event_id, source="gmail-watcher"))

        assert second.is_duplicate is True


class TestImmutability:
    """A imutabilidade do ADR-0004 vale na persistência, não só no domínio.

    Os testes atacam o banco por fora do adapter, de propósito: o que se verifica é
    que o schema recusa a mutação, não que o adapter evita emiti-la.
    """

    @pytest.fixture
    def database(self, tmp_path: Path) -> Path:
        path = tmp_path / "events.db"
        with SqliteEventStore.open(path) as store:
            store.append(make_event(event_id="frozen"))
        return path

    def test_updates_are_blocked_by_the_database(self, database: Path) -> None:
        with (
            sqlite3.connect(database) as raw,
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
        ):
            raw.execute("UPDATE events SET event_type = 'x' WHERE event_id = ?", ("frozen",))

    def test_deletes_are_blocked_by_the_database(self, database: Path) -> None:
        with (
            sqlite3.connect(database) as raw,
            pytest.raises(sqlite3.IntegrityError, match="immutable"),
        ):
            raw.execute("DELETE FROM events WHERE event_id = ?", ("frozen",))


class TestQueries:
    @pytest.fixture
    def populated(self, store: SqliteEventStore, clock: FrozenClock) -> SqliteEventStore:
        # Inserção fora de ordem temporal, de propósito: a ordem de leitura é a de
        # persistência, não a de `occurred_at`.
        for index, (event_type, hour, correlation) in enumerate(
            [
                ("email.received", 15, "chain-a"),
                ("calendar.meeting_starting", 9, "chain-b"),
                ("email.received", 12, "chain-a"),
            ]
        ):
            clock.advance(1)
            store.append(
                make_event(
                    event_id=f"e-{index}",
                    event_type=event_type,
                    occurred_at=datetime(2026, 8, 9, hour, tzinfo=UTC),
                    correlation_id=correlation,
                )
            )
        return store

    def test_reads_follow_persistence_order(self, populated: SqliteEventStore) -> None:
        assert [item.event.event_id for item in populated.read_latest(limit=10)] == [
            "e-0",
            "e-1",
            "e-2",
        ]

    def test_read_by_type(self, populated: SqliteEventStore) -> None:
        found = populated.read_by_type("email.received")

        assert [item.event.event_id for item in found] == ["e-0", "e-2"]

    def test_read_by_type_honours_limit(self, populated: SqliteEventStore) -> None:
        assert len(populated.read_by_type("email.received", limit=1)) == 1

    def test_read_by_type_without_matches(self, populated: SqliteEventStore) -> None:
        assert populated.read_by_type("nada.aconteceu") == []

    def test_read_by_correlation_returns_the_whole_chain(self, populated: SqliteEventStore) -> None:
        found = populated.read_by_correlation("chain-a")

        assert [item.event.event_id for item in found] == ["e-0", "e-2"]

    def test_temporal_query_filters_occurred_at(self, populated: SqliteEventStore) -> None:
        found = populated.read_occurred_between(
            datetime(2026, 8, 9, 10, tzinfo=UTC), datetime(2026, 8, 9, 16, tzinfo=UTC)
        )

        assert [item.event.event_id for item in found] == ["e-0", "e-2"]

    def test_temporal_query_is_half_open(self, populated: SqliteEventStore) -> None:
        found = populated.read_occurred_between(
            datetime(2026, 8, 9, 12, tzinfo=UTC), datetime(2026, 8, 9, 15, tzinfo=UTC)
        )

        assert [item.event.event_id for item in found] == ["e-2"]

    def test_temporal_query_honours_limit(self, populated: SqliteEventStore) -> None:
        found = populated.read_occurred_between(
            datetime(2026, 8, 9, 0, tzinfo=UTC), datetime(2026, 8, 10, 0, tzinfo=UTC), limit=2
        )

        assert len(found) == 2

    def test_read_latest_returns_the_tail_in_order(self, populated: SqliteEventStore) -> None:
        assert [item.event.event_id for item in populated.read_latest(limit=2)] == ["e-1", "e-2"]


class TestPersistence:
    def test_events_survive_reopening(self, tmp_path: Path) -> None:
        database = tmp_path / "nested" / "events.db"
        event = make_event(event_id="durable", payload={"n": 1})

        with SqliteEventStore.open(database) as store:
            store.append(event)

        with SqliteEventStore.open(database) as reopened:
            stored = reopened.get("durable")

        assert stored is not None
        assert stored.event == event

    def test_schema_creation_is_idempotent(self, tmp_path: Path) -> None:
        database = tmp_path / "events.db"

        with SqliteEventStore.open(database) as first:
            first.append(make_event(event_id="a"))
        with SqliteEventStore.open(database) as second:
            second.append(make_event(event_id="b"))

        with SqliteEventStore.open(database) as third:
            assert len(third.read_latest(limit=10)) == 2

    def test_opening_an_unusable_path_fails_explicitly(self, tmp_path: Path) -> None:
        blocking_file = tmp_path / "blocker"
        blocking_file.write_text("not a directory", encoding="utf-8")

        with pytest.raises(EventStoreError, match="event store"):
            SqliteEventStore.open(blocking_file / "events.db")


class TestFailures:
    def test_append_on_a_closed_store_raises_append_error(self, store: SqliteEventStore) -> None:
        store.close()

        with pytest.raises(EventAppendError, match="falha ao registrar"):
            store.append(make_event())

    def test_read_on_a_closed_store_raises_read_error(self, store: SqliteEventStore) -> None:
        store.close()

        with pytest.raises(EventReadError, match="consultar"):
            store.read_latest(limit=1)

    def test_driver_errors_do_not_leak(self, store: SqliteEventStore) -> None:
        store.close()

        with pytest.raises(EventStoreError) as exc_info:
            store.get("x")

        assert isinstance(exc_info.value.__cause__, sqlite3.Error)


def test_store_satisfies_the_event_store_port(store: SqliteEventStore) -> None:
    port: EventStore = store
    event: Event = make_event()

    assert port.append(event).event.event == event
