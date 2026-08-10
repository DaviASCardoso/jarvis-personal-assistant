"""O serviço de aplicação que o composition root usa.

Junta o que o agregador sabe com onde as capturas ficam. É aqui, e não no
consumer, que a persistência acontece: `handle()` roda dentro do dispatch síncrono
do bus (ADR-0008), e gravar em disco lá deixaria quem publicou um evento esperando
por I/O.

**Relevância de captura:** uma captura só é persistida se o conteúdo mudou em
relação à última vigente. Sem isso, capturar duas vezes seguidas encheria o
histórico de registros idênticos e tornaria a consulta histórica inútil.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.consumer import CONTEXT_EVENT_TYPES, ContextEventConsumer
from jarvis.context.model import CurrentContext, iter_fields
from jarvis.context.ports import ContextSnapshotRepository
from jarvis.context.projection import ContextConflict
from jarvis.context.snapshot import ContextSnapshot, new_snapshot_id
from jarvis.events.event import RecordedEvent
from jarvis.events.ports import EventStore

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _persistence_order(recorded: RecordedEvent) -> tuple[datetime, datetime, str]:
    """`recorded_at` é a ordem real; os demais só desempatam de forma estável."""
    return recorded.recorded_at, recorded.event.occurred_at, recorded.event.event_id


class ContextEngine:
    def __init__(
        self,
        *,
        aggregator: ContextAggregator,
        snapshots: ContextSnapshotRepository,
        consumer: ContextEventConsumer | None = None,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_snapshot_id,
    ) -> None:
        self._aggregator = aggregator
        self._snapshots = snapshots
        self._consumer = consumer or ContextEventConsumer(aggregator)
        self._clock = clock
        self._new_id = new_id

    @property
    def consumer(self) -> ContextEventConsumer:
        """O que o composition root inscreve no bus, com `CONTEXT_EVENT_TYPES`."""
        return self._consumer

    def refresh(self) -> tuple[ContextConflict, ...]:
        return self._aggregator.refresh()

    def rebuild_from(self, store: EventStore) -> None:
        """Reconstrói a projeção a partir dos eventos já registrados.

        `CurrentContext` é projeção derivada, não fonte de verdade: um processo
        novo (a CLI é de vida curta) nasceria sem nada se não relesse o store.

        A ordem importa — `user.activity_started` seguido de `user.activity_ended`
        só resolve certo na ordem em que os fatos foram registrados. `read_by_type`
        já devolve cada tipo em ordem de persistência; reordenar por `recorded_at`
        recompõe a ordem **entre** tipos, usando apenas o que `RecordedEvent` expõe.

        Limitação conhecida: dois eventos de tipos diferentes com `recorded_at`
        idêntico não são desempatáveis (a coluna `sequence` do adapter não é
        exposta no domínio), e a leitura é integral, sem cursor. Se qualquer uma
        das duas passar a alterar o resultado na prática, a resposta é acrescentar
        leitura ordenada/por cursor ao port `EventStore` naquele momento — com o
        consumidor concreto na mão.
        """
        recorded = [
            item
            for event_type in sorted(CONTEXT_EVENT_TYPES)
            for item in store.read_by_type(event_type)
        ]
        for item in sorted(recorded, key=_persistence_order):
            self._consumer.handle(item)

    def current(self) -> CurrentContext:
        return self._aggregator.get_current_context()

    def capture_snapshot(self) -> ContextSnapshot | None:
        """Persiste a projeção atual; devolve `None` quando nada mudou."""
        context = self.current()
        snapshot = ContextSnapshot(
            snapshot_id=self._new_id(), captured_at=self._clock(), context=context
        )

        previous = self._snapshots.latest()
        if previous is not None and previous.fingerprint() == snapshot.fingerprint():
            logger.debug("context.snapshot_unchanged")
            return None

        self._snapshots.save(snapshot)
        logger.info(
            "context.snapshot_captured",
            extra={
                "snapshot_id": snapshot.snapshot_id,
                "field_count": sum(
                    1 for _, observation in iter_fields(context) if observation is not None
                ),
                "stale_count": sum(
                    1
                    for _, observation in iter_fields(context)
                    if observation is not None and observation.is_stale(context.as_of)
                ),
            },
        )
        return snapshot

    def history(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]:
        return self._snapshots.read_captured_between(
            start, end, limit=limit, include_expired=include_expired
        )

    def expire_before(self, cutoff: datetime) -> int:
        """Expiração é sempre deliberada: nunca há job, timer ou retenção implícita."""
        expired = self._snapshots.expire_before(cutoff)
        logger.warning(
            "context.snapshots_expired",
            extra={"cutoff": cutoff.isoformat(), "expired": expired},
        )
        return expired
