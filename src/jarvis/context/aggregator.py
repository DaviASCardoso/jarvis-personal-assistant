"""O agregador: coleta dos providers, merge por campo e leitura da projeção.

Divisão de trabalho deliberada:

- `refresh()` faz I/O (pergunta aos providers) e é sempre acionado explicitamente
  pelo composition root — **nunca** pelo Event Bus, cujo dispatch é síncrono e não
  pode ficar preso a um poll (ADR-0008);
- `get_current_context()` não faz I/O nem poll: só devolve o que já se sabe,
  datado com `as_of`.

Política de falha de provider, explícita porque `PHASE-2.md §8` exige que ela seja:
`ContextProviderError` **degrada** (o provider é pulado, os valores já conhecidos
permanecem e envelhecem normalmente); qualquer outra exceção **propaga**. Um adapter
que deixa escapar exceção nativa tem bug, e bug não vira degradação silenciosa —
por isso não existe `except Exception` aqui.
"""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from jarvis.context.errors import ContextProviderError
from jarvis.context.freshness import DEFAULT_TTL_POLICY, TtlPolicy
from jarvis.context.model import ContextUpdate, CurrentContext
from jarvis.context.ports import ContextProvider
from jarvis.context.projection import ContextConflict, ContextProjection

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ContextAggregator:
    def __init__(
        self,
        *,
        providers: Sequence[ContextProvider] = (),
        clock: Callable[[], datetime] = _utc_now,
        policy: TtlPolicy = DEFAULT_TTL_POLICY,
    ) -> None:
        self._providers = tuple(providers)
        self._clock = clock
        self._projection = ContextProjection(policy=policy)

    def refresh(self) -> tuple[ContextConflict, ...]:
        """Pergunta a cada provider, na ordem de registro, e combina o que voltar."""
        now = self._clock()
        conflicts: list[ContextConflict] = []

        for provider in self._providers:
            try:
                update = provider.observe(now)
            except ContextProviderError as error:
                logger.warning(
                    "context.provider_failed",
                    extra={"provider": provider.name, "error_type": type(error).__name__},
                )
                continue
            conflicts.extend(self._projection.apply(update))

        return tuple(conflicts)

    def apply(self, update: ContextUpdate) -> tuple[ContextConflict, ...]:
        """Incorpora uma observação vinda de fora dos providers (ex. de um evento)."""
        return self._projection.apply(update)

    def get_current_context(self) -> CurrentContext:
        return self._projection.snapshot_of(as_of=self._clock())
