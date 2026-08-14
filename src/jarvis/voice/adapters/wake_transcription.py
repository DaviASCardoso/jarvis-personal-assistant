"""Wake word por transcrição, com gate determinístico e orçamento.

A restrição da fase proíbe IA local, o que elimina Porcupine, openWakeWord e
qualquer detector acústico treinado. O que sobra sem quebrar a restrição é
verificar a frase **no texto**, e o preço disso é mandar trechos curtos do
ambiente para a nuvem — um preço que precisa ser controlado, não ignorado
([ADR-0021](../../../../docs/adr/0021-wake-word-without-local-ai.md)).

Quatro controles, e cada um existe por um cenário concreto:

1. **gate de energia e duração** (`Segmenter`): silêncio, tosse e clique nunca
   viram requisição — nada sai da máquina sem alguém ter falado;
2. **teto de segmento**: um trecho longo é fala contínua, não uma chamada pelo
   nome. Não vale transcrever;
3. **`WakeBudget`**: uma TV ligada consumiria a quota inteira em minutos. Passado
   o teto por minuto, os segmentos são descartados e o fato é logado uma vez;
4. **suspensão**: enquanto o Jarvis fala, o detector é pausado pelo loop — senão
   ele transcreve a própria voz e se acorda sozinho.

Este adapter depende do **port** `SpeechToText`, nunca da Groq. Trocar de provider
de transcrição não toca uma linha daqui.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Final

from jarvis.voice.audio import AudioChunk
from jarvis.voice.errors import SpeechToTextError
from jarvis.voice.ports import SpeechToText, WakeWordDetection
from jarvis.voice.vad import Segmenter, VadSettings
from jarvis.voice.wake import WakePhrase, matches

logger = logging.getLogger(__name__)

DETECTOR_NAME: Final = "transcription"

#: Um segmento mais longo que isto é fala contínua, não uma chamada pelo nome.
DEFAULT_MAX_SEGMENT_SECONDS: Final = 3.0

DEFAULT_BUDGET_PER_MINUTE: Final = 12


class WakeBudget:
    """Teto de transcrições por minuto, em janela deslizante.

    Janela deslizante e não contador por minuto de relógio: um teto que zera na
    virada do minuto permite o dobro de chamadas na fronteira.
    """

    def __init__(
        self, *, per_minute: int = DEFAULT_BUDGET_PER_MINUTE, monotonic: Callable[[], float]
    ) -> None:
        self._per_minute = per_minute
        self._monotonic = monotonic
        self._stamps: list[float] = []
        self._refused = 0

    @property
    def refused(self) -> int:
        return self._refused

    def take(self) -> bool:
        if self._per_minute <= 0:
            return False
        now = self._monotonic()
        self._stamps = [stamp for stamp in self._stamps if now - stamp < 60.0]
        if len(self._stamps) >= self._per_minute:
            self._refused += 1
            return False
        self._stamps.append(now)
        return True


class TranscriptionWakeWord:
    """Implementa `jarvis.voice.ports.WakeWordDetector`."""

    def __init__(
        self,
        *,
        stt: SpeechToText,
        phrases: Sequence[WakePhrase],
        vad: VadSettings | None = None,
        language: str | None = None,
        timeout_seconds: float = 15.0,
        max_segment_seconds: float = DEFAULT_MAX_SEGMENT_SECONDS,
        budget_per_minute: int = DEFAULT_BUDGET_PER_MINUTE,
        monotonic: Callable[[], float],
    ) -> None:
        self._stt = stt
        self._phrases = tuple(phrases)
        self._segmenter = Segmenter(settings=vad if vad is not None else VadSettings())
        self._language = language
        self._timeout = timeout_seconds
        self._max_segment_seconds = max_segment_seconds
        self._budget = WakeBudget(per_minute=budget_per_minute, monotonic=monotonic)
        self._warned_budget = False

    @property
    def name(self) -> str:
        return DETECTOR_NAME

    def feed(self, chunk: AudioChunk) -> WakeWordDetection | None:
        segment = self._segmenter.feed(chunk)
        if segment is None:
            return None
        if segment.clip.duration_seconds > self._max_segment_seconds:
            return None
        if not self._budget.take():
            if not self._warned_budget:
                logger.warning(
                    "voice.wake_budget_exhausted", extra={"refused": self._budget.refused}
                )
                self._warned_budget = True
            return None
        self._warned_budget = False

        try:
            transcript = self._stt.transcribe(
                segment.clip, language=self._language, timeout_seconds=self._timeout
            )
        except SpeechToTextError as error:
            # Falhar em ouvir não é falhar em existir: o detector segue vivo e o
            # próximo segmento tenta de novo.
            logger.warning(
                "voice.wake_transcription_failed", extra={"error_type": type(error).__name__}
            )
            return None

        if transcript.is_empty:
            return None
        found = matches(transcript.text, self._phrases)
        if found is None:
            return None

        phrase, remainder = found
        return WakeWordDetection(
            phrase=phrase,
            detected_at=segment.ended_at,
            detector=DETECTOR_NAME,
            transcript=transcript.text,
            remainder=remainder,
        )

    def reset(self) -> None:
        self._segmenter.reset()

    def close(self) -> None:
        """Nada a fechar: o transcritor é do composition root, e o segmentador é
        memória."""
