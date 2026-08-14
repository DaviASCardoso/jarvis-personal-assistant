"""View models do painel: o que a tela mostra, e nada além.

Todo tipo aqui é **dado plano e imutável**, montado pelo `ObservabilityService` a
partir das fontes de verdade. A página não recebe entidade de domínio, não recebe
`RecordedEvent`, não recebe `StoredMemory` — recebe isto, já serializável.

A regra de privacidade que molda o módulo inteiro (`§20.3` do plano da fase):
**payload de evento não vira texto de tela.** `TimelineEntry.summary` é derivado
do `event_type` e de um punhado de campos de identidade que o próprio Jarvis
escreve; um evento de fonte externa — que pode carregar corpo de e-mail ou trecho
de arquivo — aparece pelo tipo e por mais nada.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from jarvis.events.event import JsonValue, RecordedEvent

MAX_MEMORY_CHARS: Final = 160
MAX_MESSAGE_CHARS: Final = 400

#: Fontes escritas pelo próprio Jarvis. Só delas o painel mostra campos de
#: payload — e mesmo assim, só os da allowlist abaixo.
TRUSTED_SOURCES: Final[frozenset[str]] = frozenset(
    {"jarvis-execution", "jarvis-cli", "jarvis-voice"}
)

#: Campos de identidade e desfecho. Nenhum deles carrega conteúdo do usuário:
#: parâmetros de ação nunca entram em evento (ADR-0017), e transcrição nunca
#: entra em evento (ADR-0025).
SAFE_PAYLOAD_KEYS: Final[tuple[str, ...]] = (
    "skill",
    "decision",
    "status",
    "rule_id",
    "tool_id",
    "backend_id",
    "actor",
    "turn_count",
    "reason",
)


class Severity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"


_SEVERITY_BY_TYPE: Final[Mapping[str, Severity]] = {
    "action.completed": Severity.SUCCESS,
    "action.failed": Severity.DANGER,
    "action.confirmation_requested": Severity.WARNING,
    "action.confirmation_denied": Severity.WARNING,
    "action.confirmation_granted": Severity.SUCCESS,
    "tool.execution_failed": Severity.DANGER,
    "tool.execution_completed": Severity.SUCCESS,
}

#: O que vira toast. Lista **fechada** — o painel renderiza fatos que já existem,
#: e não é um Notification System (esse é a subfase 7.3).
DEFAULT_TOAST_TYPES: Final[frozenset[str]] = frozenset(
    {"action.confirmation_requested", "action.failed", "action.completed", "policy.evaluated"}
)

_TOAST_TITLES: Final[Mapping[str, str]] = {
    "action.confirmation_requested": "Confirmação necessária",
    "action.failed": "Ação falhou",
    "action.completed": "Ação concluída",
    "policy.evaluated": "Ação negada",
}


def truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def safe_summary(recorded: RecordedEvent) -> str:
    """Uma frase sobre o evento, sem repetir o payload de fonte externa."""
    event = recorded.event
    if event.source not in TRUSTED_SOURCES:
        return event.event_type
    parts = [
        f"{key}={event.payload[key]}"
        for key in SAFE_PAYLOAD_KEYS
        if key in event.payload and event.payload[key] not in (None, "")
    ]
    return f"{event.event_type} {' '.join(parts)}".strip()


def severity_of(event_type: str, payload: Mapping[str, JsonValue]) -> Severity:
    if event_type == "policy.evaluated":
        return Severity.DANGER if payload.get("decision") == "deny" else Severity.INFO
    return _SEVERITY_BY_TYPE.get(event_type, Severity.INFO)


@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineEntry:
    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: str
    severity: Severity = Severity.INFO
    summary: str = ""

    @classmethod
    def from_recorded(cls, recorded: RecordedEvent) -> "TimelineEntry":
        event = recorded.event
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            occurred_at=event.occurred_at,
            recorded_at=recorded.recorded_at,
            correlation_id=event.correlation_id or event.event_id,
            severity=severity_of(event.event_type, event.payload),
            summary=safe_summary(recorded),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextRow:
    field: str
    value: str
    source: str = ""
    observed_at: datetime | None = None
    freshness: str = ""
    confidence: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCard:
    memory_id: str
    type: str
    content: str
    subject: str = ""
    importance: float = 0.0
    confidence: float = 0.0
    origin: str = ""
    reference: str = ""
    score: float | None = None
    used_in_turn: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionCard:
    decision_type: str
    decided_at: datetime
    reason: str = ""
    message: str = ""
    correlation_id: str = ""
    consulted_llm: bool = False
    importance: float | None = None
    memory_count: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionCard:
    execution_id: str
    skill: str = ""
    status: str = ""
    actor: str = ""
    verdict: str = ""
    rule_id: str = ""
    reason: str = ""
    duration_ms: float | None = None
    tools_used: tuple[str, ...] = ()
    correlation_id: str = ""
    at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCard:
    tool_id: str
    backend_id: str = ""
    status: str = ""
    duration_ms: float | None = None
    execution_id: str = ""
    at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationEntry:
    role: str
    text: str
    at: datetime
    session_id: str = ""
    latency_ms: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Toast:
    toast_id: str
    severity: Severity
    title: str
    body: str
    at: datetime

    @classmethod
    def from_entry(cls, entry: TimelineEntry) -> "Toast":
        # `toast_id` determinístico: o navegador deduplica sem que o servidor
        # precise guardar o que já mostrou.
        return cls(
            toast_id=entry.event_id,
            severity=entry.severity,
            title=_TOAST_TITLES.get(entry.event_type, entry.event_type),
            body=entry.summary,
            at=entry.recorded_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceStatusView:
    state: str = "idle"
    session_id: str | None = None
    detail: str = ""
    last_transcript: str = ""
    last_reply: str = ""
    at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnTrace:
    """O turno em curso, como o composition root o conhece.

    Existe porque decisões só viram trilha consultável na subfase 7.4: até lá, o
    que o painel mostra sobre "por que" é o turno que acabou de acontecer, e ele
    vive em memória.
    """

    decision_type: str
    decided_at: datetime
    reason: str = ""
    message: str = ""
    correlation_id: str = ""
    consulted_llm: bool = False
    importance: float | None = None
    memories: tuple[MemoryCard, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class PanelSnapshot:
    revision: int
    as_of: datetime
    voice: VoiceStatusView = field(default_factory=VoiceStatusView)
    timeline: tuple[TimelineEntry, ...] = ()
    context: tuple[ContextRow, ...] = ()
    memories: tuple[MemoryCard, ...] = ()
    decisions: tuple[DecisionCard, ...] = ()
    actions: tuple[ActionCard, ...] = ()
    tools: tuple[ToolCard, ...] = ()
    conversation: tuple[ConversationEntry, ...] = ()
    toasts: tuple[Toast, ...] = ()
    #: O que não pôde ser lido nesta passada. A interface é honesta sobre o que
    #: falhou em vez de mostrar vazio como se fosse ausência.
    degraded: tuple[str, ...] = ()


def _moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def to_json_object(snapshot: PanelSnapshot) -> dict[str, object]:
    """Serialização explícita, sem reflexão.

    Escrita à mão de propósito: um `asdict` genérico despejaria qualquer campo
    novo na resposta HTTP, inclusive um que não devesse sair daqui.
    """
    return {
        "revision": snapshot.revision,
        "as_of": snapshot.as_of.isoformat(),
        "voice": {
            "state": snapshot.voice.state,
            "session_id": snapshot.voice.session_id,
            "detail": snapshot.voice.detail,
            "last_transcript": snapshot.voice.last_transcript,
            "last_reply": snapshot.voice.last_reply,
            "at": _moment(snapshot.voice.at),
        },
        "timeline": [
            {
                "event_id": entry.event_id,
                "event_type": entry.event_type,
                "source": entry.source,
                "occurred_at": entry.occurred_at.isoformat(),
                "recorded_at": entry.recorded_at.isoformat(),
                "correlation_id": entry.correlation_id,
                "severity": entry.severity.value,
                "summary": entry.summary,
            }
            for entry in snapshot.timeline
        ],
        "context": [
            {
                "field": row.field,
                "value": row.value,
                "source": row.source,
                "observed_at": _moment(row.observed_at),
                "freshness": row.freshness,
                "confidence": row.confidence,
            }
            for row in snapshot.context
        ],
        "memories": [
            {
                "memory_id": card.memory_id,
                "type": card.type,
                "content": card.content,
                "subject": card.subject,
                "importance": card.importance,
                "confidence": card.confidence,
                "origin": card.origin,
                "reference": card.reference,
                "score": card.score,
                "used_in_turn": card.used_in_turn,
            }
            for card in snapshot.memories
        ],
        "decisions": [
            {
                "decision_type": card.decision_type,
                "decided_at": card.decided_at.isoformat(),
                "reason": card.reason,
                "message": card.message,
                "correlation_id": card.correlation_id,
                "consulted_llm": card.consulted_llm,
                "importance": card.importance,
                "memory_count": card.memory_count,
            }
            for card in snapshot.decisions
        ],
        "actions": [
            {
                "execution_id": card.execution_id,
                "skill": card.skill,
                "status": card.status,
                "actor": card.actor,
                "verdict": card.verdict,
                "rule_id": card.rule_id,
                "reason": card.reason,
                "duration_ms": card.duration_ms,
                "tools_used": list(card.tools_used),
                "correlation_id": card.correlation_id,
                "at": _moment(card.at),
            }
            for card in snapshot.actions
        ],
        "tools": [
            {
                "tool_id": card.tool_id,
                "backend_id": card.backend_id,
                "status": card.status,
                "duration_ms": card.duration_ms,
                "execution_id": card.execution_id,
                "at": _moment(card.at),
            }
            for card in snapshot.tools
        ],
        "conversation": [
            {
                "role": entry.role,
                "text": entry.text,
                "at": entry.at.isoformat(),
                "session_id": entry.session_id,
                "latency_ms": entry.latency_ms,
            }
            for entry in snapshot.conversation
        ],
        "toasts": [
            {
                "toast_id": toast.toast_id,
                "severity": toast.severity.value,
                "title": toast.title,
                "body": toast.body,
                "at": toast.at.isoformat(),
            }
            for toast in snapshot.toasts
        ],
        "degraded": list(snapshot.degraded),
    }


def entries_of(events: Sequence[RecordedEvent]) -> tuple[TimelineEntry, ...]:
    return tuple(TimelineEntry.from_recorded(recorded) for recorded in events)
