"""`ToolAccess`: o router visto por uma Skill — recortado, e só depois de aprovado.

Uma Skill **não** recebe o `ToolRouter`. Recebe isto: um objeto amarrado a uma
execução específica, limitado às Tools que a própria Skill declarou precisar, e
que só é construído em `jarvis/execution` depois de uma `PolicyApproval` ter sido
consumida com sucesso.

Duas propriedades caem de graça desse desenho, e as duas são testadas:

- **menor privilégio por execução** (`PHASE-5.md §33`) — uma Skill de leitura que
  tentasse chamar uma tool de escrita é recusada aqui, antes do router, mesmo com
  aprovação válida em mãos. Não existe `execute_anything`;
- **não há caminho de bypass** — para chegar ao router, é preciso um `ToolAccess`;
  para ter um `ToolAccess`, é preciso ter passado pelo Policy Engine.

A restrição "só `jarvis/execution` constrói" não é convenção: é um teste
arquitetural que varre a AST de `src/` atrás de construções fora do lugar.
"""

from collections.abc import Mapping

from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolNotPermittedError
from jarvis.tools.router import ToolRouter
from jarvis.tools.tool import ToolCall, ToolId, ToolResult, require_tool_id


class ToolAccess:
    def __init__(
        self,
        *,
        router: ToolRouter,
        execution_id: str,
        correlation_id: str,
        allowed: frozenset[ToolId],
        idempotent: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        self._router = router
        self._execution_id = execution_id
        self._correlation_id = correlation_id
        self._allowed = frozenset(require_tool_id(item) for item in allowed)
        self._idempotent = idempotent
        self._timeout_seconds = timeout_seconds
        self._used: list[ToolId] = []

    @property
    def used(self) -> tuple[ToolId, ...]:
        """As Tools efetivamente chamadas, na ordem. Vai para a auditoria."""
        return tuple(self._used)

    @property
    def allowed(self) -> frozenset[ToolId]:
        return self._allowed

    def call(
        self,
        tool_id: ToolId,
        parameters: Mapping[str, JsonValue] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        """Chama uma Tool do conjunto permitido.

        `idempotency_key` é derivada da execução quando não informada: a mesma
        execução, repetindo a mesma posição de chamada, produz a mesma chave — o
        que dá a backends que a suportam uma segunda linha de defesa contra
        duplicação (`PHASE-5.md §19`).
        """
        tool_id = require_tool_id(tool_id)
        if tool_id not in self._allowed:
            raise ToolNotPermittedError(
                f"{tool_id} está fora das ferramentas declaradas por esta skill"
            )

        ordinal = len(self._used)
        self._used.append(tool_id)
        call = ToolCall(
            tool_id=tool_id,
            parameters=parameters if parameters is not None else {},
            execution_id=self._execution_id,
            correlation_id=self._correlation_id,
            idempotency_key=(
                idempotency_key
                if idempotency_key is not None
                else f"{self._execution_id}:{ordinal}"
            ),
            timeout_seconds=self._timeout_seconds,
        )
        return self._router.call(call, idempotent=self._idempotent, ordinal=ordinal)
