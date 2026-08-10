"""Doubles do Context Engine, com defaults válidos.

Ficam em `tests/` de propósito: um adapter de "valor declarado" em `src/` daria a
impressão de que Activity, Calendar e Location já têm integração — e não têm. O
que existe de verdade é o port, e é o `StubProvider` que prova que ele aceita
essas fontes.

Cada double controla exatamente uma variável do teste:

- `StubProvider` — quais observações entram e com que `observed_at`;
- `FailingProvider` — qual exceção o agregador vê (traduzida ou não);
- `frozen_clock` — a passagem do tempo, única forma de testar `fresh → stale`.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation

DEFAULT_OBSERVED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def make_observation[T](
    value: T,
    *,
    observed_at: datetime = DEFAULT_OBSERVED_AT,
    source: str = "provider:test",
    confidence: float = 1.0,
    ttl: timedelta | None = None,
) -> Observation[T]:
    return Observation(
        value=value,
        observed_at=observed_at,
        source=source,
        confidence=confidence,
        ttl=ttl,
    )


def frozen_clock(*moments: datetime) -> Callable[[], datetime]:
    """Relógio que devolve cada instante uma vez e repete o último para sempre."""
    remaining = list(moments)

    def clock() -> datetime:
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0]

    return clock


class StubProvider:
    """Provider que devolve um `ContextUpdate` fixo e registra os `now` recebidos."""

    def __init__(self, update: ContextUpdate, *, name: str = "stub") -> None:
        self._name = name
        self._update = update
        self.observed_with: list[datetime] = []

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        self.observed_with.append(now)
        return self._update


class FailingProvider:
    """Provider que falha sempre, com o erro que o teste escolher."""

    def __init__(self, *, name: str = "failing", error: Exception | None = None) -> None:
        self._name = name
        self._error = error or ContextProviderError("fonte indisponível")

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        raise self._error
