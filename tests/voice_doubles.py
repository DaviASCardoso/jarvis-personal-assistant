"""Doubles e geradores de áudio da camada de voz.

Nenhum teste desta fase abre microfone, alto-falante ou socket. O que substitui o
mundo real é este módulo: PCM sintético determinístico (uma senoide e zeros) e
implementações roteirizadas dos sete ports.

A senoide existe para que `rms` tenha um valor **conhecido**: uma onda de
amplitude `a` tem RMS `a / √2`, o que torna verificável tanto a função quanto o
limiar do VAD.
"""

import math
import urllib.error
import urllib.request
from array import array
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from io import BytesIO

from jarvis.voice.audio import CAPTURE_FORMAT, AudioChunk, AudioFormat, PcmClip
from jarvis.voice.errors import SpeechToTextError, TextToSpeechError
from jarvis.voice.ports import (
    AgentReply,
    PlaybackResult,
    Transcript,
    WakeWordDetection,
)
from jarvis.voice.session import VoiceSession

#: Duração padrão de um bloco. 100 ms é o que um backend real costuma entregar e
#: divide os limites do VAD sem sobra, o que mantém os testes legíveis.
BLOCK_SECONDS = 0.1

EPOCH = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

LOUD_AMPLITUDE = 0.5
FAINT_AMPLITUDE = 0.005


def pcm_tone(
    seconds: float,
    *,
    amplitude: float = LOUD_AMPLITUDE,
    frequency: float = 440.0,
    audio_format: AudioFormat = CAPTURE_FORMAT,
) -> bytes:
    """Senoide em PCM s16le, com RMS previsível (`amplitude / √2`)."""
    frames = int(seconds * audio_format.sample_rate)
    peak = amplitude * 32767
    samples = array(
        "h",
        (
            int(peak * math.sin(2 * math.pi * frequency * index / audio_format.sample_rate))
            for index in range(frames)
        ),
    )
    return samples.tobytes()


def tone(
    seconds: float = BLOCK_SECONDS,
    *,
    amplitude: float = LOUD_AMPLITUDE,
    at: datetime = EPOCH,
    audio_format: AudioFormat = CAPTURE_FORMAT,
) -> AudioChunk:
    return AudioChunk(
        data=pcm_tone(seconds, amplitude=amplitude, audio_format=audio_format),
        format=audio_format,
        captured_at=at,
    )


def quiet(
    seconds: float = BLOCK_SECONDS,
    *,
    at: datetime = EPOCH,
    audio_format: AudioFormat = CAPTURE_FORMAT,
) -> AudioChunk:
    frames = int(seconds * audio_format.sample_rate)
    return AudioChunk(
        data=b"\x00" * (frames * audio_format.frame_bytes), format=audio_format, captured_at=at
    )


def stream(
    pattern: Sequence[tuple[str, float]],
    *,
    start: datetime = EPOCH,
    amplitude: float = LOUD_AMPLITUDE,
) -> list[AudioChunk]:
    """Converte `[("loud", 0.5), ("quiet", 1.0)]` numa lista de blocos de 100 ms.

    `captured_at` avança bloco a bloco, para que o segmento tenha começo e fim
    verificáveis.
    """
    chunks: list[AudioChunk] = []
    moment = start
    for kind, seconds in pattern:
        for _ in range(round(seconds / BLOCK_SECONDS)):
            chunks.append(
                tone(BLOCK_SECONDS, amplitude=amplitude, at=moment)
                if kind == "loud"
                else quiet(BLOCK_SECONDS, at=moment)
            )
            moment += timedelta(seconds=BLOCK_SECONDS)
    return chunks


class FakeAudioSource:
    """Reproduz uma lista de blocos e depois devolve `None` para sempre."""

    def __init__(
        self, chunks: Sequence[AudioChunk] = (), *, audio_format: AudioFormat = CAPTURE_FORMAT
    ) -> None:
        self._chunks = list(chunks)
        self._format = audio_format
        self.started = 0
        self.stopped = 0
        self.closed = 0

    @property
    def format(self) -> AudioFormat:
        return self._format

    @property
    def remaining(self) -> int:
        return len(self._chunks)

    def extend(self, chunks: Sequence[AudioChunk]) -> None:
        self._chunks.extend(chunks)

    def start(self) -> None:
        self.started += 1

    def read(self, *, timeout_seconds: float) -> AudioChunk | None:
        if not self._chunks:
            return None
        return self._chunks.pop(0)

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1


class RecordingAudioSink:
    """Guarda o que foi tocado; `cancel_after` simula uma interrupção."""

    def __init__(
        self, *, audio_format: AudioFormat = CAPTURE_FORMAT, cancel_after: int | None = None
    ) -> None:
        self._format = audio_format
        self._cancel_after = cancel_after
        self.played: list[PcmClip] = []
        self.results: list[PlaybackResult] = []
        self.closed = 0

    @property
    def format(self) -> AudioFormat:
        return self._format

    def play(
        self, clip: PcmClip, *, cancelled: Callable[[], bool] = lambda: False
    ) -> PlaybackResult:
        self.played.append(clip)
        block = 0.05
        blocks = max(1, round(clip.duration_seconds / block))
        for index in range(blocks):
            if cancelled() or (self._cancel_after is not None and index >= self._cancel_after):
                result = PlaybackResult(played_seconds=index * block, interrupted=True)
                self.results.append(result)
                return result
        result = PlaybackResult(played_seconds=clip.duration_seconds, interrupted=False)
        self.results.append(result)
        return result

    def close(self) -> None:
        self.closed += 1


class ScriptedSpeechToText:
    """Devolve transcrições na ordem em que foram roteirizadas."""

    def __init__(
        self,
        transcripts: Sequence[str] = (),
        *,
        model: str = "fake-stt",
        error: Exception | None = None,
        fail_on: int | None = None,
    ) -> None:
        self._transcripts = list(transcripts)
        self._model = model
        self._error = error
        self._fail_on = fail_on
        self.calls: list[PcmClip] = []

    @property
    def model(self) -> str:
        return self._model

    def transcribe(
        self, clip: PcmClip, *, language: str | None = None, timeout_seconds: float
    ) -> Transcript:
        self.calls.append(clip)
        if self._error is not None and (self._fail_on is None or self._fail_on == len(self.calls)):
            raise self._error
        text = self._transcripts.pop(0) if self._transcripts else ""
        return Transcript(text=text, language=language, duration_seconds=clip.duration_seconds)


class ScriptedTextToSpeech:
    def __init__(self, *, voice: str = "fake-voice", error: Exception | None = None) -> None:
        self._voice = voice
        self._error = error
        self.calls: list[str] = []

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(self, text: str, *, timeout_seconds: float) -> PcmClip:
        self.calls.append(text)
        if self._error is not None:
            raise self._error
        return PcmClip(data=pcm_tone(0.2), format=CAPTURE_FORMAT)


class ScriptedWakeWord:
    """Dispara depois de `trigger_after` blocos, quantas vezes for preciso."""

    def __init__(
        self,
        *,
        trigger_after: int = 1,
        remainder: str = "",
        phrase: str = "jarvis",
        name: str = "scripted",
    ) -> None:
        self._trigger_after = trigger_after
        self._remainder = remainder
        self._phrase = phrase
        self._name = name
        self._seen = 0
        self.resets = 0
        self.closed = 0

    @property
    def name(self) -> str:
        return self._name

    def feed(self, chunk: AudioChunk) -> WakeWordDetection | None:
        self._seen += 1
        if self._seen < self._trigger_after:
            return None
        self._seen = 0
        return WakeWordDetection(
            phrase=self._phrase,
            detected_at=chunk.captured_at,
            detector=self._name,
            remainder=self._remainder,
        )

    def reset(self) -> None:
        self.resets += 1
        self._seen = 0

    def close(self) -> None:
        self.closed += 1


@dataclass
class ScriptedAgent:
    """Implementa `ConversationalAgent` sem LLM, memória ou execução."""

    replies: list[AgentReply] = field(default_factory=list)
    confirmation_reply: AgentReply | None = None
    error: Exception | None = None
    heard: list[str] = field(default_factory=list)
    confirmations: list[tuple[str, bool]] = field(default_factory=list)

    def respond(self, text: str, *, session: VoiceSession) -> AgentReply:
        self.heard.append(text)
        if self.error is not None:
            raise self.error
        if self.replies:
            return self.replies.pop(0)
        return AgentReply(text=f"eco: {text}", decision_type="notify")

    def answer_confirmation(
        self, execution_id: str, *, granted: bool, session: VoiceSession
    ) -> AgentReply:
        self.confirmations.append((execution_id, granted))
        if self.confirmation_reply is not None:
            return self.confirmation_reply
        return AgentReply(text="feito" if granted else "cancelado", decision_type="notify")


class InMemoryVoiceSessions:
    """Implementa `VoiceSessionRepository` sem banco."""

    def __init__(self) -> None:
        self.saved: dict[str, VoiceSession] = {}
        self.save_calls = 0

    def save(self, session: VoiceSession) -> None:
        self.save_calls += 1
        self.saved[session.session_id] = session

    def get(self, session_id: str) -> VoiceSession | None:
        return self.saved.get(session_id)

    def list(self, *, limit: int) -> Sequence[VoiceSession]:
        ordered = sorted(self.saved.values(), key=lambda item: item.started_at, reverse=True)
        return ordered[:limit]

    def purge(self, session_id: str) -> bool:
        return self.saved.pop(session_id, None) is not None

    def purge_before(self, cutoff: datetime) -> int:
        stale = [key for key, item in self.saved.items() if item.started_at < cutoff]
        for key in stale:
            del self.saved[key]
        return len(stale)


def stt_error(message: str = "falhou") -> SpeechToTextError:
    return SpeechToTextError(message)


def tts_error(message: str = "falhou") -> TextToSpeechError:
    return TextToSpeechError(message)


class RecordingOpener:
    """Transporte HTTP falso: guarda as requisições e devolve respostas roteirizadas.

    Um item da sequência que seja `Exception` é levantado em vez de devolvido —
    é o que torna testável a política de retry sem rede e sem espera.
    """

    def __init__(self, *responses: bytes | Exception) -> None:
        self._responses: list[bytes | Exception] = list(responses)
        self.captured: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.captured.append(request)
        self.timeouts.append(timeout)
        if not self._responses:
            return b"{}"
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def calls(self) -> int:
        return len(self.captured)


def failing_opener(error: Exception) -> Callable[[urllib.request.Request, float], bytes]:
    def opener(request: urllib.request.Request, timeout: float) -> bytes:
        raise error

    return opener


def http_error(status: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = EmailMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://example.invalid/voice",
        code=status,
        msg="erro de teste",
        hdrs=headers,
        fp=BytesIO(b"{}"),
    )


class SleepSpy:
    """Substitui `time.sleep` nas políticas de retry: registra e não dorme."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


class FakeMonotonic:
    """Relógio monotônico que anda um passo a cada consulta.

    É o que permite testar timeout de sessão sem esperar doze segundos de
    verdade — o loop recebe o relógio injetado, exatamente como o `AgentRuntime`.
    """

    def __init__(self, *, step: float = 5.0) -> None:
        self.now = 0.0
        self._step = step

    def __call__(self) -> float:
        self.now += self._step
        return self.now
