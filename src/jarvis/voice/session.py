"""Sessão de voz: identidade, estado e histórico de uma conversa falada.

A subfase 6.4 do [roadmap](../../../ROADMAP.md) pede session id, integração com a
conversa, timeout e controle de estado. As quatro coisas vivem aqui, e nenhuma
delas conhece microfone, rede ou banco.

`VoiceSession` é imutável, como `Conversation` no Agent Runtime: `append` devolve
outra sessão. A diferença entre as duas é o ciclo de vida — a conversa do agente
é efêmera e vive um comando; a sessão de voz é **estado operacional persistido**
com retenção
([ADR-0025](../../../docs/adr/0025-voice-transcripts-as-operational-state.md)).

O que **nunca** entra numa sessão: áudio. Nem bytes, nem caminho de arquivo, nem
duração de gravação. Uma sessão guarda o que foi dito, não o que foi ouvido.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from jarvis.voice.errors import InvalidVoiceInputError, VoiceSessionError


def new_session_id() -> str:
    """Identidade da sessão, que é também seu `correlation_id`.

    `uuid4` local em vez de importar `jarvis.events`: a camada de voz não conhece
    o Event System, e quem publica os eventos de sessão é o composition root.
    """
    return str(uuid.uuid4())


class VoiceState(StrEnum):
    """Onde o loop está. Toda transição é observável pelo painel."""

    IDLE = "idle"
    LISTENING = "listening"
    CAPTURING = "capturing"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    FOLLOW_UP = "follow_up"


class TurnRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceTurn:
    role: TurnRole
    text: str
    at: datetime
    latency_ms: float | None = None
    decision_type: str = ""
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidVoiceInputError("texto de turno não pode ser vazio")
        if self.at.utcoffset() is None:
            raise InvalidVoiceInputError("at precisa ser timezone-aware")
        object.__setattr__(self, "at", self.at.astimezone(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionSettings:
    """Os três limites que fecham uma sessão.

    `follow_up_seconds` é o que dispensa a wake word entre turnos: depois de
    responder, o Jarvis continua ouvindo por alguns segundos. Sem isso, uma
    conversa de cinco turnos exigiria cinco "Jarvis".
    """

    follow_up_seconds: float = 12.0
    idle_timeout_seconds: float = 45.0
    max_turns: int = 40

    def __post_init__(self) -> None:
        if self.follow_up_seconds < 0:
            raise InvalidVoiceInputError("follow_up_seconds não pode ser negativo")
        if self.idle_timeout_seconds <= 0:
            raise InvalidVoiceInputError("idle_timeout_seconds precisa ser positivo")
        if self.max_turns < 1:
            raise InvalidVoiceInputError("max_turns precisa ser >= 1")


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSession:
    session_id: str
    started_at: datetime
    correlation_id: str = ""
    turns: tuple[VoiceTurn, ...] = field(default_factory=tuple)
    ended_at: datetime | None = None
    ended_reason: str = ""

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        if not self.session_id.strip():
            raise InvalidVoiceInputError("session_id não pode ser vazio")
        if self.started_at.utcoffset() is None:
            raise InvalidVoiceInputError("started_at precisa ser timezone-aware")
        overwrite(self, "started_at", self.started_at.astimezone(UTC))
        if not self.correlation_id:
            # A sessão inteira é uma cadeia causal só, e a identidade dela serve
            # de correlação — é o que faz `events list --correlation-id` mostrar
            # a conversa do começo ao fim.
            overwrite(self, "correlation_id", self.session_id)
        if self.ended_at is not None:
            overwrite(self, "ended_at", self.ended_at.astimezone(UTC))

    def append(self, turn: VoiceTurn) -> "VoiceSession":
        if not self.is_open:
            raise VoiceSessionError(f"sessão {self.session_id} já encerrada")
        return VoiceSession(
            session_id=self.session_id,
            started_at=self.started_at,
            correlation_id=self.correlation_id,
            turns=(*self.turns, turn),
            ended_at=None,
            ended_reason="",
        )

    def end(self, *, at: datetime, reason: str) -> "VoiceSession":
        return VoiceSession(
            session_id=self.session_id,
            started_at=self.started_at,
            correlation_id=self.correlation_id,
            turns=self.turns,
            ended_at=at,
            ended_reason=reason,
        )

    def last(self, count: int) -> Sequence[VoiceTurn]:
        if count <= 0:
            return ()
        return self.turns[-count:]

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() * 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceStatus:
    """O estado ao vivo, para quem observa de fora.

    Carrega o último transcrito e a última resposta porque é isso que faz o
    painel útil enquanto a conversa acontece. **Nunca** carrega áudio.
    """

    state: VoiceState
    at: datetime
    session_id: str | None = None
    detail: str = ""
    last_transcript: str = ""
    last_reply: str = ""
