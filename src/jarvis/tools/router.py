"""Tool Router: o ponto único por onde toda chamada de Tool passa.

Responsabilidades, na ordem em que acontecem
([`architecture-contracts.md §9`](../../../docs/architecture-contracts.md#9-tool--mcp-boundary)):

1. resolver o `tool_id` no registry;
2. validar os parâmetros contra o schema anunciado — imediatamente antes do
   dispatch, e **independentemente** da validação de negócio que a Skill já fez.
   São concerns diferentes: a Skill valida a regra dela, o router valida o
   contrato técnico que o backend publicou;
3. aplicar o timeout da chamada;
4. executar;
5. normalizar toda falha para a família `ToolError`;
6. registrar a execução — aqui, num lugar só. Skills não implementam log próprio.

O que o router **não** faz: decidir autorização. Ele não importa
`jarvis.policy`, não sabe o que é um `PolicyApproval` e assume que quem montou o
`ToolCall` tinha o direito de fazê-lo. Quem garante isso é o `ToolAccess`, que só
existe depois de uma aprovação consumida.

Retry tem duas condições, e as duas precisam valer: o erro precisa se declarar
`retryable` **e** a execução precisa ter sido declarada idempotente pela Skill.
Um timeout numa operação não-idempotente nunca é repetido — timeout não prova que
a operação não aconteceu do outro lado.
"""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from jarvis.audit import AuditEntry, AuditKind, AuditLog
from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolError, ToolExecutionError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.tool import ToolCall, ToolResult

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolRetryPolicy:
    max_attempts: int = 2
    base_delay: float = 0.2
    backoff: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts precisa ser >= 1, recebido {self.max_attempts}")
        if self.base_delay < 0:
            raise ValueError(f"base_delay não pode ser negativo, recebido {self.base_delay}")

    def delay_before(self, attempt: int) -> float:
        return self.base_delay * (self.backoff ** (attempt - 1))


class ToolRouter:
    """Serviço do Core. Não é port: implementação única."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        audit: AuditLog | None = None,
        default_timeout_seconds: float = 20.0,
        retry: ToolRetryPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._default_timeout = default_timeout_seconds
        self._retry = retry if retry is not None else ToolRetryPolicy()
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep

    def call(self, call: ToolCall, *, idempotent: bool = False, ordinal: int = 0) -> ToolResult:
        descriptor = self._registry.get(call.tool_id)
        backend = self._registry.backend_for(call.tool_id)
        validated = descriptor.parameters.validate(call.parameters)

        prepared = replace(
            call,
            parameters=validated,
            idempotency_key=call.idempotency_key if descriptor.supports_idempotency_key else None,
        )
        timeout = (
            call.timeout_seconds if call.timeout_seconds is not None else self._default_timeout
        )
        attempts = self._retry.max_attempts if idempotent else 1

        for attempt in range(1, attempts + 1):
            started = self._monotonic()
            try:
                result = backend.invoke(prepared, timeout_seconds=timeout)
            except ToolError as error:
                duration_ms = (self._monotonic() - started) * 1000
                self._log_failure(prepared, error, attempt=attempt, duration_ms=duration_ms)
                if error.retryable and attempt < attempts:
                    delay = self._retry.delay_before(attempt)
                    if delay:
                        self._sleep(delay)
                    continue
                # Um evento por chamada, não por tentativa: as tentativas viram o
                # campo `attempts`, e o `event_id` determinístico do adapter
                # continua único por (execução, ordinal).
                self._record(
                    AuditKind.TOOL_FAILED,
                    prepared,
                    ordinal=ordinal,
                    detail={
                        "duration_ms": round(duration_ms, 1),
                        "attempts": attempt,
                        "error_type": type(error).__name__,
                        "retryable": error.retryable,
                    },
                )
                raise
            except Exception as error:
                # Um adapter que deixa escapar exceção nativa tem bug — contracts
                # §13 manda traduzir. O router não deixa esse bug atravessar a
                # fronteira: a Skill vê `ToolExecutionError`, e o stack trace
                # completo fica no log para quem for consertar.
                duration_ms = (self._monotonic() - started) * 1000
                logger.error(
                    "tools.adapter_leaked_exception",
                    extra={
                        "tool_id": prepared.tool_id,
                        "execution_id": prepared.execution_id,
                        "error_type": type(error).__name__,
                    },
                    exc_info=error,
                )
                leaked = ToolExecutionError(
                    f"backend {descriptor.backend_id} falhou de forma não traduzida "
                    f"({type(error).__name__})"
                )
                self._record(
                    AuditKind.TOOL_FAILED,
                    prepared,
                    ordinal=ordinal,
                    detail={
                        "duration_ms": round(duration_ms, 1),
                        "attempts": attempt,
                        "error_type": type(error).__name__,
                        "retryable": False,
                    },
                )
                raise leaked from error

            duration_ms = (self._monotonic() - started) * 1000
            self._on_success(prepared, duration_ms=duration_ms, attempt=attempt, ordinal=ordinal)
            return replace(result, duration_ms=duration_ms)

        # Inalcançável: o laço ou devolve, ou relança na última tentativa.
        raise ToolExecutionError("nenhuma tentativa produziu resultado")

    def _on_success(
        self, call: ToolCall, *, duration_ms: float, attempt: int, ordinal: int
    ) -> None:
        logger.info(
            "tools.call_completed",
            extra={
                "tool_id": call.tool_id,
                "execution_id": call.execution_id,
                "correlation_id": call.correlation_id,
                "attempt": attempt,
                "duration_ms": round(duration_ms, 1),
            },
        )
        self._record(
            AuditKind.TOOL_COMPLETED,
            call,
            ordinal=ordinal,
            detail={"duration_ms": round(duration_ms, 1), "attempt": attempt},
        )

    def _log_failure(
        self, call: ToolCall, error: ToolError, *, attempt: int, duration_ms: float
    ) -> None:
        logger.warning(
            "tools.call_failed",
            extra={
                "tool_id": call.tool_id,
                "execution_id": call.execution_id,
                "correlation_id": call.correlation_id,
                "attempt": attempt,
                "duration_ms": round(duration_ms, 1),
                "error_type": type(error).__name__,
                "retryable": error.retryable,
            },
        )

    def _record(
        self,
        kind: AuditKind,
        call: ToolCall,
        *,
        ordinal: int,
        detail: Mapping[str, JsonValue],
    ) -> None:
        if self._audit is None:
            return
        merged: dict[str, JsonValue] = {
            "tool_id": call.tool_id,
            "backend_id": call.tool_id.split(":", 1)[0],
            **detail,
        }
        self._audit.record(
            AuditEntry(
                kind=kind,
                execution_id=call.execution_id,
                correlation_id=call.correlation_id,
                occurred_at=self._clock(),
                ordinal=ordinal,
                detail=merged,
            )
        )
