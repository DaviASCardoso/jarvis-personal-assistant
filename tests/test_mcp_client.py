"""O cliente MCP contra um transporte falso: lifecycle, correlação e falhas.

Sem `subprocess` e sem espera real. O teste de integração com processo de verdade
está em `test_mcp_integration.py`; aqui interessa a lógica do cliente.
"""

import json

import pytest

from jarvis.tools.adapters.mcp_client import MAX_UNRELATED_MESSAGES, McpToolBackend
from jarvis.tools.adapters.mcp_config import McpServerSpec
from jarvis.tools.errors import ToolExecutionError, ToolProtocolError, ToolUnavailableError
from jarvis.tools.tool import ToolCall
from tests.action_doubles import FakeTransport

SPEC = McpServerSpec(server_id="servidor", command=("nao-executado",))


def response(request_id: int, result: dict[str, object]) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def initialize_response() -> str:
    return response(1, {"protocolVersion": "2025-06-18", "capabilities": {}})


def build(responses: list[str | Exception]) -> tuple[McpToolBackend, FakeTransport]:
    transport = FakeTransport(responses)
    backend = McpToolBackend(SPEC, environ={}, transport_factory=lambda spec: transport)
    return backend, transport


def make_call(tool_id: str = "servidor:echo", **changes: object) -> ToolCall:
    fields: dict[str, object] = {
        "tool_id": tool_id,
        "parameters": {"text": "oi"},
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
    }
    fields.update(changes)
    return ToolCall(**fields)  # type: ignore[arg-type]


class TestLifecycle:
    def test_nothing_happens_at_construction(self) -> None:
        _, transport = build([])

        assert transport.started == 0

    def test_the_first_call_performs_the_handshake(self) -> None:
        backend, transport = build([initialize_response(), response(2, {"tools": []})])

        backend.discover()

        assert transport.started == 1
        sent = [json.loads(line) for line in transport.sent]
        assert sent[0]["method"] == "initialize"
        assert sent[1]["method"] == "notifications/initialized"
        assert sent[2]["method"] == "tools/list"

    def test_the_handshake_happens_only_once(self) -> None:
        backend, transport = build(
            [initialize_response(), response(2, {"tools": []}), response(3, {"tools": []})]
        )

        backend.discover()
        backend.discover()

        assert transport.started == 1
        methods = [json.loads(line)["method"] for line in transport.sent]
        assert methods.count("initialize") == 1

    def test_close_shuts_the_transport_down(self) -> None:
        backend, transport = build([initialize_response(), response(2, {"tools": []})])
        backend.discover()

        backend.close()

        assert transport.closed == 1

    def test_a_failed_handshake_does_not_leave_a_process_behind(self) -> None:
        backend, transport = build([ToolUnavailableError("morreu no início")])

        with pytest.raises(ToolUnavailableError):
            backend.discover()

        assert transport.closed == 1

    def test_a_transport_failure_drops_the_connection_and_the_next_call_reconnects(self) -> None:
        transports: list[FakeTransport] = [
            FakeTransport([initialize_response(), ToolUnavailableError("caiu")]),
            FakeTransport([initialize_response(), response(2, {"tools": []})]),
        ]
        backend = McpToolBackend(SPEC, environ={}, transport_factory=lambda spec: transports.pop(0))

        with pytest.raises(ToolUnavailableError):
            backend.discover()
        descriptors = backend.discover()

        assert descriptors == ()
        assert transports == []


class TestDiscovery:
    def test_tools_are_translated_into_descriptors(self) -> None:
        backend, _ = build(
            [
                initialize_response(),
                response(
                    2,
                    {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Ecoa.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            }
                        ]
                    },
                ),
            ]
        )

        descriptors = backend.discover()

        assert descriptors[0].tool_id == "servidor:echo"
        assert descriptors[0].backend_id == "servidor"

    def test_skipped_names_are_reported(self) -> None:
        backend, _ = build(
            [
                initialize_response(),
                response(2, {"tools": [{"name": "com espaço"}, {"name": "ok"}]}),
            ]
        )

        backend.discover()

        assert backend.skipped_tools == ("com espaço",)


class TestInvocation:
    def test_a_call_carries_the_tool_name_without_the_backend_prefix(self) -> None:
        backend, transport = build(
            [
                initialize_response(),
                response(2, {"content": [{"type": "text", "text": "pronto"}]}),
            ]
        )

        result = backend.invoke(make_call(), timeout_seconds=5.0)

        params = json.loads(transport.sent[-1])["params"]
        assert params["name"] == "echo"
        assert params["arguments"] == {"text": "oi"}
        assert result.message == "pronto"

    def test_the_idempotency_key_travels_as_metadata(self) -> None:
        backend, transport = build([initialize_response(), response(2, {"content": []})])

        backend.invoke(make_call(idempotency_key="exec-1:0"), timeout_seconds=5.0)

        params = json.loads(transport.sent[-1])["params"]
        assert params["_meta"] == {"idempotencyKey": "exec-1:0"}

    def test_a_logical_failure_becomes_an_execution_error(self) -> None:
        backend, _ = build(
            [
                initialize_response(),
                response(
                    2,
                    {"content": [{"type": "text", "text": "recusou"}], "isError": True},
                ),
            ]
        )

        with pytest.raises(ToolExecutionError, match="recusou"):
            backend.invoke(make_call(), timeout_seconds=5.0)


class TestCorrelation:
    def test_a_notification_before_the_answer_is_skipped(self) -> None:
        backend, _ = build(
            [
                initialize_response(),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/message"}),
                response(2, {"tools": []}),
            ]
        )

        assert backend.discover() == ()

    def test_a_flood_of_unrelated_messages_ends_the_exchange(self) -> None:
        noise = [json.dumps({"jsonrpc": "2.0", "method": "notifications/message"})]
        backend, _ = build([initialize_response(), *noise * (MAX_UNRELATED_MESSAGES + 1)])

        with pytest.raises(ToolProtocolError, match="não respondeu"):
            backend.discover()

    def test_a_malformed_body_is_a_protocol_error(self) -> None:
        backend, _ = build([initialize_response(), "isto não é json"])

        with pytest.raises(ToolProtocolError):
            backend.discover()


class TestEnvironment:
    def test_only_the_declared_keys_reach_the_child(self) -> None:
        from jarvis.tools.adapters.mcp_config import child_environment

        spec = McpServerSpec(server_id="servidor", command=("x",), env_keys=("MEU_TOKEN",))
        environ = {
            "PATH": "/usr/bin",
            "MEU_TOKEN": "valor-secreto",
            "JARVIS_GEMINI_API_KEY": "nao-deve-vazar",
        }

        child = child_environment(spec, environ)

        assert child == {
            "PATH": "/usr/bin",
            "MEU_TOKEN": "valor-secreto",
            # Acrescentado por nós, não herdado: MCP é UTF-8 no fio.
            "PYTHONIOENCODING": "utf-8",
        }
        assert "JARVIS_GEMINI_API_KEY" not in child

    def test_a_declared_key_that_is_absent_is_simply_not_passed(self) -> None:
        from jarvis.tools.adapters.mcp_config import child_environment

        spec = McpServerSpec(server_id="servidor", command=("x",), env_keys=("AUSENTE",))

        assert "AUSENTE" not in child_environment(spec, {"PATH": "/usr/bin"})
