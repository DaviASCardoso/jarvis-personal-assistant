"""Testes de `Notification` (Fase 7.3)."""

from datetime import UTC, datetime

import pytest

from jarvis.notify.errors import InvalidNotificationError
from jarvis.notify.notification import Notification, NotificationPriority
from tests.notify_doubles import make_notification


def test_valid_notification_builds() -> None:
    notification = make_notification()
    assert notification.priority is NotificationPriority.NORMAL
    assert notification.created_at.tzinfo is UTC


def test_rejects_empty_subject() -> None:
    with pytest.raises(InvalidNotificationError):
        make_notification(subject="  ")


def test_rejects_empty_title() -> None:
    with pytest.raises(InvalidNotificationError):
        make_notification(title="")


def test_rejects_empty_body() -> None:
    with pytest.raises(InvalidNotificationError):
        make_notification(body="")


def test_rejects_naive_datetime() -> None:
    with pytest.raises(InvalidNotificationError):
        Notification(
            notification_id="n1",
            subject="printer",
            title="t",
            body="b",
            correlation_id="c1",
            created_at=datetime(2026, 8, 17, 12, 0),
        )


def test_rejects_body_over_limit() -> None:
    with pytest.raises(InvalidNotificationError):
        make_notification(body="x" * 501)
