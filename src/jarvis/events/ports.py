"""Ports do Event System.

O Event Store é um port porque o domínio não pode conhecer SQL, driver ou schema
(`docs/architecture-contracts.md §11`).
O Event Bus, em contraste, é uma classe concreta do Core (`bus.py`): tem uma única
implementação e nenhuma necessidade de substituição, e um port para ele seria a
"abstração especulativa" que o contrato §1 proíbe.

As operações de leitura aqui são exatamente as exigidas pela Fase 1 — consulta por
tipo, temporal e por `correlation_id` (ROADMAP 1.3), mais o que o CLI usa. Leitura
por offset/cursor é necessidade da Fase 2 e será acrescentada lá.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jarvis.events.event import Event, RecordedEvent


@dataclass(frozen=True, slots=True)
class AppendResult:
    """Resultado de um append.

    `is_duplicate` distingue "gravei agora" de "já existia" sem usar exceção como
    fluxo de controle: reinserir um `event_id` conhecido é no-op por contrato, e
    `event` carrega o registro **original** (com o `recorded_at` da primeira vez).
    """

    event: RecordedEvent
    is_duplicate: bool


class EventStore(Protocol):
    """Registro durável e consultável de eventos.

    Toda leitura devolve os eventos em ordem de persistência ascendente — a
    ordenação estável que o contrato §5 garante aos consumidores do mesmo store.
    Isso não é uma alegação sobre relógio global: causalidade se reconstrói com
    `occurred_at` + `causation_id`/`correlation_id`.
    """

    def append(self, event: Event) -> AppendResult: ...

    def get(self, event_id: str) -> RecordedEvent | None: ...

    def read_by_type(
        self, event_type: str, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]: ...

    def read_by_correlation(self, correlation_id: str) -> Sequence[RecordedEvent]: ...

    def read_occurred_between(
        self, start: datetime, end: datetime, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]:
        """Eventos com `occurred_at` no intervalo semiaberto `[start, end)`.

        Filtra tempo de domínio, não tempo de persistência.
        """
        ...

    def read_latest(self, *, limit: int) -> Sequence[RecordedEvent]: ...


class EventConsumer(Protocol):
    """Componente que reage a eventos publicados no bus.

    Um consumer nunca modifica o evento — só lê e produz efeitos próprios. Retornar
    normalmente é o acknowledgement; levantar exceção é a recusa que dispara retry
    e, esgotadas as tentativas, dead-letter.
    """

    @property
    def name(self) -> str: ...

    def handle(self, event: RecordedEvent) -> None: ...
