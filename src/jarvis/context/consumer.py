"""O Context Engine como consumidor do Event System.

Satisfaz `EventConsumer` estruturalmente — nenhum import de adapter, nenhuma
herança. `handle()` roda dentro do dispatch síncrono do bus (ADR-0008), então faz
**apenas** trabalho local: traduz o evento e chama o agregador. Nada de arquivo,
banco ou rede aqui; a persistência de snapshot é do `ContextEngine`, acionada pelo
composition root.

Não existe catch-all: `CONTEXT_EVENT_TYPES` é a lista fechada do que o Context
Engine sabe projetar, e é a mesma usada na assinatura do bus e na reconstrução.
Payload de um tipo assinado que não bate com o esperado é `InvalidContextError`
(permanente): o bus registra e manda para dead-letter na primeira tentativa, sem
retry, porque repetir produziria exatamente o mesmo erro. O evento continua no
Event Store — o fato não se perde.

Três tipos, não dez: é o menor conjunto que demonstra substituição de valor,
ausência observada e idempotência. Agenda, localização, conversa e tarefa
pertencem às fases que trouxerem as fontes correspondentes.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Final

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation, require_label
from jarvis.events.event import Event, RecordedEvent

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION: Final = 1

# O evento afirma o fato; o Context Engine não reinterpreta nem estima.
EVENT_CONFIDENCE: Final = 1.0


def _observed[T](event: Event, value: T) -> Observation[T]:
    return Observation(
        value=value,
        # Tempo de domínio: quando o fato aconteceu, não quando foi registrado.
        observed_at=event.occurred_at,
        source=f"event:{event.event_type}",
        confidence=EVENT_CONFIDENCE,
    )


def _availability_changed(event: Event) -> ContextUpdate:
    label = require_label(event.payload.get("availability"), field_name="payload.availability")
    return ContextUpdate(availability=_observed(event, label))


def _activity_started(event: Event) -> ContextUpdate:
    started: str | None = require_label(
        event.payload.get("activity"), field_name="payload.activity"
    )
    return ContextUpdate(activity=_observed(event, started))


def _activity_ended(event: Event) -> ContextUpdate:
    # Ausência **observada**: alguém afirmou que não há atividade corrente. Isso é
    # diferente de o campo nunca ter sido observado.
    ended: str | None = None
    return ContextUpdate(activity=_observed(event, ended))


_TRANSLATIONS: Final[Mapping[str, Callable[[Event], ContextUpdate]]] = {
    "user.availability_changed": _availability_changed,
    "user.activity_started": _activity_started,
    "user.activity_ended": _activity_ended,
}

CONTEXT_EVENT_TYPES: Final = frozenset(_TRANSLATIONS)


class ContextEventConsumer:
    def __init__(self, aggregator: ContextAggregator, *, name: str = "context") -> None:
        self._aggregator = aggregator
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def handle(self, event: RecordedEvent) -> None:
        fact = event.event

        translate = _TRANSLATIONS.get(fact.event_type)
        if translate is None:
            # O bus filtra por tipo, então isto só acontece em chamada direta ou
            # reconstrução — vale a checagem, não vale um log ruidoso.
            logger.debug("context.event_ignored", extra=_ignored(fact, "unsubscribed_type"))
            return

        if fact.schema_version != SUPPORTED_SCHEMA_VERSION:
            # contracts §5: versão desconhecida é tratada explicitamente, nunca
            # assumida como a mais recente.
            logger.info("context.event_ignored", extra=_ignored(fact, "unsupported_schema_version"))
            return

        update = translate(fact)
        conflicts = self._aggregator.apply(update)

        logger.debug(
            "context.event_applied",
            extra={
                "event_id": fact.event_id,
                "event_type": fact.event_type,
                "correlation_id": fact.correlation_id,
                "causation_id": fact.causation_id,
                "conflicts": len(conflicts),
            },
        )


def _ignored(event: Event, reason: str) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "reason": reason,
    }
