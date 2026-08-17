"""Testes de `VoiceNotificationChannel` (Fase 7.3)."""

from jarvis.notify.adapters.voice import VoiceNotificationChannel
from jarvis.notify.ports import DeliveryStatus
from tests.notify_doubles import FakeAudioSink, FakeTextToSpeech, make_notification


def test_speaks_when_it_can_speak_now() -> None:
    tts = FakeTextToSpeech()
    sink = FakeAudioSink()
    channel = VoiceNotificationChannel(tts=tts, sink=sink, can_speak_now=lambda: True)

    result = channel.send(make_notification(title="Impressão", body="Terminou"))

    assert result.status is DeliveryStatus.SENT
    assert len(tts.synthesized) == 1
    assert "Impressão" in tts.synthesized[0]
    assert len(sink.played) == 1


def test_refuses_when_it_cannot_speak_now() -> None:
    tts = FakeTextToSpeech()
    sink = FakeAudioSink()
    channel = VoiceNotificationChannel(tts=tts, sink=sink, can_speak_now=lambda: False)

    result = channel.send(make_notification())

    assert result.status is DeliveryStatus.REFUSED
    assert tts.synthesized == []
    assert sink.played == []


def test_channel_id_is_voice() -> None:
    channel = VoiceNotificationChannel(
        tts=FakeTextToSpeech(), sink=FakeAudioSink(), can_speak_now=lambda: True
    )
    assert channel.channel_id == "voice"
