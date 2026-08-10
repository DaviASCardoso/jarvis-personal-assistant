import logging
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.engine import ContextEngine
from jarvis.context.model import ContextUpdate
from tests.context_doubles import (
    FakeSnapshotRepository,
    StubProvider,
    frozen_clock,
    make_observation,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


def build_engine(
    *,
    update: ContextUpdate | None = None,
    moments: tuple[datetime, ...] = (NOON,),
) -> tuple[ContextEngine, ContextAggregator, FakeSnapshotRepository]:
    snapshots = FakeSnapshotRepository()
    providers = [StubProvider(update)] if update is not None else []
    aggregator = ContextAggregator(providers=providers, clock=frozen_clock(*moments))
    identifiers = iter(f"s-{index}" for index in range(100))
    engine = ContextEngine(
        aggregator=aggregator,
        snapshots=snapshots,
        clock=frozen_clock(*moments),
        new_id=lambda: next(identifiers),
    )
    return engine, aggregator, snapshots


class TestCapture:
    def test_captures_the_current_projection(self) -> None:
        engine, _, snapshots = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()

        captured = engine.capture_snapshot()

        assert captured is not None
        assert snapshots.saved == [captured]
        assert captured.context.user.availability is not None
        assert captured.context.user.availability.value == "busy"

    def test_an_unchanged_context_is_not_captured_again(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine, _, snapshots = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()
        engine.capture_snapshot()

        with caplog.at_level(logging.DEBUG, logger="jarvis.context.engine"):
            second = engine.capture_snapshot()

        assert second is None
        assert len(snapshots.saved) == 1
        assert "context.snapshot_unchanged" in caplog.text

    def test_a_changed_context_is_captured(self) -> None:
        engine, aggregator, snapshots = build_engine()
        engine.capture_snapshot()

        aggregator.apply(ContextUpdate(availability=make_observation("busy", observed_at=NOON)))
        second = engine.capture_snapshot()

        assert second is not None
        assert len(snapshots.saved) == 2

    def test_capture_logs_metadata_but_never_values(self, caplog: pytest.LogCaptureFixture) -> None:
        engine, _, _ = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()

        with caplog.at_level(logging.INFO, logger="jarvis.context.engine"):
            engine.capture_snapshot()

        record = next(
            item for item in caplog.records if item.message == "context.snapshot_captured"
        )
        assert record.field_count == 1  # type: ignore[attr-defined]
        assert record.stale_count == 0  # type: ignore[attr-defined]
        assert "busy" not in caplog.text

    def test_counts_stale_fields_at_capture_time(self) -> None:
        engine, _, _ = build_engine(
            update=ContextUpdate(
                availability=make_observation("busy", observed_at=NOON - timedelta(days=1))
            ),
            moments=(NOON,),
        )
        engine.refresh()

        captured = engine.capture_snapshot()

        assert captured is not None
        availability = captured.context.user.availability
        assert availability is not None
        assert availability.is_stale(captured.captured_at)


class TestHistoryAndExpiration:
    def test_history_delegates_to_the_repository(self) -> None:
        engine, _, _ = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()
        engine.capture_snapshot()

        found = engine.history(NOON - timedelta(days=1), NOON + timedelta(days=1))

        assert len(found) == 1

    def test_expiration_is_explicit_and_reports_the_count(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        engine, _, _ = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()
        engine.capture_snapshot()

        with caplog.at_level(logging.WARNING, logger="jarvis.context.engine"):
            expired = engine.expire_before(LATER)

        assert expired == 1
        record = next(
            item for item in caplog.records if item.message == "context.snapshots_expired"
        )
        assert record.expired == 1  # type: ignore[attr-defined]

    def test_nothing_expires_without_being_asked(self) -> None:
        engine, _, snapshots = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()
        engine.capture_snapshot()

        engine.history(NOON - timedelta(days=1), NOON + timedelta(days=1))
        engine.current()

        assert snapshots.expired == set()

    def test_expired_snapshots_remain_readable(self) -> None:
        engine, _, _ = build_engine(
            update=ContextUpdate(availability=make_observation("busy", observed_at=NOON))
        )
        engine.refresh()
        engine.capture_snapshot()
        engine.expire_before(LATER)

        window = (NOON - timedelta(days=1), NOON + timedelta(days=1))

        assert engine.history(*window) == []
        assert len(engine.history(*window, include_expired=True)) == 1
