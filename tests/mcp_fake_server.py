"""Um MCP Server mínimo, real e determinístico, para o teste de integração.

Fala o protocolo de verdade sobre stdin/stdout — `initialize`,
`notifications/initialized`, `tools/list`, `tools/call` — e é executado como
subprocesso (`sys.executable -m tests.mcp_fake_server`). Isso exercita o caminho
completo do cliente, inclusive `Popen`, thread leitora, framing por linha e
encerramento, **sem** rede, sem credencial e sem instalar nada.

As tools existem para provocar cada ramo do cliente:

| tool | serve para testar |
|---|---|
| `echo` | caminho feliz e `structuredContent` |
| `fail` | `isError: true` → `ToolExecutionError` |
| `slow` | timeout do lado do cliente |
| `garbage` | resposta que não é JSON → `ToolProtocolError` |
| `Weird-Name` | nome exótico que ainda vira `ToolId` válido |

Roda igual em Windows e Linux: só stdlib, só linhas de texto.
"""

import io
import json
import sys
import time
from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Devolve o texto recebido.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 200}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fail",
        "description": "Sempre falha logicamente.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "slow",
        "description": "Demora mais que qualquer timeout razoável de teste.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "garbage",
        "description": "Responde algo que não é JSON.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "Weird-Name",
        "description": "Nome com maiúsculas e hífen.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _call_tool(request_id: Any, params: dict[str, Any]) -> None:
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if name == "slow":
        time.sleep(30)
        return

    if name == "garbage":
        sys.stdout.write("isto não é json\n")
        sys.stdout.flush()
        return

    if name == "fail":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": "a ferramenta recusou"}],
                    "isError": True,
                },
            }
        )
        return

    if name == "echo":
        text = str(arguments.get("text", ""))
        _write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": {"text": text, "length": len(text)},
                },
            }
        )
        return

    if name == "Weird-Name":
        _write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        )
        return

    _write(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"tool desconhecida: {name}"},
        }
    )


def main() -> int:
    # MCP é UTF-8 no fio. Em Windows o padrão de um processo Python ainda é a
    # codificação do console, e um acento na descrição de uma tool bastaria para
    # produzir bytes que o cliente não consegue decodificar.
    for stream in (sys.stdin, sys.stdout):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")

    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        request_id = message.get("id")

        if method == "initialize":
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "1.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            # Notificação: não tem resposta, por definição.
            continue
        elif method == "tools/list":
            _write({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            _call_tool(request_id, message.get("params") or {})
        elif request_id is not None:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"método desconhecido: {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
