"""Monta o `PanelSnapshot` a partir das fontes de verdade.

Recebe **funções de leitura** já ligadas aos stores pelo composition root — o
mesmo desenho de `AgentRuntime(context_reader=...)`. Este módulo não abre banco,
não conhece adapter e não sabe o que é SQLite; um teste arquitetural garante isso
módulo a módulo.

Cada leitura é embrulhada: um banco travado degrada **um painel**, não a sessão
de voz que está acontecendo. O que falhou aparece em `PanelSnapshot.degraded` e é
mostrado na tela — mostrar vazio como se fosse ausência seria mentir sobre o
estado do sistema, que é justamente o que o painel existe para não fazer.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final

from jarvis.context.model import CurrentContext, iter_fields
from jarvis.errors import JarvisError
from jarvis.events.event import JsonValue, RecordedEvent
from jarvis.execution.model import PendingAction
from jarvis.interface.viewmodel import (
    DEFAULT_TOAST_TYPES,
    MAX_MEMORY_CHARS,
    MAX_MESSAGE_CHARS,
    ActionCard,
    ContextRow,
    ConversationEntry,
    DecisionCard,
    MemoryCard,
    PanelSnapshot,
    Toast,
    ToolCard,
    TurnTrace,
    VoiceStatusView,
    entries_of,
    truncate,
)
from jarvis.memory.memory import StoredMemory
from jarvis.voice.session import TurnRole, VoiceSession, VoiceStatus

logger = logging.getLogger(__name__)

#: Mesmas duas ausências que o CLI distingue: "-" é nunca observado, "(nenhum)" é
#: alguém observou que não há.
ABSENT: Final = "-"
OBSERVED_ABSENCE: Final = "(nenhum)"

_ACTION_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "action.requested",
        "policy.evaluated",
        "action.confirmation_requested",
        "action.confirmation_granted",
        "action.confirmation_denied",
        "action.completed",
        "action.failed",
    }
)
_TOOL_EVENTS: Final[frozenset[str]] = frozenset(
    {"tool.execution_completed", "tool.execution_failed"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _text(payload: object) -> str:
    return payload if isinstance(payload, str) else ""


def _number(payload: object) -> float | None:
    return (
        float(payload)
        if isinstance(payload, int | float) and not isinstance(payload, bool)
        else None
    )


class ObservabilityService:
    def __init__(
        self,
        *,
        read_events: Callable[[int], Sequence[RecordedEvent]],
        read_context: Callable[[], CurrentContext],
        read_memories: Callable[[int], Sequence[StoredMemory]],
        read_pending: Callable[[], Sequence[PendingAction]],
        timeline_limit: int = 50,
        memory_limit: int = 10,
        toast_types: frozenset[str] = DEFAULT_TOAST_TYPES,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._read_events = read_events
        self._read_context = read_context
        self._read_memories = read_memories
        self._read_pending = read_pending
        self._timeline_limit = timeline_limit
        self._memory_limit = memory_limit
        self._toast_types = toast_types
        self._clock = clock

    def snapshot(
        self,
        *,
        revision: int = 0,
        voice: VoiceStatus | None = None,
        session: VoiceSession | None = None,
        trace: TurnTrace | None = None,
    ) -> PanelSnapshot:
        degraded: list[str] = []
        # As tuplas vazias são anotadas porque `()` sozinho infere `tuple[()]` e
        # o genérico de `_safe` fecharia no tipo errado.
        no_events: tuple[RecordedEvent, ...] = ()
        no_memories: tuple[StoredMemory, ...] = ()
        no_pending: tuple[PendingAction, ...] = ()

        events = self._safe(
            lambda: tuple(self._read_events(self._timeline_limit)), "events", degraded, no_events
        )
        context = self._safe(self._read_context, "context", degraded, None)
        memories = self._safe(
            lambda: tuple(self._read_memories(self._memory_limit)), "memory", degraded, no_memories
        )
        pending = self._safe(lambda: tuple(self._read_pending()), "actions", degraded, no_pending)

        timeline = entries_of(events)
        return PanelSnapshot(
            revision=revision,
            as_of=self._clock(),
            voice=_voice_view(voice),
            timeline=timeline,
            context=_context_rows(context),
            memories=_memory_cards(memories, trace=trace),
            decisions=_decision_cards(session, trace=trace),
            actions=_action_cards(events, pending),
            tools=_tool_cards(events),
            conversation=_conversation(session),
            toasts=tuple(
                Toast.from_entry(entry)
                for entry in timeline
                if entry.event_type in self._toast_types and entry.severity.value != "info"
            ),
            degraded=tuple(degraded),
        )

    def _safe[T](self, read: Callable[[], T], what: str, degraded: list[str], fallback: T) -> T:
        try:
            return read()
        except JarvisError as error:
            logger.warning(
                "panel.read_failed", extra={"source": what, "error_type": type(error).__name__}
            )
            degraded.append(what)
            return fallback


def _voice_view(status: VoiceStatus | None) -> VoiceStatusView:
    if status is None:
        return VoiceStatusView()
    return VoiceStatusView(
        state=status.state.value,
        session_id=status.session_id,
        detail=status.detail,
        last_transcript=truncate(status.last_transcript, limit=MAX_MESSAGE_CHARS),
        last_reply=truncate(status.last_reply, limit=MAX_MESSAGE_CHARS),
        at=status.at,
    )


def _context_rows(context: CurrentContext | None) -> tuple[ContextRow, ...]:
    if context is None:
        return ()
    rows: list[ContextRow] = []
    for field, observation in iter_fields(context):
        if observation is None:
            rows.append(ContextRow(field=field.value, value=ABSENT))
            continue
        value = observation.value
        rows.append(
            ContextRow(
                field=field.value,
                value=OBSERVED_ABSENCE
                if value is None
                else value.isoformat()
                if isinstance(value, datetime)
                else str(value),
                source=observation.source,
                observed_at=observation.observed_at,
                freshness=observation.freshness(context.as_of).value,
                confidence=observation.confidence,
            )
        )
    return tuple(rows)


def _memory_cards(
    memories: Sequence[StoredMemory], *, trace: TurnTrace | None
) -> tuple[MemoryCard, ...]:
    used = trace.memories if trace is not None else ()
    known = {card.memory_id for card in used}
    stored = tuple(_memory_card(item) for item in memories if item.memory.memory_id not in known)
    return (*used, *stored)


def _memory_card(
    stored: StoredMemory, *, score: float | None = None, used: bool = False
) -> MemoryCard:
    memory = stored.memory
    return MemoryCard(
        memory_id=memory.memory_id,
        type=memory.type.value,
        content=truncate(memory.content, limit=MAX_MEMORY_CHARS),
        subject=memory.subject or "",
        importance=memory.importance,
        confidence=stored.confidence,
        origin=memory.provenance.origin.value,
        reference=memory.provenance.reference or "",
        score=score,
        used_in_turn=used,
    )


def memory_card_of(stored: StoredMemory, *, score: float | None, used: bool) -> MemoryCard:
    """Ponte para o composition root montar `TurnTrace.memories` com o score do
    retrieval — que só existe em tempo de recuperação, nunca armazenado."""
    return _memory_card(stored, score=score, used=used)


def _decision_cards(
    session: VoiceSession | None, *, trace: TurnTrace | None
) -> tuple[DecisionCard, ...]:
    cards: list[DecisionCard] = []
    if trace is not None:
        cards.append(
            DecisionCard(
                decision_type=trace.decision_type,
                decided_at=trace.decided_at,
                reason=trace.reason,
                message=truncate(trace.message, limit=MAX_MESSAGE_CHARS),
                correlation_id=trace.correlation_id,
                consulted_llm=trace.consulted_llm,
                importance=trace.importance,
                memory_count=len(trace.memories),
            )
        )
    if session is not None:
        cards.extend(
            DecisionCard(
                decision_type=turn.decision_type or "notify",
                decided_at=turn.at,
                message=truncate(turn.text, limit=MAX_MESSAGE_CHARS),
                correlation_id=turn.correlation_id,
            )
            for turn in reversed(session.turns)
            if turn.role is TurnRole.ASSISTANT
        )
    return tuple(cards)


def _action_cards(
    events: Sequence[RecordedEvent], pending: Sequence[PendingAction]
) -> tuple[ActionCard, ...]:
    """Agrega a trilha de auditoria por `execution_id`.

    A trilha da Fase 5 já responde "o que foi feito, com qual autorização e com
    qual resultado" — o painel só a lê. Histórico consultável de **decisões** é
    outra coisa, e é a subfase 7.4.
    """
    found: dict[str, dict[str, JsonValue]] = {}
    order: list[str] = []

    for recorded in events:
        event = recorded.event
        if event.event_type not in _ACTION_EVENTS:
            continue
        execution_id = _text(event.payload.get("execution_id"))
        if not execution_id:
            continue
        if execution_id not in found:
            found[execution_id] = {"correlation_id": event.correlation_id or ""}
            order.append(execution_id)
        found[execution_id].update(_action_fields(recorded))

    cards = [
        ActionCard(
            execution_id=execution_id,
            skill=_text(fields.get("skill")),
            status=_text(fields.get("status")),
            actor=_text(fields.get("actor")),
            verdict=_text(fields.get("verdict")),
            rule_id=_text(fields.get("rule_id")),
            reason=_text(fields.get("reason")),
            duration_ms=_number(fields.get("duration_ms")),
            correlation_id=_text(fields.get("correlation_id")),
            at=fields.get("at") if isinstance(fields.get("at"), datetime) else None,  # type: ignore[arg-type]
        )
        for execution_id in reversed(order)
        for fields in [found[execution_id]]
    ]
    known = {card.execution_id for card in cards}
    cards.extend(
        ActionCard(
            execution_id=item.execution_id,
            skill=item.skill,
            status=item.status.value,
            actor=item.actor.value,
            reason=item.reason,
            correlation_id=item.correlation_id,
            at=item.requested_at,
        )
        for item in pending
        if item.execution_id not in known
    )
    return tuple(cards)


def _action_fields(recorded: RecordedEvent) -> dict[str, JsonValue]:
    event = recorded.event
    fields: dict[str, JsonValue] = {"at": recorded.recorded_at}  # type: ignore[dict-item]
    for key in ("skill", "actor", "reason", "rule_id"):
        value = event.payload.get(key)
        if isinstance(value, str) and value:
            fields[key] = value
    if event.event_type == "policy.evaluated":
        fields["verdict"] = _text(event.payload.get("decision"))
    if event.event_type in ("action.completed", "action.failed"):
        fields["status"] = "completed" if event.event_type == "action.completed" else "failed"
        duration = event.payload.get("duration_ms")
        if isinstance(duration, int | float):
            fields["duration_ms"] = duration
    if event.event_type == "action.confirmation_requested":
        fields["status"] = "awaiting_confirmation"
    return fields


def _tool_cards(events: Sequence[RecordedEvent]) -> tuple[ToolCard, ...]:
    cards = [
        ToolCard(
            tool_id=_text(recorded.event.payload.get("tool_id")),
            backend_id=_text(recorded.event.payload.get("backend_id")),
            status="completed"
            if recorded.event.event_type == "tool.execution_completed"
            else "failed",
            duration_ms=_number(recorded.event.payload.get("duration_ms")),
            execution_id=_text(recorded.event.payload.get("execution_id")),
            at=recorded.recorded_at,
        )
        for recorded in events
        if recorded.event.event_type in _TOOL_EVENTS
    ]
    cards.reverse()
    return tuple(cards)


def _conversation(session: VoiceSession | None) -> tuple[ConversationEntry, ...]:
    if session is None:
        return ()
    return tuple(
        ConversationEntry(
            role=turn.role.value,
            text=truncate(turn.text, limit=MAX_MESSAGE_CHARS),
            at=turn.at,
            session_id=session.session_id,
            latency_ms=turn.latency_ms,
        )
        for turn in session.turns
    )
