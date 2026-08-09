"""Event Bus: distribuição de eventos já registrados aos consumidores.

Distribuição e persistência são responsabilidades distintas: o Event Store responde
"o que foi registrado?", o bus responde "quem precisa processar isto?". O bus só
recebe `RecordedEvent`, ou seja, só distribui o que já é durável e já passou pela
deduplicação do store.

O bus é **síncrono e em processo** — ver
[ADR-0008](../../../docs/adr/0008-synchronous-in-process-event-bus.md) para por que
asyncio e broker externo foram descartados nesta fase. Semântica de entrega:

- **ack** — o consumer retorna normalmente;
- **nack** — o consumer levanta exceção, o que dispara a `RetryPolicy`;
- **dead letter** — esgotadas as tentativas, a falha vai para o handler configurado.
"""

import logging
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

from jarvis.events.event import RecordedEvent
from jarvis.events.ports import EventConsumer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Quantas vezes tentar entregar um evento a um consumer que falhou.

    O default é uma tentativa (sem retry): retry só faz sentido para consumers cuja
    falha é plausivelmente transitória, e essa é uma decisão de quem se inscreve.
    """

    max_attempts: int = 1
    delay: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts precisa ser >= 1, recebido {self.max_attempts}")
        if self.delay < 0:
            raise ValueError(f"delay não pode ser negativo, recebido {self.delay}")


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """Um evento que um consumer não conseguiu processar dentro da sua política."""

    event: RecordedEvent
    consumer: str
    attempts: int
    error: Exception


type DeadLetterHandler = Callable[[DeadLetter], None]


def log_dead_letter(dead_letter: DeadLetter) -> None:
    """Handler padrão: registra a falha sem interromper o restante da distribuição."""
    logger.error(
        "event.dead_letter",
        extra={
            "event_id": dead_letter.event.event.event_id,
            "event_type": dead_letter.event.event.event_type,
            "correlation_id": dead_letter.event.event.correlation_id,
            "consumer": dead_letter.consumer,
            "attempts": dead_letter.attempts,
        },
        exc_info=dead_letter.error,
    )


@dataclass(frozen=True, slots=True)
class _Subscription:
    consumer: EventConsumer
    event_types: frozenset[str] | None
    retry: RetryPolicy = field(default_factory=RetryPolicy)

    def accepts(self, event_type: str) -> bool:
        return self.event_types is None or event_type in self.event_types


class EventBus:
    """Entrega síncrona de eventos aos consumidores inscritos.

    Não é um port: existe uma única implementação e nenhuma necessidade de
    substituí-la, então um `Protocol` aqui seria abstração sem consumidor real
    (contrato §1). Sua interface é a API pública desta classe.
    """

    def __init__(
        self,
        *,
        dead_letter_handler: DeadLetterHandler | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._subscriptions: list[_Subscription] = []
        self._dead_letter_handler = dead_letter_handler or log_dead_letter
        self._sleep = sleep

    def subscribe(
        self,
        consumer: EventConsumer,
        *,
        event_types: Collection[str] | None = None,
        retry: RetryPolicy | None = None,
    ) -> None:
        """Registra um consumer, opcionalmente restrito a certos `event_type`.

        `event_types=None` recebe tudo; caso contrário o match é exato.
        """
        self._subscriptions.append(
            _Subscription(
                consumer=consumer,
                event_types=None if event_types is None else frozenset(event_types),
                retry=retry or RetryPolicy(),
            )
        )

    def publish(self, event: RecordedEvent) -> None:
        """Entrega o evento a cada consumer interessado, em ordem de inscrição.

        A falha de um consumer nunca impede os demais nem propaga para quem
        publicou: um evento já registrado é um fato histórico, e não deixa de sê-lo
        porque alguém falhou ao reagir a ele.
        """
        for subscription in self._subscriptions:
            if subscription.accepts(event.event.event_type):
                self._deliver(subscription, event)

    def _deliver(self, subscription: _Subscription, event: RecordedEvent) -> None:
        retry = subscription.retry
        for attempt in range(1, retry.max_attempts + 1):
            try:
                subscription.consumer.handle(event)
            except Exception as error:
                # Não é supressão de falha: o erro é logado com stack trace e, se as
                # tentativas acabarem, roteado explicitamente para o dead letter.
                # `BaseException` continua propagando de propósito.
                self._on_failed_attempt(subscription, event, attempt=attempt, error=error)
                if attempt == retry.max_attempts:
                    self._dead_letter_handler(
                        DeadLetter(
                            event=event,
                            consumer=subscription.consumer.name,
                            attempts=attempt,
                            error=error,
                        )
                    )
                    return
                if retry.delay:
                    self._sleep(retry.delay)
            else:
                return

    def _on_failed_attempt(
        self,
        subscription: _Subscription,
        event: RecordedEvent,
        *,
        attempt: int,
        error: Exception,
    ) -> None:
        logger.warning(
            "event.consumer_failed",
            extra={
                "event_id": event.event.event_id,
                "event_type": event.event.event_type,
                "correlation_id": event.event.correlation_id,
                "consumer": subscription.consumer.name,
                "attempt": attempt,
                "max_attempts": subscription.retry.max_attempts,
            },
            exc_info=error,
        )
