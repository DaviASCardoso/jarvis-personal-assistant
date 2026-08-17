"""Testes de `ConsoleNotificationChannel` (Fase 7.3)."""

from jarvis.notify.adapters.console import ConsoleNotificationChannel
from jarvis.notify.ports import DeliveryStatus
from tests.notify_doubles import make_notification


def test_writes_a_single_structured_line() -> None:
    lines: list[str] = []
    channel = ConsoleNotificationChannel(write=lines.append)

    result = channel.send(make_notification(title="Impressão", body="Terminou"))

    assert result.status is DeliveryStatus.SENT
    assert len(lines) == 1
    assert "Impressão" in lines[0]
    assert "Terminou" in lines[0]


def test_channel_id_is_console() -> None:
    channel = ConsoleNotificationChannel(write=lambda line: None)
    assert channel.channel_id == "console"
