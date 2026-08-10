import logging
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from jarvis.context.freshness import DEFAULT_TTL_POLICY, TtlPolicy
from jarvis.context.model import ContextField, ContextUpdate
from jarvis.context.observation import Freshness
from jarvis.context.projection import ContextProjection
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
EARLIER = NOON - timedelta(hours=1)
LATER = NOON + timedelta(hours=1)


def availability(value: str, observed_at: datetime, *, source: str = "provider:a") -> ContextUpdate:
    return ContextUpdate(
        availability=make_observation(value, observed_at=observed_at, source=source)
    )


class TestMerge:
    def test_first_observation_populates_an_empty_field(self) -> None:
        projection = ContextProjection()

        conflicts = projection.apply(availability("busy", NOON))

        context = projection.snapshot_of(as_of=NOON)
        assert conflicts == ()
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"

    def test_a_source_that_says_nothing_leaves_the_field_alone(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON))

        projection.apply(ContextUpdate())

        context = projection.snapshot_of(as_of=NOON)
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"

    def test_more_recent_observation_wins(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON))

        projection.apply(availability("available", LATER, source="provider:b"))

        context = projection.snapshot_of(as_of=LATER)
        assert context.user.availability is not None
        assert context.user.availability.value == "available"

    def test_late_arriving_older_observation_does_not_win(self) -> None:
        """Ordem de chegada não é ordem de observação."""
        projection = ContextProjection()
        projection.apply(availability("busy", NOON))

        projection.apply(availability("available", EARLIER, source="provider:b"))

        context = projection.snapshot_of(as_of=LATER)
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"

    def test_tie_keeps_the_incumbent(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON, source="provider:a"))

        projection.apply(availability("available", NOON, source="provider:b"))

        context = projection.snapshot_of(as_of=NOON)
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"
        assert context.user.availability.source == "provider:a"

    def test_confidence_does_not_override_observed_at(self) -> None:
        projection = ContextProjection()
        projection.apply(
            ContextUpdate(
                availability=make_observation(
                    "busy", observed_at=NOON, source="provider:a", confidence=0.2
                )
            )
        )

        projection.apply(
            ContextUpdate(
                availability=make_observation(
                    "available", observed_at=EARLIER, source="provider:b", confidence=1.0
                )
            )
        )

        context = projection.snapshot_of(as_of=NOON)
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"


class TestIdempotence:
    def test_reapplying_the_same_observation_changes_nothing(self) -> None:
        projection = ContextProjection()
        update = availability("busy", NOON)

        first = projection.apply(update)
        before = projection.snapshot_of(as_of=NOON)
        repeats = [projection.apply(update) for _ in range(4)]

        assert first == ()
        assert all(conflicts == () for conflicts in repeats)
        assert projection.snapshot_of(as_of=NOON) == before

    def test_repeating_a_value_from_another_source_is_not_a_conflict(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON, source="provider:a"))

        conflicts = projection.apply(availability("busy", LATER, source="provider:b"))

        assert conflicts == ()


class TestConflicts:
    def test_conflict_is_returned_as_data(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON, source="provider:a"))

        conflicts = projection.apply(availability("available", LATER, source="provider:b"))

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.field is ContextField.AVAILABILITY
        assert (conflict.winner_source, conflict.loser_source) == ("provider:b", "provider:a")
        assert conflict.winner_observed_at == LATER
        assert conflict.loser_observed_at == NOON

    def test_conflict_is_logged_without_the_values(self, caplog: pytest.LogCaptureFixture) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON, source="provider:a"))

        with caplog.at_level(logging.INFO, logger="jarvis.context.projection"):
            projection.apply(availability("available", LATER, source="provider:b"))

        record = next(item for item in caplog.records if item.message == "context.conflict")
        assert record.field == "availability"  # type: ignore[attr-defined]
        assert "busy" not in caplog.text
        assert "available" not in caplog.text

    def test_a_losing_observation_is_reported_even_though_it_loses(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON, source="provider:a"))

        conflicts = projection.apply(availability("available", EARLIER, source="provider:b"))

        assert len(conflicts) == 1
        assert conflicts[0].loser_source == "provider:b"

    def test_conflicts_from_one_update_are_reported_per_field(self) -> None:
        projection = ContextProjection()
        projection.apply(
            ContextUpdate(
                availability=make_observation("busy", observed_at=NOON),
                place=make_observation("home", observed_at=NOON),
            )
        )

        conflicts = projection.apply(
            ContextUpdate(
                availability=make_observation("available", observed_at=LATER, source="b"),
                place=make_observation("work", observed_at=LATER, source="b"),
            )
        )

        assert {conflict.field for conflict in conflicts} == {
            ContextField.AVAILABILITY,
            ContextField.PLACE,
        }


class TestTtlStamping:
    def test_merge_stamps_the_policy_ttl(self) -> None:
        projection = ContextProjection()

        projection.apply(availability("busy", NOON))

        context = projection.snapshot_of(as_of=NOON)
        assert context.user.availability is not None
        assert context.user.availability.ttl == DEFAULT_TTL_POLICY.ttl_for(
            ContextField.AVAILABILITY
        )

    def test_policy_overrides_whatever_ttl_the_source_declared(self) -> None:
        policy = TtlPolicy(
            ttl_by_field=MappingProxyType({field: timedelta(minutes=5) for field in ContextField})
        )
        projection = ContextProjection(policy=policy)

        projection.apply(
            ContextUpdate(
                availability=make_observation("busy", observed_at=NOON, ttl=timedelta(days=99))
            )
        )

        context = projection.snapshot_of(as_of=NOON)
        assert context.user.availability is not None
        assert context.user.availability.ttl == timedelta(minutes=5)

    def test_value_goes_stale_without_being_discarded(self) -> None:
        projection = ContextProjection()
        projection.apply(availability("busy", NOON))

        ttl = DEFAULT_TTL_POLICY.ttl_for(ContextField.AVAILABILITY)
        assert ttl is not None
        much_later = NOON + ttl + timedelta(minutes=1)

        context = projection.snapshot_of(as_of=much_later)
        assert context.user.availability is not None
        assert context.user.availability.freshness(much_later) is Freshness.STALE
        assert context.user.availability.value == "busy"


class TestObservedAbsence:
    def test_an_observed_absence_replaces_a_value(self) -> None:
        projection = ContextProjection()
        projection.apply(ContextUpdate(activity=make_observation("working", observed_at=NOON)))

        projection.apply(
            ContextUpdate(
                activity=make_observation(
                    None, observed_at=LATER, source="event:user.activity_ended"
                )
            )
        )

        context = projection.snapshot_of(as_of=LATER)
        assert context.activity.current is not None
        assert context.activity.current.value is None
        assert context.activity.current.source == "event:user.activity_ended"

    def test_the_projection_never_invents_a_value(self) -> None:
        projection = ContextProjection()

        projection.apply(ContextUpdate(availability=make_observation("busy", observed_at=NOON)))

        context = projection.snapshot_of(as_of=NOON)
        assert context.activity.current is None
        assert context.conversation.active_id is None
        assert context.task.active_id is None
