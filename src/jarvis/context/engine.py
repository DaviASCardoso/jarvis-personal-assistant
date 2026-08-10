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
from jarvis.context.model import CurrentContext, iter_fields
from jarvis.context.ports import ContextSnapshotRepository
from jarvis.context.projection import ContextConflict
from jarvis.context.snapshot import ContextSnapshot, new_snapshot_id

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ContextEngine:
    def __init__(
        self,
        *,
        aggregator: ContextAggregator,
        snapshots: ContextSnapshotRepository,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_snapshot_id,
    ) -> None:
        self._aggregator = aggregator
        self._snapshots = snapshots
        self._clock = clock
        self._new_id = new_id

    def refresh(self) -> tuple[ContextConflict, ...]:
        return self._aggregator.refresh()

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
