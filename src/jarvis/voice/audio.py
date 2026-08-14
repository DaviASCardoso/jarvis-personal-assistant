"""Os tipos de áudio do Core, e a aritmética que opera sobre eles.

Módulo folha: não importa nada de `jarvis` além de `errors`. É de propósito —
tudo aqui é aritmética sobre bytes, e um módulo de áudio que soubesse o que é um
dispositivo já seria um adapter.

**PCM s16le é o único formato do pipeline.** Groq quer 16 bits, o Google devolve
16 bits em `LINEAR16`, e os dispositivos são abertos em 16 bits. Um WAV fora
disso é recusado com erro explícito em vez de convertido em silêncio: conversão
de profundidade é DSP, e DSP escondido é como um pipeline de áudio começa a
mentir sobre o que está ouvindo.

`audioop` resolveria `rms` em uma linha e **não existe mais**: foi removido do
Python 3.13 (PEP 594). A soma de quadrados abaixo é o substituto — determinística
e testável com PCM sintético.
"""

import math
import sys
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from jarvis.voice.errors import InvalidVoiceInputError

#: Único `sample_width` aceito (16 bits com sinal).
SAMPLE_WIDTH: Final = 2

#: Amplitude máxima de uma amostra de 16 bits — o divisor que normaliza o RMS.
FULL_SCALE: Final = 32768.0

#: Teto de um enunciado. Existe para que um VAD mal calibrado não acumule
#: memória indefinidamente nem mande uma hora de áudio para a nuvem.
MAX_CLIP_SECONDS: Final = 60.0

_ARRAY_CODE: Final = "h"


def rms(data: bytes, *, sample_width: int = SAMPLE_WIDTH) -> float:
    """Energia média do bloco, normalizada entre `0.0` e `1.0`.

    Bytes sobrando no fim (bloco cortado no meio de uma amostra) são ignorados em
    vez de derrubar a leitura: um dispositivo pode entregar um frame parcial no
    fechamento do stream, e isso não é motivo para perder o enunciado.
    """
    if sample_width != SAMPLE_WIDTH:
        raise InvalidVoiceInputError(
            f"sample_width precisa ser {SAMPLE_WIDTH}, recebido {sample_width}"
        )
    usable = len(data) - len(data) % SAMPLE_WIDTH
    if usable <= 0:
        return 0.0

    samples = array(_ARRAY_CODE)
    samples.frombytes(data[:usable])
    if sys.byteorder != "little":  # pragma: no cover - CI e desenvolvimento são little-endian
        samples.byteswap()

    total = sum(float(sample) * float(sample) for sample in samples)
    return math.sqrt(total / len(samples)) / FULL_SCALE


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioFormat:
    """Como as amostras estão dispostas nos bytes."""

    sample_rate: int = 16_000
    channels: int = 1
    sample_width: int = SAMPLE_WIDTH

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise InvalidVoiceInputError(
                f"sample_rate precisa ser positivo, recebido {self.sample_rate}"
            )
        if self.channels != 1:
            # Estéreo não melhora reconhecimento e dobraria o que sai do
            # dispositivo. Downmix é DSP, e DSP não entra sem necessidade medida.
            raise InvalidVoiceInputError(
                f"apenas áudio mono é suportado, recebido {self.channels} canais"
            )
        if self.sample_width != SAMPLE_WIDTH:
            raise InvalidVoiceInputError(
                f"apenas PCM de {SAMPLE_WIDTH} bytes é suportado, recebido {self.sample_width}"
            )

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.sample_width

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_bytes

    def duration_of(self, data: bytes) -> float:
        return len(data) / self.bytes_per_second


#: Formato de captura: 16 kHz é o que os modelos de transcrição esperam, e
#: gravar acima disso só aumenta o upload.
CAPTURE_FORMAT: Final = AudioFormat()


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioChunk:
    """Um bloco contínuo de PCM, como saiu do dispositivo."""

    data: bytes
    format: AudioFormat = CAPTURE_FORMAT
    captured_at: datetime

    def __post_init__(self) -> None:
        if self.captured_at.utcoffset() is None:
            raise InvalidVoiceInputError("captured_at precisa ser timezone-aware")
        object.__setattr__(self, "captured_at", self.captured_at.astimezone(UTC))

    @property
    def duration_seconds(self) -> float:
        return self.format.duration_of(self.data)

    @property
    def rms(self) -> float:
        return rms(self.data, sample_width=self.format.sample_width)


@dataclass(frozen=True, slots=True, kw_only=True)
class PcmClip:
    """Um enunciado completo, pronto para transcrever ou reproduzir."""

    data: bytes
    format: AudioFormat = CAPTURE_FORMAT

    def __post_init__(self) -> None:
        if len(self.data) % self.format.frame_bytes:
            raise InvalidVoiceInputError("o áudio não termina em uma fronteira de amostra")
        if self.duration_seconds > MAX_CLIP_SECONDS:
            raise InvalidVoiceInputError(
                f"clip de {self.duration_seconds:.1f}s excede o teto de {MAX_CLIP_SECONDS:.0f}s"
            )

    @property
    def duration_seconds(self) -> float:
        return self.format.duration_of(self.data)

    @property
    def is_empty(self) -> bool:
        return not self.data


def concat(chunks: Sequence[AudioChunk]) -> PcmClip:
    """Junta blocos contíguos num enunciado.

    Formatos divergentes são recusados em vez de reamostrados: dois dispositivos
    diferentes no mesmo enunciado é um bug de wiring, não um caso a tratar.
    """
    if not chunks:
        raise InvalidVoiceInputError("nenhum bloco de áudio para juntar")

    reference = chunks[0].format
    for chunk in chunks:
        if chunk.format != reference:
            raise InvalidVoiceInputError("blocos com formatos diferentes não podem ser juntados")
    return PcmClip(data=b"".join(chunk.data for chunk in chunks), format=reference)


def silence(seconds: float, *, format: AudioFormat = CAPTURE_FORMAT) -> PcmClip:
    """Silêncio digital — usado em teste e como preenchimento de borda."""
    if seconds < 0:
        raise InvalidVoiceInputError(f"duração não pode ser negativa, recebido {seconds}")
    frames = int(seconds * format.sample_rate)
    return PcmClip(data=b"\x00" * (frames * format.frame_bytes), format=format)
