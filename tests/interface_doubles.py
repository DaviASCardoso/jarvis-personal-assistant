"""Leitores falsos para o painel.

O `ObservabilityService` recebe funções de leitura já ligadas aos stores pelo
composition root. Nos testes essas funções devolvem dados fixos — nenhum banco é
aberto, o que é exatamente a propriedade que a fronteira do pacote comprou.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.model import ContextUpdate, CurrentContext
from jarvis.context.observation import Observation
from jarvis.errors import InfrastructureError
from jarvis.events.event import Event, JsonValue, RecordedEvent
from jarvis.execution.model import Actor, ExecutionStatus, PendingAction
from jarvis.memory.memory import StoredMemory
from tests.memory_doubles import make_memory

PANEL_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def audit_event(
    event_type: str,
    *,
    execution_id: str = "exec-1",
    payload: dict[str, JsonValue] | None = None,
    source: str = "jarvis-execution",
    correlation_id: str = "corr-1",
    recorded_at: datetime = PANEL_NOW,
) -> RecordedEvent:
    body: dict[str, JsonValue] = {"execution_id": execution_id}
    body.update(payload or {})
    return RecordedEvent(
        event=Event(
            event_id=f"{execution_id}:{event_type}",
            event_type=event_type,
            source=source,
            occurred_at=recorded_at,
            payload=body,
            correlation_id=correlation_id,
        ),
        recorded_at=recorded_at,
    )


def external_event(
    *,
    event_type: str = "email.received",
    payload: dict[str, JsonValue] | None = None,
    recorded_at: datetime = PANEL_NOW,
) -> RecordedEvent:
    """Um evento de fonte externa — o caso que o painel não pode ecoar."""
    return RecordedEvent(
        event=Event(
            event_id="ext-1",
            event_type=event_type,
            source="gmail-watcher",
            occurred_at=recorded_at,
            payload=payload
            or {"subject": "assunto secreto", "body": "corpo confidencial do e-mail"},
        ),
        recorded_at=recorded_at,
    )


def stored_memory(
    *,
    memory_id: str = "mem-1",
    content: str = "prefere café sem açúcar",
    subject: str | None = "cafe",
    importance: float = 0.7,
    confidence: float = 0.86,
) -> StoredMemory:
    return StoredMemory(
        memory=make_memory(
            memory_id=memory_id,
            content=content,
            subject=subject,
            importance=importance,
            confidence=confidence,
        ),
        recorded_at=PANEL_NOW,
        updated_at=PANEL_NOW,
        confidence=confidence,
    )


def pending_action(
    *,
    execution_id: str = "exec-9",
    skill: str = "file.delete",
    status: ExecutionStatus = ExecutionStatus.AWAITING_CONFIRMATION,
) -> PendingAction:
    return PendingAction(
        execution_id=execution_id,
        skill=skill,
        parameters={"path": "relatorio.txt"},
        parameters_fingerprint="fp-1",
        actor=Actor.USER,
        correlation_id="corr-9",
        status=status,
        requested_at=PANEL_NOW,
        updated_at=PANEL_NOW,
    )


def current_context(*, place: str | None = "escritorio") -> CurrentContext:
    aggregator = ContextAggregator(clock=frozen_clock())
    aggregator.apply(
        ContextUpdate(
            utc_offset=Observation(
                value="-03:00", observed_at=PANEL_NOW, source="system-time", confidence=1.0
            ),
            place=None
            if place is None
            else Observation(value=place, observed_at=PANEL_NOW, source="device", confidence=0.9),
        )
    )
    return aggregator.get_current_context()


@dataclass
class FakeReaders:
    """As quatro leituras que o serviço recebe injetadas."""

    events: Sequence[RecordedEvent] = ()
    context: CurrentContext | None = None
    memories: Sequence[StoredMemory] = ()
    pending: Sequence[PendingAction] = ()
    failing: frozenset[str] = field(default_factory=frozenset)

    def read_events(self, limit: int) -> Sequence[RecordedEvent]:
        self._maybe_fail("events")
        return list(self.events)[:limit]

    def read_context(self) -> CurrentContext:
        self._maybe_fail("context")
        return self.context if self.context is not None else CurrentContext(as_of=PANEL_NOW)

    def read_memories(self, limit: int) -> Sequence[StoredMemory]:
        self._maybe_fail("memory")
        return list(self.memories)[:limit]

    def read_pending(self) -> Sequence[PendingAction]:
        self._maybe_fail("actions")
        return list(self.pending)

    def _maybe_fail(self, what: str) -> None:
        if what in self.failing:
            raise InfrastructureError(f"banco de {what} indisponível")


def frozen_clock(moment: datetime = PANEL_NOW) -> Callable[[], datetime]:
    return lambda: moment
