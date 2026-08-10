from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from jarvis.context.model import (
    ActivityContext,
    ContextField,
    ContextUpdate,
    CurrentContext,
    EnvironmentContext,
    UserContext,
    iter_fields,
)
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_every_context_field_has_a_matching_update_field() -> None:
    """Impede que um campo novo entre no modelo sem identidade, TTL e serialização."""
    assert {field.value for field in ContextField} == {
        field.name for field in fields(ContextUpdate)
    }


def test_iter_fields_covers_every_context_field_exactly_once() -> None:
    context = CurrentContext(as_of=NOON)

    assert [field for field, _ in iter_fields(context)] == list(ContextField)


class TestAbsence:
    def test_a_fresh_context_knows_nothing(self) -> None:
        context = CurrentContext(as_of=NOON)

        assert all(observation is None for _, observation in iter_fields(context))

    def test_unobserved_absence_differs_from_observed_absence(self) -> None:
        unobserved = ActivityContext()
        observed = ActivityContext(
            current=make_observation(None, source="event:user.activity_ended")
        )

        assert unobserved.current is None
        assert observed.current is not None
        assert observed.current.value is None
        # A segunda carrega proveniência; a primeira não existe como fato.
        assert observed.current.source == "event:user.activity_ended"


class TestImmutability:
    def test_subcontexts_are_frozen(self) -> None:
        user = UserContext(availability=make_observation("busy"))

        with pytest.raises(FrozenInstanceError):
            user.availability = None  # type: ignore[misc]

    def test_current_context_is_frozen(self) -> None:
        context = CurrentContext(as_of=NOON)

        with pytest.raises(FrozenInstanceError):
            context.as_of = NOON  # type: ignore[misc]


class TestContextUpdate:
    def test_is_empty_when_no_source_has_anything_to_say(self) -> None:
        assert ContextUpdate().is_empty()

    def test_is_not_empty_when_a_field_carries_an_observed_absence(self) -> None:
        update = ContextUpdate(activity=make_observation(None))

        assert not update.is_empty()

    def test_carries_typed_values(self) -> None:
        update = ContextUpdate(
            availability=make_observation("busy"),
            local_time=make_observation(NOON),
        )

        assert update.availability is not None
        assert update.availability.value == "busy"
        assert update.local_time is not None
        assert update.local_time.value == NOON


def test_context_groups_observations_under_the_seven_subcontexts() -> None:
    context = CurrentContext(
        as_of=NOON,
        user=UserContext(availability=make_observation("busy")),
        environment=EnvironmentContext(local_time=make_observation(NOON)),
    )

    populated = {field for field, observation in iter_fields(context) if observation is not None}

    assert populated == {ContextField.AVAILABILITY, ContextField.LOCAL_TIME}
