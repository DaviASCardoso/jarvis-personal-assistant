"""Testes da Interruption Policy (Fase 7.2)."""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.model import ConversationContext, CurrentContext, EnvironmentContext
from jarvis.proactivity.interruption import (
    InterruptionPolicy,
    InterruptionSettings,
    RecentNotification,
)
from tests.context_doubles import make_observation

NOW = datetime(2026, 8, 17, 15, 0, tzinfo=UTC)


def _context(**kwargs: object) -> CurrentContext:
    return CurrentContext(as_of=NOW, **kwargs)  # type: ignore[arg-type]


def test_high_importance_with_no_context_signal_interrupts() -> None:
    policy = InterruptionPolicy()
    decision = policy.evaluate(importance=0.8, context=_context(), subject="printer", now=NOW)
    assert decision.should_interrupt is True
    assert decision.suppressed_by is None


def test_below_threshold_suppresses() -> None:
    policy = InterruptionPolicy(InterruptionSettings(importance_threshold=0.6))
    decision = policy.evaluate(importance=0.5, context=_context(), subject="printer", now=NOW)
    assert decision.should_interrupt is False
    assert decision.suppressed_by == "importance"


def test_active_fresh_conversation_suppresses() -> None:
    context = _context(
        conversation=ConversationContext(
            active_id=make_observation("session-1", observed_at=NOW, ttl=timedelta(minutes=5))
        )
    )
    policy = InterruptionPolicy()
    decision = policy.evaluate(importance=0.8, context=context, subject="x", now=NOW)
    assert decision.should_interrupt is False
    assert decision.suppressed_by == "conversation"


def test_stale_conversation_does_not_suppress() -> None:
    old = NOW - timedelta(hours=1)
    context = _context(
        conversation=ConversationContext(
            active_id=make_observation("session-1", observed_at=old, ttl=timedelta(minutes=5))
        )
    )
    policy = InterruptionPolicy()
    decision = policy.evaluate(importance=0.8, context=context, subject="x", now=NOW)
    assert decision.should_interrupt is True


def test_explicit_absence_of_conversation_does_not_suppress() -> None:
    context = _context(
        conversation=ConversationContext(active_id=make_observation(None, observed_at=NOW))
    )
    policy = InterruptionPolicy()
    decision = policy.evaluate(importance=0.8, context=context, subject="x", now=NOW)
    assert decision.should_interrupt is True


def test_quiet_hours_suppress_when_local_hour_falls_inside() -> None:
    # NOW é 15:00 UTC; offset -03:00 -> hora local 12:00.
    context = _context(
        environment=EnvironmentContext(utc_offset=make_observation("-03:00", observed_at=NOW))
    )
    policy = InterruptionPolicy(InterruptionSettings(quiet_hours_start=10, quiet_hours_end=14))
    decision = policy.evaluate(importance=0.8, context=context, subject="x", now=NOW)
    assert decision.should_interrupt is False
    assert decision.suppressed_by == "quiet_hours"


def test_quiet_hours_wrap_around_midnight() -> None:
    # hora local 12:00, janela 22-7 não cobre 12:00 -> não suprime.
    context = _context(
        environment=EnvironmentContext(utc_offset=make_observation("-03:00", observed_at=NOW))
    )
    policy = InterruptionPolicy(InterruptionSettings(quiet_hours_start=22, quiet_hours_end=7))
    decision = policy.evaluate(importance=0.8, context=context, subject="x", now=NOW)
    assert decision.should_interrupt is True


def test_unknown_offset_skips_quiet_hours_check() -> None:
    policy = InterruptionPolicy(InterruptionSettings(quiet_hours_start=0, quiet_hours_end=23))
    decision = policy.evaluate(importance=0.8, context=_context(), subject="x", now=NOW)
    assert decision.should_interrupt is True
    assert any("quiet_hours=unknown_offset" in item for item in decision.considered)


def test_recent_notification_within_cooldown_suppresses() -> None:
    policy = InterruptionPolicy(InterruptionSettings(cooldown_seconds=600))
    recent = (RecentNotification(subject="printer", sent_at=NOW - timedelta(minutes=5)),)
    decision = policy.evaluate(
        importance=0.8, context=_context(), subject="printer", recent=recent, now=NOW
    )
    assert decision.should_interrupt is False
    assert decision.suppressed_by == "cooldown"


def test_recent_notification_outside_cooldown_does_not_suppress() -> None:
    policy = InterruptionPolicy(InterruptionSettings(cooldown_seconds=60))
    recent = (RecentNotification(subject="printer", sent_at=NOW - timedelta(minutes=5)),)
    decision = policy.evaluate(
        importance=0.8, context=_context(), subject="printer", recent=recent, now=NOW
    )
    assert decision.should_interrupt is True


def test_recent_notification_with_different_subject_does_not_suppress() -> None:
    policy = InterruptionPolicy(InterruptionSettings(cooldown_seconds=600))
    recent = (RecentNotification(subject="calendar", sent_at=NOW - timedelta(minutes=1)),)
    decision = policy.evaluate(
        importance=0.8, context=_context(), subject="printer", recent=recent, now=NOW
    )
    assert decision.should_interrupt is True


def test_location_is_always_recorded_as_considered() -> None:
    policy = InterruptionPolicy()
    decision = policy.evaluate(importance=0.8, context=_context(), subject="x", now=NOW)
    assert any(item.startswith("location=") for item in decision.considered)


def test_settings_reject_invalid_quiet_hour() -> None:
    with pytest.raises(ValueError, match="quiet_hours_start"):
        InterruptionSettings(quiet_hours_start=24)


def test_settings_reject_negative_cooldown() -> None:
    with pytest.raises(ValueError, match="cooldown_seconds"):
        InterruptionSettings(cooldown_seconds=-1)
