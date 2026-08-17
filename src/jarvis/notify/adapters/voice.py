"""Canal de voz: fala a notificação, mas só quando o Jarvis pode falar agora.

Não abre dispositivo de áudio por conta própria — recebe `TextToSpeech` e
`AudioSink` já construídos pelo composition root, mesma disciplina de
`RuntimeConversationalAgent` (`cli.py`). `can_speak_now` é injetado também: só
o composition root sabe se há uma sessão de voz ativa e em que estado ela
está; este adapter nunca lê `VoiceLoop`/`VoiceSession` diretamente.
"""

from collections.abc import Callable

from jarvis.notify.notification import Notification
from jarvis.notify.ports import DeliveryResult, DeliveryStatus
from jarvis.voice.ports import AudioSink, TextToSpeech

DEFAULT_TIMEOUT_SECONDS = 15.0


class VoiceNotificationChannel:
    def __init__(
        self,
        *,
        tts: TextToSpeech,
        sink: AudioSink,
        can_speak_now: Callable[[], bool],
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._tts = tts
        self._sink = sink
        self._can_speak_now = can_speak_now
        self._timeout_seconds = timeout_seconds

    @property
    def channel_id(self) -> str:
        return "voice"

    def send(self, notification: Notification) -> DeliveryResult:
        if not self._can_speak_now():
            return DeliveryResult(
                channel=self.channel_id, status=DeliveryStatus.REFUSED, detail="voz ocupada"
            )
        clip = self._tts.synthesize(
            f"{notification.title}. {notification.body}", timeout_seconds=self._timeout_seconds
        )
        self._sink.play(clip)
        return DeliveryResult(channel=self.channel_id, status=DeliveryStatus.SENT)
