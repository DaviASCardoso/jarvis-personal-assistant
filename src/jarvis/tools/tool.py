"""Contrato de `Tool`: capacidade atômica, stateless, com schema fixo.

[ADR-0005](../../../docs/adr/0005-skill-tool-mcp-distinction.md): uma Tool é "o
que pode ser feito tecnicamente"; risco, permissão e confirmação **não** moram
aqui — moram na Skill. Um `ToolDescriptor` não tem campo de risco, e essa
ausência é deliberada: se tivesse, a primeira Tool a se declarar inofensiva
teria criado um segundo lugar onde autorização parece morar.

`ToolId` é qualificado por backend (`local:fs.read_text`, `workspace:search`).
A qualificação resolve colisão entre servidores por construção — dois MCP Servers
podem expor `search` sem que o registry precise arbitrar.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolInvalidInputError
from jarvis.tools.schema import ParameterSchema

type ToolId = str

MAX_MESSAGE_LENGTH: Final = 2000

_BACKEND = r"[a-z0-9][a-z0-9_-]*"
# O nome aceita maiúsculas e `_` porque não é nosso: um MCP Server externo expõe
# `read_file` ou `getStatus`, e recusar a tool por causa da convenção de nomes
# dele seria rejeitar a integração inteira por estética. O `backend_id`, esse
# sim, é escolhido por nós e continua em minúsculas.
_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"

_BACKEND_PATTERN: Final = re.compile(rf"^{_BACKEND}$")
_NAME_PATTERN: Final = re.compile(rf"^{_NAME}$")
_TOOL_ID_PATTERN: Final = re.compile(rf"^{_BACKEND}:{_NAME}$")


def make_tool_id(*, backend_id: str, name: str) -> ToolId:
    if not _BACKEND_PATTERN.fullmatch(backend_id):
        raise ToolInvalidInputError(f"backend_id inválido: {backend_id!r}")
    if not _NAME_PATTERN.fullmatch(name):
        # O nome vem do servidor externo; ecoá-lo é seguro (é identificador
        # público de capacidade, não conteúdo de usuário) e ajuda a diagnosticar.
        raise ToolInvalidInputError(f"nome de tool inválido: {name!r}")
    return f"{backend_id}:{name}"


def require_tool_id(value: str, *, field_name: str = "tool_id") -> ToolId:
    if not _TOOL_ID_PATTERN.fullmatch(value):
        raise ToolInvalidInputError(f"{field_name} precisa ser 'backend:nome', recebido {value!r}")
    return value


def backend_of(tool_id: ToolId) -> str:
    return require_tool_id(tool_id).split(":", 1)[0]


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDescriptor:
    """O que um backend anuncia sobre uma Tool que expõe."""

    tool_id: ToolId
    backend_id: str
    name: str
    summary: str
    parameters: ParameterSchema = field(default_factory=ParameterSchema)
    supports_idempotency_key: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", require_tool_id(self.tool_id))
        if self.tool_id != f"{self.backend_id}:{self.name}":
            raise ToolInvalidInputError(
                f"tool_id {self.tool_id!r} não corresponde a backend_id/name"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCall:
    """Um pedido de execução técnica, já correlacionado a uma execução de Skill.

    `execution_id` e `correlation_id` são obrigatórios porque um `ToolCall` sem
    eles seria uma chamada anônima — exatamente o que a auditoria da fase existe
    para tornar impossível.
    """

    tool_id: ToolId
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    execution_id: str
    correlation_id: str
    idempotency_key: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_id", require_tool_id(self.tool_id))
        if not self.execution_id.strip():
            raise ToolInvalidInputError("execution_id não pode ser vazio")
        if not self.correlation_id.strip():
            raise ToolInvalidInputError("correlation_id não pode ser vazio")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ToolInvalidInputError("timeout_seconds precisa ser positivo")


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolResult:
    """O resultado de uma Tool que **deu certo**.

    Não existe `ok: bool` aqui de propósito. Falha é exceção da família
    `ToolError`, e não um campo que alguém esquece de checar — o esquecimento é a
    forma mais comum de uma falha virar sucesso silencioso.
    """

    tool_id: ToolId
    backend_id: str
    execution_id: str
    data: Mapping[str, JsonValue] = field(default_factory=dict)
    message: str = ""
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        if len(self.message) > MAX_MESSAGE_LENGTH:
            object.__setattr__(self, "message", f"{self.message[:MAX_MESSAGE_LENGTH]}…")
