"""O protocolo MCP, testado como função pura: texto entra, estrutura sai.

Nenhum processo é iniciado aqui. É o que permite cobrir resposta malformada,
`id` trocado, objeto `error` e conteúdo não textual sem espera real e sem
depender do sistema operacional.
"""

import json

import pytest

from jarvis.tools.adapters.mcp_protocol import (
    JSONRPC_VERSION,
    PROTOCOL_VERSION,
    decode_message,
    descriptors_from_tools_list,
    encode_notification,
    encode_request,
    initialize_params,
    is_response_to,
    result_from_call,
    result_of,
)
from jarvis.tools.errors import (
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolProtocolError,
)


class TestEncoding:
    def test_a_request_carries_version_id_method_and_params(self) -> None:
        payload = json.loads(encode_request(request_id=7, method="tools/list", params={}))

        assert payload == {
            "jsonrpc": JSONRPC_VERSION,
            "id": 7,
            "method": "tools/list",
            "params": {},
        }

    def test_a_notification_has_no_id(self) -> None:
        payload = json.loads(encode_notification(method="notifications/initialized", params={}))

        assert "id" not in payload

    def test_the_handshake_declares_the_protocol_version_and_the_client(self) -> None:
        params = initialize_params()

        assert params["protocolVersion"] == PROTOCOL_VERSION
        assert params["clientInfo"] == {"name": "jarvis", "version": "0.1"}


class TestDecoding:
    def test_a_valid_object_decodes(self) -> None:
        assert decode_message('{"jsonrpc":"2.0","id":1,"result":{}}')["id"] == 1

    def test_a_non_json_body_is_a_protocol_error(self) -> None:
        with pytest.raises(ToolProtocolError, match="não é JSON"):
            decode_message("isto não é json")

    def test_a_json_array_is_a_protocol_error(self) -> None:
        with pytest.raises(ToolProtocolError, match="objeto"):
            decode_message("[1, 2, 3]")

    def test_an_absurdly_large_body_is_refused(self) -> None:
        with pytest.raises(ToolProtocolError, match="excede"):
            decode_message("x" * 300_000)

    def test_the_error_never_echoes_the_body(self) -> None:
        with pytest.raises(ToolProtocolError) as error:
            decode_message("segredo-do-usuario-que-nao-e-json")

        assert "segredo-do-usuario" not in str(error.value)


class TestCorrelation:
    def test_only_the_matching_id_counts_as_the_response(self) -> None:
        assert is_response_to({"id": 3}, request_id=3)
        assert not is_response_to({"id": 4}, request_id=3)

    def test_a_notification_is_never_the_response(self) -> None:
        assert not is_response_to({"method": "notifications/message"}, request_id=1)


class TestResultExtraction:
    def test_a_result_is_returned(self) -> None:
        assert result_of({"result": {"tools": []}}) == {"tools": []}

    def test_a_message_without_result_or_error_is_a_protocol_error(self) -> None:
        with pytest.raises(ToolProtocolError):
            result_of({"id": 1})

    def test_method_not_found_becomes_tool_not_found(self) -> None:
        with pytest.raises(ToolNotFoundError):
            result_of({"error": {"code": -32601, "message": "sem esse método"}})

    def test_invalid_params_becomes_invalid_input(self) -> None:
        with pytest.raises(ToolInvalidInputError):
            result_of({"error": {"code": -32602, "message": "faltou campo"}})

    def test_any_other_error_becomes_an_execution_error(self) -> None:
        with pytest.raises(ToolExecutionError):
            result_of({"error": {"code": -1, "message": "deu ruim"}})


class TestToolsList:
    def test_a_typical_listing_translates(self) -> None:
        descriptors, skipped = descriptors_from_tools_list(
            {
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Lê um arquivo.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    }
                ]
            },
            backend_id="servidor",
        )

        assert skipped == ()
        assert descriptors[0].tool_id == "servidor:read_file"
        assert descriptors[0].parameters.fields["path"].required is True

    def test_uppercase_and_hyphen_are_accepted(self) -> None:
        """O nome é do servidor, não nosso; recusá-lo perderia a integração."""
        descriptors, skipped = descriptors_from_tools_list(
            {"tools": [{"name": "Weird-Name"}]}, backend_id="servidor"
        )

        assert skipped == ()
        assert descriptors[0].tool_id == "servidor:Weird-Name"

    def test_an_impossible_name_is_skipped_not_fatal(self) -> None:
        descriptors, skipped = descriptors_from_tools_list(
            {"tools": [{"name": "nome com espaço"}, {"name": "ok"}]}, backend_id="servidor"
        )

        assert [item.name for item in descriptors] == ["ok"]
        assert skipped == ("nome com espaço",)

    def test_a_tool_without_a_schema_is_permissive_and_says_so(self) -> None:
        descriptors, _ = descriptors_from_tools_list(
            {"tools": [{"name": "livre"}]}, backend_id="servidor"
        )

        assert descriptors[0].parameters.allow_unknown is True
        assert descriptors[0].parameters.ignored_keywords == ("(sem inputSchema)",)

    def test_a_missing_tools_key_is_a_protocol_error(self) -> None:
        with pytest.raises(ToolProtocolError):
            descriptors_from_tools_list({}, backend_id="servidor")

    def test_the_description_falls_back_to_the_name(self) -> None:
        descriptors, _ = descriptors_from_tools_list(
            {"tools": [{"name": "sem_descricao"}]}, backend_id="servidor"
        )

        assert descriptors[0].summary == "sem_descricao"


class TestToolsCall:
    def test_text_content_becomes_the_message(self) -> None:
        result = result_from_call(
            {"content": [{"type": "text", "text": "pronto"}]},
            tool_id="servidor:echo",
            backend_id="servidor",
            execution_id="exec-1",
        )

        assert result.message == "pronto"
        assert result.data == {"text": "pronto"}

    def test_structured_content_wins_over_text(self) -> None:
        result = result_from_call(
            {
                "content": [{"type": "text", "text": "pronto"}],
                "structuredContent": {"count": 2},
            },
            tool_id="servidor:echo",
            backend_id="servidor",
            execution_id="exec-1",
        )

        assert result.data == {"count": 2}
        assert result.message == "pronto"

    def test_is_error_becomes_an_exception_not_a_flag(self) -> None:
        """Um resultado com flag é um `if` esquecido esperando para acontecer."""
        with pytest.raises(ToolExecutionError, match="recusou"):
            result_from_call(
                {"content": [{"type": "text", "text": "recusou"}], "isError": True},
                tool_id="servidor:fail",
                backend_id="servidor",
                execution_id="exec-1",
            )

    def test_non_textual_content_is_noted_not_carried(self) -> None:
        result = result_from_call(
            {"content": [{"type": "image", "data": "base64gigante"}]},
            tool_id="servidor:foto",
            backend_id="servidor",
            execution_id="exec-1",
        )

        assert "base64gigante" not in result.message
        assert "[conteúdo image omitido]" in result.message

    def test_an_empty_result_is_valid(self) -> None:
        result = result_from_call(
            {}, tool_id="servidor:noop", backend_id="servidor", execution_id="exec-1"
        )

        assert result.message == ""
        assert result.data == {"text": ""}
