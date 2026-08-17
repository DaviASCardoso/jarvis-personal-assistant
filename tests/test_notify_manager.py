"""Testes do `NotificationManager` (Fase 7.3)."""

from datetime import UTC, datetime

from jarvis.context.model import CurrentContext
from jarvis.notify.manager import NotificationManager
from jarvis.notify.notification import NotificationPriority
from jarvis.notify.ports import DeliveryStatus
from jarvis.proactivity.interruption import InterruptionPolicy, InterruptionSettings
from tests.notify_doubles import FakeChannel, make_notification

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _context() -> CurrentContext:
    return CurrentContext(as_of=NOW)


def _manager(**kwargs: object) -> NotificationManager:
    return NotificationManager(clock=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def test_delivers_when_importance_clears_the_bar() -> None:
    channel = FakeChannel()
    manager = _manager(channels=[channel])
    outcome = manager.notify(make_notification(), importance=0.8, context=_context())

    assert outcome.delivered is True
    assert channel.sent == [outcome.notification]


def test_suppressed_notification_is_not_delivered_to_any_channel() -> None:
    channel = FakeChannel()
    policy = InterruptionPolicy(InterruptionSettings(importance_threshold=0.9))
    manager = _manager(channels=[channel], interruption_policy=policy)
    outcome = manager.notify(make_notification(), importance=0.1, context=_context())

    assert outcome.delivered is False
    assert outcome.decision.suppressed_by == "importance"
    assert channel.sent == []


def test_silent_mode_suppresses_normal_priority() -> None:
    channel = FakeChannel()
    manager = _manager(channels=[channel], silent_mode=True)
    outcome = manager.notify(make_notification(), importance=0.9, context=_context())

    assert outcome.delivered is False
    assert outcome.decision.suppressed_by == "silent_mode"
    assert channel.sent == []


def test_silent_mode_still_delivers_urgent() -> None:
    channel = FakeChannel()
    manager = _manager(channels=[channel], silent_mode=True)
    urgent = make_notification(priority=NotificationPriority.URGENT)
    outcome = manager.notify(urgent, importance=0.9, context=_context())

    assert outcome.delivered is True
    assert channel.sent == [urgent]


def test_falls_back_to_next_channel_when_first_refuses() -> None:
    refusing = FakeChannel(channel_id="voice", status=DeliveryStatus.REFUSED)
    accepting = FakeChannel(channel_id="console")
    manager = _manager(channels=[refusing, accepting])
    outcome = manager.notify(make_notification(), importance=0.9, context=_context())

    assert outcome.delivered is True
    assert outcome.result is not None
    assert outcome.result.channel == "console"
    assert refusing.sent and accepting.sent


def test_no_channel_configured_reports_failure_without_raising() -> None:
    manager = _manager(channels=[])
    outcome = manager.notify(make_notification(), importance=0.9, context=_context())

    assert outcome.delivered is False
    assert outcome.result is not None
    assert outcome.result.status is DeliveryStatus.FAILED


def test_delivered_notification_is_remembered_for_cooldown() -> None:
    channel = FakeChannel()
    manager = _manager(channels=[channel])
    manager.notify(make_notification(subject="printer"), importance=0.9, context=_context())

    assert len(manager.history) == 1
    assert manager.history[0].subject == "printer"


def test_suppressed_notification_is_not_remembered() -> None:
    channel = FakeChannel()
    policy = InterruptionPolicy(InterruptionSettings(importance_threshold=0.9))
    manager = _manager(channels=[channel], interruption_policy=policy)
    manager.notify(make_notification(), importance=0.1, context=_context())

    assert manager.history == ()


def test_cooldown_suppresses_second_notification_on_the_same_subject() -> None:
    channel = FakeChannel()
    policy = InterruptionPolicy(InterruptionSettings(cooldown_seconds=600))
    manager = _manager(channels=[channel], interruption_policy=policy)
    manager.notify(make_notification(subject="printer"), importance=0.9, context=_context())
    second = manager.notify(
        make_notification(subject="printer", notification_id="n2"),
        importance=0.9,
        context=_context(),
    )

    assert second.delivered is False
    assert second.decision.suppressed_by == "cooldown"
    assert len(channel.sent) == 1
