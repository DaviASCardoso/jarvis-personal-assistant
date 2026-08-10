"""Doubles do Context Engine, com defaults válidos.

Ficam em `tests/` de propósito: um adapter de "valor declarado" em `src/` daria a
impressão de que Activity, Calendar e Location já têm integração — e não têm. O
que existe de verdade é o port, e é o `StubProvider` que prova que ele aceita
essas fontes.

Cada double controla exatamente uma variável do teste:

- `StubProvider` — quais observações entram e com que `observed_at`;
- `FailingProvider` — qual exceção o agregador vê (traduzida ou não);
- `FakeSnapshotRepository` — o histórico, em memória;
- `SpyRepository` — só registra chamadas, para provar ausência de I/O;
- `frozen_clock` — a passagem do tempo, única forma de testar `fresh → stale`.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation
from jarvis.context.snapshot import ContextSnapshot

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


class FakeSnapshotRepository:
    """Histórico em memória, com a mesma expiração lógica do repositório real."""

    def __init__(self) -> None:
        self.saved: list[ContextSnapshot] = []
        self.expired: set[str] = set()

    def save(self, snapshot: ContextSnapshot) -> None:
        self.saved.append(snapshot)

    def latest(self) -> ContextSnapshot | None:
        alive = [item for item in self.saved if item.snapshot_id not in self.expired]
        return alive[-1] if alive else None

    def read_captured_between(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]:
        found = [
            item
            for item in self.saved
            if start <= item.captured_at < end
            and (include_expired or item.snapshot_id not in self.expired)
        ]
        return found if limit is None else found[:limit]

    def expire_before(self, cutoff: datetime) -> int:
        newly = {
            item.snapshot_id
            for item in self.saved
            if item.captured_at < cutoff and item.snapshot_id not in self.expired
        }
        self.expired |= newly
        return len(newly)


class SpyRepository(FakeSnapshotRepository):
    """Registra toda chamada, para provar que `handle` não faz I/O."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def save(self, snapshot: ContextSnapshot) -> None:
        self.calls.append("save")
        super().save(snapshot)

    def latest(self) -> ContextSnapshot | None:
        self.calls.append("latest")
        return super().latest()

    def read_captured_between(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]:
        self.calls.append("read_captured_between")
        return super().read_captured_between(
            start, end, limit=limit, include_expired=include_expired
        )

    def expire_before(self, cutoff: datetime) -> int:
        self.calls.append("expire_before")
        return super().expire_before(cutoff)
