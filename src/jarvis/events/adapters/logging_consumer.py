"""Consumer que registra no log os eventos observados.

É o consumer básico exigido pela subfase 1.4 e o único desta fase — os consumidores
de verdade (Context Engine à frente) chegam nas fases seguintes. Serve tanto como
implementação de referência do contrato `EventConsumer` quanto como diagnóstico de
"o que passou pelo bus".

Registra apenas metadados. `payload` e `metadata` **nunca** são logados: eventos
podem carregar dados pessoais, e log é o lugar mais fácil de vazá-los
(`PHASE-1.md §20`). Quando a forma do conteúdo importa para diagnóstico, só os nomes
das chaves de primeiro nível são registrados.
"""

import logging

from jarvis.events.event import RecordedEvent

logger = logging.getLogger(__name__)


class LoggingEventConsumer:
    """Anota cada evento recebido no log estruturado."""

    def __init__(self, *, name: str = "logging", level: int = logging.INFO) -> None:
        self._name = name
        self._level = level

    @property
    def name(self) -> str:
        return self._name

    def handle(self, event: RecordedEvent) -> None:
        logger.log(
            self._level,
            "event.observed",
            extra={
                "consumer": self._name,
                "event_id": event.event.event_id,
                "event_type": event.event.event_type,
                "source": event.event.source,
                "schema_version": event.event.schema_version,
                "correlation_id": event.event.correlation_id,
                "causation_id": event.event.causation_id,
                "occurred_at": event.event.occurred_at.isoformat(),
                "recorded_at": event.recorded_at.isoformat(),
                "payload_keys": sorted(event.event.payload),
            },
        )
