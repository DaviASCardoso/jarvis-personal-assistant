"""`McpToolBackend`: um MCP Server visto como backend de Tools.

MCP é tratado como **fronteira de integração**, não como sinônimo de Skill
(`PHASE-5.md §12`). O domínio do Jarvis não conhece nenhum servidor específico:
tudo que sobe daqui é `ToolDescriptor` e `ToolResult`, exatamente como o backend
local. Trocar um servidor por outro — ou por um backend que nem seja MCP — não
toca em Skill, Policy ou Router.

Ciclo de vida, tudo preguiçoso:

```text
construir            → nada acontece
discover()/invoke()  → conecta (Popen → initialize → notifications/initialized)
                     → tools/list  |  tools/call
falha de transporte  → encerra o processo e marca desconectado
próxima chamada      → tenta reconectar uma vez
```

Não há laço de reconexão em background: não existe daemon nesta fase para
hospedá-lo, e uma thread que reconecta sozinha seria infraestrutura sem dono.

Sem SDK: `subprocess`, `json`, `threading` e `queue` da biblioteca padrão
([ADR-0015](../../../../docs/adr/0015-stdlib-stdio-mcp-client.md)). O SDK oficial
é async-first, e adotá-lo forçaria asyncio num sistema que é síncrono por decisão
registrada (ADR-0008).
"""

import logging
import os
from collections.abc import Callable, Mapping, Sequence

from jarvis.tools.adapters.mcp_config import McpServerSpec, child_environment
from jarvis.tools.adapters.mcp_protocol import (
    decode_message,
    descriptors_from_tools_list,
    encode_notification,
    encode_request,
    initialize_params,
    is_response_to,
    result_from_call,
    result_of,
)
from jarvis.tools.adapters.mcp_stdio import StdioTransport, Transport
from jarvis.tools.errors import ToolError, ToolProtocolError, ToolUnavailableError
from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolResult

logger = logging.getLogger(__name__)

# Quantas mensagens fora de ordem (notificações, respostas de outro `id`) toleramos
# antes de considerar o fluxo perdido. Um servidor tagarela não deve travar a
# chamada, e um servidor quebrado não deve nos manter lendo para sempre.
MAX_UNRELATED_MESSAGES = 32


class McpToolBackend:
    """Implementação de `ToolBackend` sobre o protocolo MCP."""

    def __init__(
        self,
        spec: McpServerSpec,
        *,
        environ: Mapping[str, str] | None = None,
        transport_factory: Callable[[McpServerSpec], Transport] | None = None,
    ) -> None:
        self._spec = spec
        self._environ = environ if environ is not None else os.environ
        self._transport_factory = (
            transport_factory if transport_factory is not None else self._default_transport
        )
        self._transport: Transport | None = None
        self._next_id = 0
        self._skipped_tools: tuple[str, ...] = ()

    @property
    def backend_id(self) -> str:
        return self._spec.server_id

    @property
    def skipped_tools(self) -> tuple[str, ...]:
        """Nomes que o servidor expõe e que não viram `ToolId` — visível no CLI."""
        return self._skipped_tools

    def _default_transport(self, spec: McpServerSpec) -> Transport:
        return StdioTransport(
            command=spec.command,
            env=child_environment(spec, self._environ),
            cwd=spec.cwd,
            server_id=spec.server_id,
        )

    # ------------------------------------------------------------ lifecycle

    def _connect(self) -> Transport:
        transport = self._transport
        if transport is not None and transport.is_running:
            return transport

        self._shutdown()
        transport = self._transport_factory(self._spec)
        transport.start()
        self._transport = transport
        self._next_id = 0

        try:
            result = self._exchange(
                transport,
                method="initialize",
                params=initialize_params(),
                timeout_seconds=self._spec.startup_timeout_seconds,
            )
            transport.send(encode_notification(method="notifications/initialized", params={}))
        except ToolError:
            self._shutdown()
            raise

        served = result.get("protocolVersion")
        logger.info(
            "mcp.initialized",
            extra={"server_id": self._spec.server_id, "protocol_version": served},
        )
        return transport

    def close(self) -> None:
        self._shutdown()

    def _shutdown(self) -> None:
        transport, self._transport = self._transport, None
        if transport is not None:
            transport.close()

    # -------------------------------------------------------------- chamadas

    def discover(self) -> Sequence[ToolDescriptor]:
        result = self._request("tools/list", {}, timeout_seconds=self._spec.startup_timeout_seconds)
        descriptors, skipped = descriptors_from_tools_list(result, backend_id=self.backend_id)
        self._skipped_tools = skipped
        if skipped:
            logger.warning(
                "mcp.tools_skipped",
                extra={"server_id": self._spec.server_id, "skipped": list(skipped)},
            )
        return descriptors

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        params: dict[str, object] = {
            "name": _tool_name(call.tool_id),
            "arguments": dict(call.parameters),
        }
        if call.idempotency_key is not None:
            # Metadado opcional: servidores que não o conhecem ignoram. A garantia
            # de idempotência real é o `execution_id`, não isto (`PHASE-5.md §19`).
            params["_meta"] = {"idempotencyKey": call.idempotency_key}

        result = self._request("tools/call", params, timeout_seconds=timeout_seconds)
        return result_from_call(
            result,
            tool_id=call.tool_id,
            backend_id=self.backend_id,
            execution_id=call.execution_id,
        )

    def _request(
        self, method: str, params: Mapping[str, object], *, timeout_seconds: float
    ) -> Mapping[str, object]:
        transport = self._connect()
        try:
            return self._exchange(
                transport, method=method, params=params, timeout_seconds=timeout_seconds
            )
        except (ToolUnavailableError, ToolProtocolError):
            # O fluxo se perdeu: derruba o processo para que a próxima chamada
            # comece de um handshake limpo em vez de herdar um estado ambíguo.
            self._shutdown()
            raise

    def _exchange(
        self,
        transport: Transport,
        *,
        method: str,
        params: Mapping[str, object],
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        self._next_id += 1
        request_id = self._next_id
        transport.send(encode_request(request_id=request_id, method=method, params=params))

        for _ in range(MAX_UNRELATED_MESSAGES):
            message = decode_message(transport.receive(timeout_seconds=timeout_seconds))
            if is_response_to(message, request_id=request_id):
                return result_of(message)
            logger.debug(
                "mcp.unrelated_message",
                extra={"server_id": self._spec.server_id, "method": message.get("method")},
            )

        raise ToolProtocolError(
            f"MCP Server {self._spec.server_id} não respondeu a {method} entre "
            f"{MAX_UNRELATED_MESSAGES} mensagens"
        )


def _tool_name(tool_id: str) -> str:
    return tool_id.split(":", 1)[1]
