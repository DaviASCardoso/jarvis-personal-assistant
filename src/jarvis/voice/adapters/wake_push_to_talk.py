"""Wake word por tecla: o default.

Custo zero, latência zero, determinístico, e — o que mais importa — **nenhum
áudio sai do dispositivo antes de o usuário pedir**. É por isso que este é o modo
padrão, e não o detector por transcrição
([ADR-0021](../../../../docs/adr/0021-wake-word-without-local-ai.md)).

Satisfaz `WakeWordDetector` estruturalmente: `feed` ignora o áudio e consulta um
gatilho externo. A assimetria é honesta — este detector não escuta, ele espera.
"""

import logging
import sys
import threading
from collections.abc import Callable
from typing import Final, TextIO

from jarvis.voice.audio import AudioChunk
from jarvis.voice.ports import WakeWordDetection

logger = logging.getLogger(__name__)

DETECTOR_NAME: Final = "push-to-talk"


class StdinTrigger:
    """Uma thread lendo a entrada padrão; qualquer linha arma o gatilho.

    Thread daemon de propósito: se o loop principal terminar, o processo não fica
    preso esperando alguém apertar Enter. Ler `stdin` numa thread é o que permite
    que o loop de áudio continue rodando enquanto a pessoa decide falar.
    """

    def __init__(self, *, source: TextIO | None = None) -> None:
        self._source = source if source is not None else sys.stdin
        self._armed = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._read, name="jarvis-push-to-talk", daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            for _ in self._source:
                if self._stopped.is_set():
                    return
                self._armed.set()
        except (OSError, ValueError):  # pragma: no cover - stdin fechado no meio
            logger.debug("voice.push_to_talk_closed")

    def take(self) -> bool:
        """Consome o gatilho, se houver. Nunca bloqueia."""
        if not self._armed.is_set():
            return False
        self._armed.clear()
        return True

    def stop(self) -> None:
        self._stopped.set()
        self._armed.clear()


class PushToTalkWakeWord:
    """Implementa `jarvis.voice.ports.WakeWordDetector`."""

    def __init__(
        self,
        *,
        trigger: Callable[[], bool],
        phrase: str = "push-to-talk",
        stop: Callable[[], None] = lambda: None,
    ) -> None:
        self._trigger = trigger
        self._phrase = phrase
        self._stop = stop

    @property
    def name(self) -> str:
        return DETECTOR_NAME

    def feed(self, chunk: AudioChunk) -> WakeWordDetection | None:
        if not self._trigger():
            return None
        return WakeWordDetection(
            phrase=self._phrase, detected_at=chunk.captured_at, detector=DETECTOR_NAME
        )

    def reset(self) -> None:
        """Consome um gatilho pendente para que a tecla apertada durante a
        resposta não abra outro turno sozinha."""
        self._trigger()

    def close(self) -> None:
        self._stop()
