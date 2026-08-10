from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.context.errors import InvalidContextError
from jarvis.context.model import (
    ActivityContext,
    CurrentContext,
    EnvironmentContext,
    UserContext,
)
from jarvis.context.observation import Freshness
from jarvis.context.snapshot import ContextSnapshot, context_fingerprint, new_snapshot_id
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SAO_PAULO = timezone(timedelta(hours=-3))


def a_context() -> CurrentContext:
    return CurrentContext(
        as_of=NOON,
        user=UserContext(availability=make_observation("busy", observed_at=NOON)),
        environment=EnvironmentContext(local_time=make_observation(NOON, observed_at=NOON)),
    )


class TestModel:
    def test_normalises_captured_at_to_utc(self) -> None:
        snapshot = ContextSnapshot(
            snapshot_id="s-1",
            captured_at=datetime(2026, 8, 10, 9, 0, tzinfo=SAO_PAULO),
            context=a_context(),
        )

        assert snapshot.captured_at == NOON

    def test_rejects_naive_captured_at(self) -> None:
        with pytest.raises(InvalidContextError, match="captured_at"):
            ContextSnapshot(
                snapshot_id="s-1", captured_at=datetime(2026, 8, 10, 12, 0), context=a_context()
            )

    def test_rejects_blank_id(self) -> None:
        with pytest.raises(InvalidContextError, match="snapshot_id"):
            ContextSnapshot(snapshot_id="  ", captured_at=NOON, context=a_context())

    def test_is_immutable_all_the_way_down(self) -> None:
        snapshot = ContextSnapshot(snapshot_id="s-1", captured_at=NOON, context=a_context())

        with pytest.raises(FrozenInstanceError):
            snapshot.captured_at = NOON  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            snapshot.context.user.availability = None  # type: ignore[misc]

    def test_ids_are_unique(self) -> None:
        assert new_snapshot_id() != new_snapshot_id()


class TestPreservedMetadata:
    def test_keeps_provenance_of_every_field(self) -> None:
        observed_at = NOON - timedelta(minutes=5)
        context = replace(
            a_context(),
            user=UserContext(
                availability=make_observation(
                    "busy",
                    observed_at=observed_at,
                    source="event:user.availability_changed",
                    confidence=0.9,
                    ttl=timedelta(hours=4),
                )
            ),
        )

        snapshot = ContextSnapshot(snapshot_id="s-1", captured_at=NOON, context=context)

        availability = snapshot.context.user.availability
        assert availability is not None
        assert availability.source == "event:user.availability_changed"
        assert availability.confidence == 0.9
        assert availability.ttl == timedelta(hours=4)
        assert availability.observed_at == observed_at

    def test_staleness_is_derivable_from_the_snapshot_itself(self) -> None:
        context = replace(
            a_context(),
            user=UserContext(
                availability=make_observation(
                    "busy", observed_at=NOON - timedelta(hours=9), ttl=timedelta(hours=4)
                )
            ),
        )

        snapshot = ContextSnapshot(snapshot_id="s-1", captured_at=NOON, context=context)

        availability = snapshot.context.user.availability
        assert availability is not None
        # Sem coluna `stale`: a validade da captura se recalcula sozinha.
        assert availability.freshness(snapshot.captured_at) is Freshness.STALE


class TestFingerprint:
    def test_ignores_the_reading_instant(self) -> None:
        """`as_of` muda a cada leitura; incluí-lo esvaziaria a regra de relevância."""
        early = a_context()
        late = replace(early, as_of=NOON + timedelta(hours=3))

        assert context_fingerprint(early) == context_fingerprint(late)

    def test_changes_when_a_value_changes(self) -> None:
        before = a_context()
        after = replace(
            before, user=UserContext(availability=make_observation("available", observed_at=NOON))
        )

        assert context_fingerprint(before) != context_fingerprint(after)

    def test_changes_when_only_the_provenance_changes(self) -> None:
        before = a_context()
        after = replace(
            before,
            user=UserContext(
                availability=make_observation("busy", observed_at=NOON, source="provider:other")
            ),
        )

        assert context_fingerprint(before) != context_fingerprint(after)

    def test_distinguishes_unobserved_from_observed_absence(self) -> None:
        unobserved = a_context()
        observed = replace(
            unobserved,
            activity=ActivityContext(current=make_observation(None, observed_at=NOON)),
        )

        assert context_fingerprint(unobserved) != context_fingerprint(observed)

    def test_does_not_expose_the_values(self) -> None:
        fingerprint = context_fingerprint(a_context())

        assert "busy" not in fingerprint
        assert len(fingerprint) == 64
