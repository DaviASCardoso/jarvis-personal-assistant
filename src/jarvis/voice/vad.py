"""Segmentação de fala por energia — determinística, sem modelo.

É a peça que torna a Fase 6 possível sob a restrição "nenhuma IA local"
([ADR-0021](../../../docs/adr/0021-wake-word-without-local-ai.md)): decidir
*quando alguém começou e parou de falar* não exige inferência, exige aritmética.
O `Segmenter` compara o RMS de cada bloco com um limiar e conta silêncio — é
tudo.

Determinismo é a propriedade que se está comprando: a mesma sequência de blocos
produz exatamente os mesmos segmentos, então o comportamento é testável com PCM
sintético, sem microfone e sem gravação.

Três decisões que não são óbvias:

- **pre-roll**: os blocos imediatamente anteriores ao disparo são guardados e
  entram no segmento. Sem eles, o limiar corta a primeira sílaba e o que chega ao
  transcritor é "arvis, que horas são";
- **silêncio final não é aparado**: fica no clip. Aparar exigiria decidir quanto
  manter, e um pouco de silêncio no fim ajuda o transcritor a fechar a última
  palavra;
- **segmento curto é descartado, não entregue**: tosse, porta batendo e clique de
  mouse passam do limiar por 60 ms. Entregá-los viraria requisição paga e
  transcrição de nada.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from jarvis.voice.audio import MAX_CLIP_SECONDS, AudioChunk, PcmClip, concat
from jarvis.voice.errors import InvalidVoiceInputError

# Durações de bloco são somadas em ponto flutuante, e oito blocos de 100 ms dão
# 799,99 ms. Sem essa folga, todo limite fecharia um bloco tarde — o que não é
# grave em produção e tornaria os testes de fronteira impossíveis de escrever
# honestamente.
_TOLERANCE: Final = 1e-6


class SegmentEnd(StrEnum):
    """Por que o segmento fechou. O loop trata os três casos igual; o painel e o
    log não."""

    SILENCE = "silence"
    MAX_DURATION = "max_duration"
    FLUSH = "flush"


@dataclass(frozen=True, slots=True, kw_only=True)
class VadSettings:
    rms_threshold: float = 0.02
    min_speech_ms: int = 300
    silence_ms: int = 800
    max_utterance_seconds: float = 20.0
    pre_roll_ms: int = 300

    def __post_init__(self) -> None:
        if not 0.0 < self.rms_threshold < 1.0:
            raise InvalidVoiceInputError(
                f"rms_threshold precisa estar entre 0 e 1, recebido {self.rms_threshold}"
            )
        if self.min_speech_ms < 0 or self.silence_ms <= 0 or self.pre_roll_ms < 0:
            raise InvalidVoiceInputError("os limites de tempo do VAD precisam ser positivos")
        if not 0 < self.max_utterance_seconds <= MAX_CLIP_SECONDS:
            raise InvalidVoiceInputError(
                f"max_utterance_seconds precisa estar entre 0 e {MAX_CLIP_SECONDS:.0f}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SpeechSegment:
    clip: PcmClip
    started_at: datetime
    ended_at: datetime
    reason: SegmentEnd
    speech_seconds: float


class Segmenter:
    """Máquina de estados sobre blocos de áudio.

    Não conhece dispositivo, rede nem relógio de parede: o tempo vem de
    `AudioChunk.captured_at`, e a duração, do próprio formato do bloco.
    """

    def __init__(self, *, settings: VadSettings | None = None) -> None:
        self._settings = settings if settings is not None else VadSettings()
        self._pre_roll: deque[AudioChunk] = deque()
        self._pre_roll_seconds = 0.0
        self._voiced: list[AudioChunk] = []
        self._voiced_seconds = 0.0
        self._speech_seconds = 0.0
        self._silence_seconds = 0.0
        self._speaking = False

    @property
    def settings(self) -> VadSettings:
        return self._settings

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        # Religa em vez de esvaziar: `_close` segura uma referência à lista de
        # blocos enquanto chama isto, e limpá-la no lugar apagaria o segmento
        # que está sendo devolvido.
        self._pre_roll = deque()
        self._pre_roll_seconds = 0.0
        self._voiced = []
        self._voiced_seconds = 0.0
        self._speech_seconds = 0.0
        self._silence_seconds = 0.0
        self._speaking = False

    def feed(self, chunk: AudioChunk) -> SpeechSegment | None:
        loud = chunk.rms >= self._settings.rms_threshold
        duration = chunk.duration_seconds

        if not self._speaking:
            if not loud:
                self._remember(chunk, duration)
                return None
            self._start(chunk, duration)
            return None

        self._voiced.append(chunk)
        self._voiced_seconds += duration
        if loud:
            self._speech_seconds += duration
            self._silence_seconds = 0.0
        else:
            self._silence_seconds += duration

        if self._silence_seconds * 1000 + _TOLERANCE >= self._settings.silence_ms:
            return self._close(SegmentEnd.SILENCE)
        if self._voiced_seconds + _TOLERANCE >= self._settings.max_utterance_seconds:
            return self._close(SegmentEnd.MAX_DURATION)
        return None

    def flush(self) -> SpeechSegment | None:
        """Fecha o que estiver aberto — usado quando o loop precisa do enunciado
        agora (fim de sessão, troca de estado)."""
        if not self._speaking:
            self.reset()
            return None
        return self._close(SegmentEnd.FLUSH)

    def _remember(self, chunk: AudioChunk, duration: float) -> None:
        self._pre_roll.append(chunk)
        self._pre_roll_seconds += duration
        limit = self._settings.pre_roll_ms / 1000
        while (
            self._pre_roll and self._pre_roll_seconds - self._pre_roll[0].duration_seconds >= limit
        ):
            self._pre_roll_seconds -= self._pre_roll.popleft().duration_seconds

    def _start(self, chunk: AudioChunk, duration: float) -> None:
        self._speaking = True
        self._voiced = [*self._pre_roll, chunk]
        self._voiced_seconds = self._pre_roll_seconds + duration
        self._speech_seconds = duration
        self._silence_seconds = 0.0
        self._pre_roll.clear()
        self._pre_roll_seconds = 0.0

    def _close(self, reason: SegmentEnd) -> SpeechSegment | None:
        chunks = self._voiced
        speech_seconds = self._speech_seconds
        self.reset()

        if not chunks or speech_seconds * 1000 + _TOLERANCE < self._settings.min_speech_ms:
            return None

        first, last = chunks[0], chunks[-1]
        return SpeechSegment(
            clip=concat(chunks),
            started_at=first.captured_at,
            ended_at=last.captured_at,
            reason=reason,
            speech_seconds=speech_seconds,
        )
