"""Ports da camada de voz.

Sete `Protocol`, e o mais importante deles é o último: `ConversationalAgent` é a
**única** porta entre `jarvis.voice` e o resto do Jarvis. Graças a ele este
pacote não importa `jarvis.agent`, `jarvis.memory`, `jarvis.execution` nem
`jarvis.events` — `tests/test_voice_architecture.py` afirma isso módulo a módulo.

`architecture-contracts.md §3.9` permitiria à Voice Interface conhecer "a
interface conversacional do Agent Runtime" diretamente. Um port próprio é mais
forte e mais barato: o loop inteiro fica testável sem LLM, sem banco e sem rede,
e "a voz não alcança execução" vira uma linha de teste em vez de uma convenção.

O que **não** é port, e por quê: `Segmenter`, `VoiceLoop` e `VoiceSession` têm
implementação única e nenhum substituto real — a mesma assimetria de
`EventBus`/`EventStore` (Fase 1) e `MemoryManager`/`MemoryRepository` (Fase 3).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jarvis.voice.audio import AudioChunk, AudioFormat, PcmClip
from jarvis.voice.session import VoiceSession


@dataclass(frozen=True, slots=True, kw_only=True)
class Transcript:
    text: str
    language: str | None = None
    duration_seconds: float | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackResult:
    played_seconds: float
    interrupted: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class WakeWordDetection:
    """A ativação, e o que mais veio junto dela.

    `remainder` é o que o usuário falou **depois** da frase no mesmo enunciado.
    Sem esse campo, "jarvis, que horas são" exigiria falar duas vezes: uma para
    acordar e outra para perguntar.
    """

    phrase: str
    detected_at: datetime
    detector: str
    transcript: str = ""
    remainder: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentReply:
    """A resposta do Jarvis, na forma que a voz consegue usar.

    **Dado puro, de propósito** — nenhum tipo de `jarvis.agent` aparece aqui.
    `decision_type` é `str` e não `DecisionType` pela mesma razão que
    `ActionResultSummary` é dado puro no Agent Runtime: é o que permite fechar o
    laço sem criar a aresta de import que a arquitetura proíbe.

    `text is None` é **silêncio deliberado** (`Decision.ignore`), não ausência de
    resposta: nada é sintetizado e nada é falado.
    """

    text: str | None = None
    decision_type: str = ""
    correlation_id: str = ""
    awaiting_confirmation: str | None = None
    detail: str = ""


class AudioSource(Protocol):
    """De onde vem o som.

    Contrato que todo adapter precisa cumprir:

    - `read` **nunca** bloqueia além de `timeout_seconds`, e devolve `None`
      quando não houve áudio no intervalo — silêncio não é exceção;
    - traduz toda exceção nativa para `AudioError`/`AudioDeviceError`;
    - `start`/`stop` são idempotentes;
    - o stream permanece aberto durante a reprodução, para que o barge-in tenha
      o que ouvir.
    """

    @property
    def format(self) -> AudioFormat: ...

    def start(self) -> None: ...

    def read(self, *, timeout_seconds: float) -> AudioChunk | None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


class AudioSink(Protocol):
    """Para onde vai o som.

    `play` é síncrono e **cancelável**: consulta `cancelled()` entre blocos e
    retorna assim que ela for verdadeira. É o que torna a interrupção possível
    sem thread extra, sem lock e sem fila.
    """

    @property
    def format(self) -> AudioFormat: ...

    def play(
        self, clip: PcmClip, *, cancelled: Callable[[], bool] = lambda: False
    ) -> PlaybackResult: ...

    def close(self) -> None: ...


class SpeechToText(Protocol):
    """Áudio entra, texto sai.

    Não decide nada, não guarda estado entre chamadas, traduz toda exceção
    nativa para `SpeechToTextError` e respeita `timeout_seconds`.
    """

    @property
    def model(self) -> str: ...

    def transcribe(
        self, clip: PcmClip, *, language: str | None = None, timeout_seconds: float
    ) -> Transcript: ...


class TextToSpeech(Protocol):
    """Texto entra, áudio sai. Mesmas regras do `SpeechToText`."""

    @property
    def voice(self) -> str: ...

    def synthesize(self, text: str, *, timeout_seconds: float) -> PcmClip: ...


class WakeWordDetector(Protocol):
    """Quem decide que o Jarvis foi chamado.

    Modelo **push**: o loop já está lendo do microfone e alimenta o detector.
    Nenhum detector abre dispositivo por conta própria — é o que permite que o
    mesmo stream sirva wake word, captura de enunciado e barge-in ao mesmo
    tempo, sem disputa pelo microfone.
    """

    @property
    def name(self) -> str: ...

    def feed(self, chunk: AudioChunk) -> WakeWordDetection | None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class ConversationalAgent(Protocol):
    """A única porta da camada de voz para o resto do Jarvis.

    Quem implementa é o composition root, e é lá que acontece tudo que este
    pacote não pode conhecer: montar contexto, recuperar memória, chamar o
    `AgentRuntime`, aplicar `Decision.memory`
    ([ADR-0018](../../../docs/adr/0018-memory-writes-outside-the-policy-engine.md))
    e submeter `Decision.action` ao `ActionExecutor`
    ([ADR-0016](../../../docs/adr/0016-action-execution-orchestrator.md)).

    `answer_confirmation` existe porque uma confirmação falada precisa percorrer
    o mesmo caminho da confirmação digitada: publicar o evento e **reavaliar a
    política do zero**
    ([ADR-0014](../../../docs/adr/0014-confirmation-state-and-event-answers.md)).
    """

    def respond(self, text: str, *, session: VoiceSession) -> AgentReply: ...

    def answer_confirmation(
        self, execution_id: str, *, granted: bool, session: VoiceSession
    ) -> AgentReply: ...


class VoiceSessionRepository(Protocol):
    """Persistência de sessões — estado operacional, apagável por retenção."""

    def save(self, session: VoiceSession) -> None: ...

    def get(self, session_id: str) -> VoiceSession | None: ...

    def list(self, *, limit: int) -> Sequence[VoiceSession]: ...

    def purge(self, session_id: str) -> bool: ...

    def purge_before(self, cutoff: datetime) -> int: ...
