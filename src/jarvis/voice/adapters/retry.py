"""Repetição de transporte para os providers de voz.

Existe aqui, e não importada de `jarvis.agent.runtime`, por uma razão de
fronteira: `jarvis.voice` não conhece `jarvis.agent`, e reusar quinze linhas
custaria a aresta de import que a fase inteira existe para evitar. É o mesmo
cálculo que `skills/skill.py` já fez ao duplicar o padrão de nome de Skill.

A política consulta `retryable` da própria taxonomia de erro
(`architecture-contracts.md §13`) em vez de enumerar tipos: um erro novo entra
classificado, não listado.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.errors import ProviderError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetryPolicy:
    """Duas tentativas por default: insistir num serviço fora do ar não melhora a
    transcrição e gasta a quota que resta."""

    max_attempts: int = 2
    base_delay: float = 0.5
    backoff: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts precisa ser >= 1, recebido {self.max_attempts}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay não pode ser negativo, recebido {self.base_delay}")

    def delay_before(self, attempt: int, *, requested: float | None = None) -> float:
        """`requested` é o `Retry-After` do provider — respeitá-lo é mais barato e
        mais educado que o backoff cego."""
        if requested is not None:
            return max(requested, 0.0)
        return self.base_delay * (self.backoff ** (attempt - 1))


def call_with_retry[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    what: str,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except ProviderError as error:
            if not error.retryable or attempt == policy.max_attempts:
                raise
            requested = getattr(error, "retry_after", None)
            delay = policy.delay_before(
                attempt, requested=requested if isinstance(requested, float) else None
            )
            logger.warning(
                "voice.provider_retry",
                extra={
                    "provider": what,
                    "attempt": attempt,
                    "delay": round(delay, 2),
                    "error_type": type(error).__name__,
                },
            )
            if delay:
                sleep(delay)

    raise AssertionError("inalcançável: o laço devolve ou relança")  # pragma: no cover
