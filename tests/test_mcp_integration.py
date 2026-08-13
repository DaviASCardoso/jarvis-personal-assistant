"""MCP de ponta a ponta contra um servidor real — local, determinístico e nosso.

Sobe `tests/mcp_fake_server.py` como subprocesso e fala o protocolo de verdade:
`Popen`, thread leitora, framing por linha, handshake, `tools/list`, `tools/call`
e encerramento. É o que prova que o cliente artesanal funciona fora do laboratório
dos doubles, sem rede, sem credencial e sem instalar nada.

A fixture tem escopo de módulo: iniciar um interpretador Python por teste seria o
tipo de lentidão que faz a suíte deixar de ser rodada.
"""

import sys
from collections.abc import Iterator

import pytest

from jarvis.tools.adapters.mcp_client import McpToolBackend
from jarvis.tools.adapters.mcp_config import McpServerSpec
from jarvis.tools.errors import ToolExecutionError, ToolProtocolError, ToolTimeoutError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.tool import ToolCall

SERVER_SPEC = McpServerSpec(
    server_id="fake",
    command=(sys.executable, "-m", "tests.mcp_fake_server"),
    timeout_seconds=10.0,
    startup_timeout_seconds=15.0,
)


@pytest.fixture(scope="module")
def backend() -> Iterator[McpToolBackend]:
    server = McpToolBackend(SERVER_SPEC)
    try:
        yield server
    finally:
        server.close()


def make_call(name: str, parameters: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_id=f"fake:{name}",
        parameters=parameters or {},  # type: ignore[arg-type]
        execution_id="exec-1",
        correlation_id="corr-1",
    )


def test_discovery_reaches_a_real_process(backend: McpToolBackend) -> None:
    descriptors = {item.name: item for item in backend.discover()}

    assert "echo" in descriptors
    assert descriptors["echo"].tool_id == "fake:echo"
    assert descriptors["echo"].parameters.fields["text"].required is True


def test_a_tool_with_an_exotic_name_survives_discovery(backend: McpToolBackend) -> None:
    names = {item.name for item in backend.discover()}

    assert "Weird-Name" in names
    assert backend.skipped_tools == ()


def test_a_successful_call_returns_structured_data(backend: McpToolBackend) -> None:
    result = backend.invoke(make_call("echo", {"text": "olá"}), timeout_seconds=10.0)

    assert result.data == {"text": "olá", "length": 3}
    assert result.message == "olá"
    assert result.backend_id == "fake"
    assert result.execution_id == "exec-1"


def test_a_logical_failure_becomes_a_structured_error(backend: McpToolBackend) -> None:
    with pytest.raises(ToolExecutionError, match="recusou"):
        backend.invoke(make_call("fail"), timeout_seconds=10.0)


def test_an_unknown_tool_is_refused_by_the_server(backend: McpToolBackend) -> None:
    from jarvis.tools.errors import ToolNotFoundError

    with pytest.raises(ToolNotFoundError):
        backend.invoke(make_call("inexistente"), timeout_seconds=10.0)


def test_a_slow_tool_times_out_without_hanging_the_suite() -> None:
    """Timeout de verdade, com processo de verdade — e curto o bastante para o CI."""
    server = McpToolBackend(SERVER_SPEC)
    try:
        server.discover()
        with pytest.raises(ToolTimeoutError):
            server.invoke(make_call("slow"), timeout_seconds=0.5)
    finally:
        server.close()


def test_a_malformed_response_is_a_protocol_error() -> None:
    server = McpToolBackend(SERVER_SPEC)
    try:
        server.discover()
        with pytest.raises(ToolProtocolError):
            server.invoke(make_call("garbage"), timeout_seconds=10.0)
    finally:
        server.close()


def test_the_registry_can_route_to_a_real_mcp_server() -> None:
    """A cadeia registry → router → MCP, montada como o composition root monta."""
    from jarvis.tools.router import ToolRouter

    server = McpToolBackend(SERVER_SPEC)
    registry = ToolRegistry()
    registry.register_backend(server)
    try:
        statuses = registry.refresh()
        assert statuses[0].available is True

        result = ToolRouter(registry=registry).call(make_call("echo", {"text": "roteado"}))

        assert result.data["text"] == "roteado"
    finally:
        registry.close()


def test_closing_twice_is_safe() -> None:
    server = McpToolBackend(SERVER_SPEC)
    server.discover()

    server.close()
    server.close()
