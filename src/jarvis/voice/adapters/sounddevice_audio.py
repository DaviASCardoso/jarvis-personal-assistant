"""Microfone e alto-falante via `sounddevice` (PortAudio).

**Único módulo do repositório que importa um pacote de terceiros fora de
`pydantic`** — e ele vive num extra opcional
([ADR-0020](../../../../docs/adr/0020-audio-io-ports-and-optional-backend.md)).
`uv sync --locked` continua não instalando nada novo, e a suíte padrão continua
rodando sem áudio.

Por que `sounddevice` e não `subprocess` chamando `ffmpeg`: as flags de captura
do ffmpeg mudam por sistema operacional (`dshow` no Windows, `avfoundation` no
macOS, `alsa`/`pulse` no Linux). Traduzir isso seria colocar **mais** acoplamento
de plataforma dentro do nosso código, não menos. PortAudio já abstrai o host API.

Duas escolhas que a portabilidade impôs, no mesmo espírito do
[ADR-0015](../../../../docs/adr/0015-stdlib-stdio-mcp-client.md):

1. **`RawInputStream` + `queue`**, não streams com numpy. O callback empurra
   bytes crus para uma fila limitada e volta na hora; `read()` faz
   `Queue.get(timeout=...)` e ganha o timeout de graça. Sem numpy na árvore.
2. **Fila com teto e descarte do mais antigo.** Se o loop travar num POST, a fila
   para de crescer em vez de consumir memória; um bloco velho não tem valor
   nenhum para reconhecimento de fala.
"""

import logging
import queue
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import sounddevice

from jarvis.voice.audio import CAPTURE_FORMAT, AudioChunk, AudioFormat, PcmClip
from jarvis.voice.errors import AudioDeviceError, AudioError
from jarvis.voice.ports import PlaybackResult

logger = logging.getLogger(__name__)

#: 100 ms por bloco: curto o bastante para o VAD reagir e o barge-in parecer
#: instantâneo, longo o bastante para não virar mil chamadas por segundo.
BLOCK_SECONDS: Final = 0.1

#: ~6 s de áudio enfileirado. Além disso, o mais antigo é descartado.
MAX_QUEUED_BLOCKS: Final = 60

_DTYPE: Final = "int16"


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float


def list_devices() -> tuple[AudioDevice, ...]:
    """O que `jarvis voice devices` imprime."""
    try:
        raw: Any = sounddevice.query_devices()
    except Exception as error:
        raise AudioDeviceError("não foi possível consultar os dispositivos de áudio") from error

    devices: list[AudioDevice] = []
    for index, entry in enumerate(raw):
        devices.append(
            AudioDevice(
                index=index,
                name=str(entry.get("name", "")),
                max_input_channels=int(entry.get("max_input_channels", 0)),
                max_output_channels=int(entry.get("max_output_channels", 0)),
                default_sample_rate=float(entry.get("default_samplerate", 0.0)),
            )
        )
    return tuple(devices)


def resolve_device(value: str) -> int | str | None:
    """Aceita índice (`"3"`) ou nome parcial (`"Microfone"`); vazio = padrão do SO."""
    text = value.strip()
    if not text:
        return None
    return int(text) if text.isdigit() else text


class MicrophoneSource:
    """Implementa `jarvis.voice.ports.AudioSource`."""

    def __init__(
        self,
        *,
        audio_format: AudioFormat = CAPTURE_FORMAT,
        device: int | str | None = None,
        block_seconds: float = BLOCK_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._format = audio_format
        self._device = device
        self._block_frames = max(1, int(block_seconds * audio_format.sample_rate))
        self._clock = clock
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=MAX_QUEUED_BLOCKS)
        self._stream: Any = None
        self._dropped = 0

    @property
    def format(self) -> AudioFormat:
        return self._format

    def start(self) -> None:
        if self._stream is not None:
            return
        try:
            self._stream = sounddevice.RawInputStream(
                samplerate=self._format.sample_rate,
                channels=self._format.channels,
                dtype=_DTYPE,
                blocksize=self._block_frames,
                device=self._device,
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as error:
            self._stream = None
            raise AudioDeviceError(
                "não foi possível abrir o microfone; confira JARVIS_VOICE_INPUT_DEVICE"
            ) from error

    def _on_audio(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Roda na thread do PortAudio: copia e volta. Nada de I/O aqui."""
        if status:
            logger.debug("voice.input_status", extra={"status": str(status)})
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            # Um bloco velho não ajuda reconhecimento de fala. Descartar o mais
            # antigo mantém a latência limitada em vez de crescer sem parar.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(bytes(indata))
            except (queue.Empty, queue.Full):  # pragma: no cover - corrida rara
                pass
            self._dropped += 1

    def read(self, *, timeout_seconds: float) -> AudioChunk | None:
        if self._stream is None:
            raise AudioError("o microfone não foi iniciado")
        try:
            data = self._queue.get(timeout=max(timeout_seconds, 0.0))
        except queue.Empty:
            return None
        return AudioChunk(data=data, format=self._format, captured_at=self._clock())

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as error:
            logger.warning("voice.input_close_failed", extra={"error_type": type(error).__name__})
        if self._dropped:
            logger.info("voice.input_blocks_dropped", extra={"dropped": self._dropped})
            self._dropped = 0

    def close(self) -> None:
        self.stop()


class SpeakerSink:
    """Implementa `jarvis.voice.ports.AudioSink`.

    O stream é aberto **por clip**, e não uma vez por sessão: o TTS devolve
    24 kHz e a captura roda a 16 kHz, e abrir na taxa do clip evita reamostrar.
    """

    def __init__(
        self,
        *,
        audio_format: AudioFormat = CAPTURE_FORMAT,
        device: int | str | None = None,
        block_seconds: float = BLOCK_SECONDS,
    ) -> None:
        self._format = audio_format
        self._device = device
        self._block_seconds = block_seconds

    @property
    def format(self) -> AudioFormat:
        return self._format

    def play(
        self, clip: PcmClip, *, cancelled: Callable[[], bool] = lambda: False
    ) -> PlaybackResult:
        if clip.is_empty:
            return PlaybackResult(played_seconds=0.0, interrupted=False)

        block_bytes = max(1, int(self._block_seconds * clip.format.bytes_per_second))
        block_bytes -= block_bytes % clip.format.frame_bytes
        written = 0

        try:
            stream = sounddevice.RawOutputStream(
                samplerate=clip.format.sample_rate,
                channels=clip.format.channels,
                dtype=_DTYPE,
                device=self._device,
            )
        except Exception as error:
            raise AudioDeviceError(
                "não foi possível abrir o alto-falante; confira JARVIS_VOICE_OUTPUT_DEVICE"
            ) from error

        try:
            stream.start()
            for offset in range(0, len(clip.data), block_bytes):
                if cancelled():
                    # A interrupção acontece **entre** blocos: sem thread extra,
                    # sem lock, sem fila. É o que torna barge-in barato.
                    return PlaybackResult(
                        played_seconds=written / clip.format.bytes_per_second, interrupted=True
                    )
                block = clip.data[offset : offset + block_bytes]
                stream.write(block)
                written += len(block)
        except Exception as error:
            raise AudioError("falha ao reproduzir o áudio") from error
        finally:
            try:
                stream.stop()
                stream.close()
            except Exception as error:
                logger.warning(
                    "voice.output_close_failed", extra={"error_type": type(error).__name__}
                )

        return PlaybackResult(played_seconds=clip.duration_seconds, interrupted=False)

    def close(self) -> None:
        """Nada a fechar: o stream vive dentro de `play`."""
