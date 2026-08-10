from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from jarvis.context.errors import InvalidContextError
from jarvis.context.freshness import DEFAULT_TTL_POLICY, TtlPolicy
from jarvis.context.model import ContextField
from jarvis.context.observation import Freshness
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def test_default_policy_covers_every_field() -> None:
    for field in ContextField:
        DEFAULT_TTL_POLICY.ttl_for(field)


def test_missing_field_is_an_error_not_a_silent_default() -> None:
    policy = TtlPolicy(ttl_by_field=MappingProxyType({ContextField.PLACE: timedelta(minutes=5)}))

    with pytest.raises(InvalidContextError, match="availability"):
        policy.ttl_for(ContextField.AVAILABILITY)


def test_a_field_may_declare_that_it_never_expires() -> None:
    assert DEFAULT_TTL_POLICY.ttl_for(ContextField.DEVICE_ID) is None


def test_ttl_is_per_field_not_global() -> None:
    """Dois campos observados juntos vencem em momentos diferentes."""
    short = DEFAULT_TTL_POLICY.ttl_for(ContextField.PLACE)
    long = DEFAULT_TTL_POLICY.ttl_for(ContextField.TASK)
    assert short is not None and long is not None
    assert short < long

    place = make_observation("home", observed_at=NOON, ttl=short)
    task = make_observation("t-1", observed_at=NOON, ttl=long)

    later = NOON + short + timedelta(seconds=1)

    assert place.freshness(later) is Freshness.STALE
    assert task.freshness(later) is Freshness.FRESH


def test_no_single_ttl_governs_the_whole_context() -> None:
    distinct = {DEFAULT_TTL_POLICY.ttl_for(field) for field in ContextField}

    assert len(distinct) > 1
