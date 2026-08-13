"""Camada de Tools: contrato de capacidade técnica, roteamento e backends.

API pública do componente. As implementações concretas de `ToolBackend` ficam em
`jarvis.tools.adapters` e são escolhidas pelo composition root.

A regra que organiza tudo aqui: **uma Tool é o que pode ser feito; não é o que
está autorizado**. Nada neste pacote conhece `jarvis.policy` — o router assume
que quem montou o `ToolCall` já passou pela fronteira de autorização, e o
`ToolAccess` é o que torna essa suposição verdadeira
([ADR-0005](../../../docs/adr/0005-skill-tool-mcp-distinction.md)).

Documentação: [`docs/mcp.md`](../../../docs/mcp.md).
"""

from jarvis.tools.access import ToolAccess
from jarvis.tools.errors import (
    ToolError,
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolNotPermittedError,
    ToolProtocolError,
    ToolTimeoutError,
    ToolUnavailableError,
)
from jarvis.tools.ports import ToolBackend
from jarvis.tools.registry import BackendStatus, ToolRegistry
from jarvis.tools.router import ToolRetryPolicy, ToolRouter
from jarvis.tools.schema import (
    FieldSpec,
    FieldType,
    ParameterSchema,
    from_json_schema,
    parameters_fingerprint,
)
from jarvis.tools.tool import (
    ToolCall,
    ToolDescriptor,
    ToolId,
    ToolResult,
    backend_of,
    make_tool_id,
    require_tool_id,
)

__all__ = [
    "BackendStatus",
    "FieldSpec",
    "FieldType",
    "ParameterSchema",
    "ToolAccess",
    "ToolBackend",
    "ToolCall",
    "ToolDescriptor",
    "ToolError",
    "ToolExecutionError",
    "ToolId",
    "ToolInvalidInputError",
    "ToolNotFoundError",
    "ToolNotPermittedError",
    "ToolProtocolError",
    "ToolRegistry",
    "ToolResult",
    "ToolRetryPolicy",
    "ToolRouter",
    "ToolTimeoutError",
    "ToolUnavailableError",
    "backend_of",
    "from_json_schema",
    "make_tool_id",
    "parameters_fingerprint",
    "require_tool_id",
]
