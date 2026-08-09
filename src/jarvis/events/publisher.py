"""Ponto de entrada para registrar um acontecimento no sistema.

Junta as duas responsabilidades separadas do Event System na ordem correta:
**persistir e só então distribuir**. Essa ordem não é detalhe de implementação —
ela garante duas propriedades:

1. nenhum consumer reage a um evento que ainda pode falhar ao ser gravado;
2. a deduplicação do store acontece antes do dispatch, então reobservar o mesmo
   acontecimento não faz nenhum consumer processá-lo duas vezes.

Falha de persistência propaga (o fato não foi registrado). Falha de consumer não
propaga: o fato já é histórico, e quem falhou em reagir a ele é problema do bus
(retry/dead letter), não de quem publicou.
"""

import logging

from jarvis.events.bus import EventBus
from jarvis.events.event import Event
from jarvis.events.ports import AppendResult, EventStore

logger = logging.getLogger(__name__)


class EventPublisher:
    def __init__(self, *, store: EventStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus

    def publish(self, event: Event) -> AppendResult:
        """Registra o evento e, se ele for novo, o distribui aos consumidores."""
        result = self._store.append(event)
        if result.is_duplicate:
            logger.info(
                "event.not_republished",
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "correlation_id": event.correlation_id,
                },
            )
            return result

        self._bus.publish(result.event)
        return result
