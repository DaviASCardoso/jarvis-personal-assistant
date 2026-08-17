"""Doubles do Notification Manager (Fase 7.3)."""

from collections.abc import Callable
from datetime import UTC, datetime

from jarvis.notify.notification import Notification, NotificationPriority
from jarvis.notify.ports import DeliveryResult, DeliveryStatus
from jarvis.voice.audio import AudioFormat, PcmClip
from jarvis.voice.ports import PlaybackResult

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def make_notification(
    *,
    notification_id: str = "notif-1",
    subject: str = "printer",
    title: str = "Impressão concluída",
    body: str = "O trabalho terminou.",
    priority: NotificationPriority = NotificationPriority.NORMAL,
    correlation_id: str = "corr-1",
    created_at: datetime = NOW,
) -> Notification:
    return Notification(
        notification_id=notification_id,
        subject=subject,
        title=title,
        body=body,
        priority=priority,
        correlation_id=correlation_id,
        created_at=created_at,
    )


class FakeChannel:
    """Canal programável: devolve o `status` configurado e registra o que recebeu."""

    def __init__(
        self, *, channel_id: str = "fake", status: DeliveryStatus = DeliveryStatus.SENT
    ) -> None:
        self._channel_id = channel_id
        self._status = status
        self.sent: list[Notification] = []

    @property
    def channel_id(self) -> str:
        return self._channel_id

    def send(self, notification: Notification) -> DeliveryResult:
        self.sent.append(notification)
        return DeliveryResult(channel=self._channel_id, status=self._status)


class FakeTextToSpeech:
    def __init__(self, *, voice: str = "fake-voice") -> None:
        self._voice = voice
        self.synthesized: list[str] = []

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(self, text: str, *, timeout_seconds: float) -> PcmClip:
        self.synthesized.append(text)
        return PcmClip(data=b"", format=AudioFormat())


class FakeAudioSink:
    def __init__(self) -> None:
        self.played: list[PcmClip] = []

    @property
    def format(self) -> AudioFormat:
        return AudioFormat()

    def play(
        self, clip: PcmClip, *, cancelled: Callable[[], bool] = lambda: False
    ) -> PlaybackResult:
        self.played.append(clip)
        return PlaybackResult(played_seconds=clip.duration_seconds)

    def close(self) -> None:
        return None
