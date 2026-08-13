"""O protocolo MCP, na parte que o Jarvis usa: JSON-RPC 2.0 sobre linhas.

Quatro mensagens, e a lista fecha aí: `initialize`, `notifications/initialized`,
`tools/list`, `tools/call`. Resources e prompts do MCP ficam de fora — não há
consumidor para eles nesta fase, e implementá-los seria abstração especulativa
([ADR-0015](../../../../docs/adr/0015-stdlib-stdio-mcp-client.md)).

Este módulo é puro: transforma texto em estrutura e estrutura em texto, sem tocar
processo nem rede. É o que permite testar a tradução do protocolo — inclusive
resposta malformada, `id` trocado e objeto `error` — sem levantar servidor nenhum.

Toda saída de erro daqui já é da taxonomia `ToolError`: nada de JSON-RPC cru
atravessa a fronteira para a Skill (contracts §9).
"""

import json
from collections.abc import Mapping, Sequence
from typing import Final

from jarvis.events.event import JsonValue
from jarvis.tools.errors import (
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolProtocolError,
)
from jarvis.tools.schema import ParameterSchema, from_json_schema
from jarvis.tools.tool import ToolDescriptor, ToolResult, make_tool_id

JSONRPC_VERSION: Final = "2.0"

# Versão do protocolo que este cliente declara falar. Fixa e explícita: um
# servidor que responda outra coisa precisa aparecer no log, não ser aceito em
# silêncio.
PROTOCOL_VERSION: Final = "2025-06-18"

CLIENT_NAME: Final = "jarvis"
CLIENT_VERSION: Final = "0.1"

MAX_MESSAGE_CHARS: Final = 200_000

# Códigos padronizados do JSON-RPC que têm tradução óbvia na nossa taxonomia.
_METHOD_NOT_FOUND: Final = -32601
_INVALID_PARAMS: Final = -32602


def encode_request(*, request_id: int, method: str, params: Mapping[str, object]) -> str:
    payload = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
        "params": dict(params),
    }
    return json.dumps(payload, ensure_ascii=False)


def encode_notification(*, method: str, params: Mapping[str, object]) -> str:
    payload = {"jsonrpc": JSONRPC_VERSION, "method": method, "params": dict(params)}
    return json.dumps(payload, ensure_ascii=False)


def initialize_params() -> dict[str, object]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
    }


def decode_message(line: str) -> Mapping[str, object]:
    if len(line) > MAX_MESSAGE_CHARS:
        raise ToolProtocolError(f"resposta excede {MAX_MESSAGE_CHARS} caracteres")
    try:
        decoded: object = json.loads(line)
    except json.JSONDecodeError as error:
        # A mensagem não repete o corpo recebido: ele pode conter resultado de
        # tool, que não tem por que aparecer em log.
        raise ToolProtocolError(f"resposta não é JSON válido: {error.msg}") from error
    if not isinstance(decoded, Mapping):
        raise ToolProtocolError("resposta não é um objeto JSON")
    return decoded


def is_response_to(message: Mapping[str, object], *, request_id: int) -> bool:
    """Notificação do servidor (sem `id`) e resposta de outro `id` não servem.

    Não é paranoia: um servidor pode emitir notificações a qualquer momento, e
    tratar a primeira coisa que chegou como "a resposta" é como se lê o resultado
    de uma chamada no lugar de outra.
    """
    return message.get("id") == request_id


def result_of(message: Mapping[str, object]) -> Mapping[str, object]:
    """Extrai `result`, ou traduz `error` para a taxonomia do Core."""
    error = message.get("error")
    if isinstance(error, Mapping):
        raise _translate_error(error)
    result = message.get("result")
    if not isinstance(result, Mapping):
        raise ToolProtocolError("resposta sem 'result' nem 'error'")
    return result


def _translate_error(error: Mapping[str, object]) -> Exception:
    code = error.get("code")
    message = error.get("message")
    detail = message if isinstance(message, str) else "erro sem mensagem"
    if code == _METHOD_NOT_FOUND:
        return ToolNotFoundError(f"o servidor não expõe esse método: {detail}")
    if code == _INVALID_PARAMS:
        return ToolInvalidInputError(f"o servidor recusou os parâmetros: {detail}")
    return ToolExecutionError(f"o servidor devolveu erro ({code}): {detail}")


def descriptors_from_tools_list(
    result: Mapping[str, object], *, backend_id: str
) -> tuple[tuple[ToolDescriptor, ...], tuple[str, ...]]:
    """Traduz `tools/list`. Devolve `(descritores, nomes recusados)`.

    Um nome que não casa com o formato de `ToolId` é **pulado**, não fatal: o
    resto do servidor continua utilizável, e o nome recusado aparece em
    `jarvis tools list`. Derrubar a descoberta inteira por causa de uma tool
    exótica seria trocar uma limitação por uma indisponibilidade.
    """
    raw_tools = result.get("tools")
    if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, str):
        raise ToolProtocolError("tools/list não devolveu uma lista de tools")

    descriptors: list[ToolDescriptor] = []
    skipped: list[str] = []
    for entry in raw_tools:
        if not isinstance(entry, Mapping):
            skipped.append("(entrada não é objeto)")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            skipped.append("(tool sem nome)")
            continue
        try:
            tool_id = make_tool_id(backend_id=backend_id, name=name)
        except ToolInvalidInputError:
            skipped.append(name)
            continue

        raw_schema = entry.get("inputSchema")
        description = entry.get("description")
        descriptors.append(
            ToolDescriptor(
                tool_id=tool_id,
                backend_id=backend_id,
                name=name,
                summary=description if isinstance(description, str) and description else name,
                parameters=(
                    from_json_schema(raw_schema)
                    if isinstance(raw_schema, Mapping)
                    else _permissive()
                ),
            )
        )
    return tuple(descriptors), tuple(skipped)


def _permissive() -> ParameterSchema:
    """Servidor sem `inputSchema`: nada a validar, e dizer o contrário seria mentira."""
    return ParameterSchema(allow_unknown=True, ignored_keywords=("(sem inputSchema)",))


def result_from_call(
    result: Mapping[str, object], *, tool_id: str, backend_id: str, execution_id: str
) -> ToolResult:
    """Normaliza `tools/call` no `ToolResult` do Core.

    `isError: true` é a forma de o próprio MCP dizer que a ferramenta falhou
    logicamente — vira exceção, não um resultado com flag, para que ninguém
    esqueça de checar.
    """
    text = _joined_text(result.get("content"))
    if result.get("isError") is True:
        raise ToolExecutionError(text or "a tool falhou sem mensagem")

    structured = result.get("structuredContent")
    data: dict[str, JsonValue] = (
        _as_json_mapping(structured) if isinstance(structured, Mapping) else {"text": text}
    )
    return ToolResult(
        tool_id=tool_id,
        backend_id=backend_id,
        execution_id=execution_id,
        data=data,
        message=text,
    )


def _joined_text(content: object) -> str:
    """Concatena os blocos textuais. Blocos não textuais são anotados, não trazidos.

    Binário (imagem, áudio) não trafega nesta fase: não há consumidor, e um
    base64 gigante num `ToolResult` acabaria num prompt ou num log.
    """
    if not isinstance(content, Sequence) or isinstance(content, str):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            parts.append(str(block["text"]))
        elif isinstance(kind, str):
            parts.append(f"[conteúdo {kind} omitido]")
    return "\n".join(parts)


def _as_json_mapping(value: Mapping[str, object]) -> dict[str, JsonValue]:
    """Reaproveita a validação de JSON do Event System via round-trip textual.

    O `structuredContent` vem de um servidor externo e pode conter qualquer
    coisa; passar por `json.dumps`/`loads` garante que só tipos JSON entrem no
    `ToolResult`, sem um validador recursivo próprio.
    """
    try:
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False)
        decoded: object = json.loads(rendered)
    except (TypeError, ValueError) as error:
        raise ToolProtocolError("structuredContent não é JSON representável") from error
    if not isinstance(decoded, dict):  # pragma: no cover - a entrada já é Mapping
        raise ToolProtocolError("structuredContent precisa ser um objeto")
    result: dict[str, JsonValue] = decoded
    return result
