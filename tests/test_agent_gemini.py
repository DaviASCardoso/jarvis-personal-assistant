"""`GeminiLLMProvider`: corpo da requisição, parsing e tradução de erro.

Nenhum teste aqui toca a rede: o transporte é injetado (`Opener`). É por isso
que o adapter recebe um `opener` — sem essa costura, testar o mapeamento de erro
exigiria um servidor ou `monkeypatch` global de `urlopen`.
"""

import json
import urllib.error
from typing import Any

import pytest

from jarvis.agent.adapters.gemini import DEFAULT_GEMINI_MODEL, GeminiLLMProvider
from jarvis.agent.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestRejectedError,
    LLMTimeoutError,
)
from jarvis.agent.messages import LLMRequest, Message, ResponseFormat, Role, StopReason
from tests.agent_doubles import failing_opener, fake_opener, gemini_body, http_error

API_KEY = "chave-de-teste-nunca-logar"


def request(*, response_format: ResponseFormat = ResponseFormat.JSON_OBJECT) -> LLMRequest:
    return LLMRequest(
        system="instrução de sistema",
        messages=(
            Message(role=Role.USER, content="primeira"),
            Message(role=Role.ASSISTANT, content="resposta"),
            Message(role=Role.USER, content="segunda"),
        ),
        response_format=response_format,
        temperature=0.3,
        max_output_tokens=256,
        timeout_seconds=12.0,
    )


def provider(opener: Any) -> GeminiLLMProvider:
    return GeminiLLMProvider(api_key=API_KEY, model="gemini-test", opener=opener)


def sent(opener: Any) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(opener.captured[0].data)
    return body


# --- requisição --------------------------------------------------------------


def test_an_empty_api_key_is_refused_at_construction() -> None:
    with pytest.raises(LLMAuthenticationError):
        GeminiLLMProvider(api_key="   ")


def test_the_credential_travels_in_a_header_never_in_the_url() -> None:
    """Uma URL com segredo vaza em log de exceção, proxy e histórico — e
    `HTTPError` imprime a URL por padrão."""
    opener = fake_opener()

    provider(opener).generate(request())

    http_request = opener.captured[0]
    assert http_request.get_header("X-goog-api-key") == API_KEY
    assert API_KEY not in http_request.full_url


def test_the_url_targets_the_configured_model() -> None:
    opener = fake_opener()

    provider(opener).generate(request())

    assert opener.captured[0].full_url.endswith("/models/gemini-test:generateContent")


def test_the_system_instruction_is_not_mixed_into_the_dialogue() -> None:
    opener = fake_opener()

    provider(opener).generate(request())

    body = sent(opener)
    assert body["systemInstruction"]["parts"][0]["text"] == "instrução de sistema"
    assert [content["parts"][0]["text"] for content in body["contents"]] == [
        "primeira",
        "resposta",
        "segunda",
    ]


def test_the_assistant_role_is_translated_to_the_vendor_name() -> None:
    opener = fake_opener()

    provider(opener).generate(request())

    assert [content["role"] for content in sent(opener)["contents"]] == ["user", "model", "user"]


def test_generation_parameters_are_translated() -> None:
    opener = fake_opener()

    provider(opener).generate(request())

    generation = sent(opener)["generationConfig"]
    assert generation["temperature"] == 0.3
    assert generation["maxOutputTokens"] == 256
    assert generation["responseMimeType"] == "application/json"


def test_a_text_request_does_not_ask_for_json() -> None:
    opener = fake_opener()

    provider(opener).generate(request(response_format=ResponseFormat.TEXT))

    assert "responseMimeType" not in sent(opener)["generationConfig"]


def test_the_request_timeout_reaches_the_transport() -> None:
    seen: list[float] = []

    def opener(http_request: Any, timeout: float) -> bytes:
        seen.append(timeout)
        return gemini_body()

    provider(opener).generate(request())

    assert seen == [12.0]


def test_the_default_model_is_configuration_not_contract() -> None:
    """O catálogo do provider muda mais rápido que este repositório."""
    assert GeminiLLMProvider(api_key=API_KEY).model.name == DEFAULT_GEMINI_MODEL


# --- parsing da resposta -----------------------------------------------------


def test_a_normal_response_is_parsed_whole() -> None:
    opener = fake_opener(gemini_body(text='{"type": "ignore", "reason": "nada"}'))

    response = provider(opener).generate(request())

    assert response.text == '{"type": "ignore", "reason": "nada"}'
    assert response.stop_reason is StopReason.COMPLETE
    assert response.usage.input_tokens == 120
    assert response.usage.output_tokens == 15
    assert response.model.vendor == "google"


def test_multiple_parts_are_concatenated() -> None:
    body = json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": "par"}, {"text": "tido"}]}, "finishReason": "STOP"}
            ]
        }
    ).encode()

    assert provider(fake_opener(body)).generate(request()).text == "partido"


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("STOP", StopReason.COMPLETE),
        ("MAX_TOKENS", StopReason.MAX_TOKENS),
        ("SAFETY", StopReason.BLOCKED),
        ("RECITATION", StopReason.BLOCKED),
        ("ALGO_NOVO", StopReason.OTHER),
    ],
)
def test_finish_reasons_are_translated(finish_reason: str, expected: StopReason) -> None:
    opener = fake_opener(gemini_body(text="conteúdo", finish_reason=finish_reason))

    assert provider(opener).generate(request()).stop_reason is expected


def test_missing_usage_becomes_absent_rather_than_zero() -> None:
    body = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
    ).encode()

    usage = provider(fake_opener(body)).generate(request()).usage

    assert (usage.input_tokens, usage.output_tokens) == (None, None)


def test_a_blocked_prompt_produces_a_blocked_response_not_an_error() -> None:
    """Sem candidato **e** com motivo de bloqueio é um desfecho conhecido; quem
    decide o que fazer com ele é o runtime."""
    body = json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode()

    response = provider(fake_opener(body)).generate(request())

    assert response.stop_reason is StopReason.BLOCKED
    assert response.text == ""


# --- tradução de erro --------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, LLMRateLimitError),
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (400, LLMRequestRejectedError),
        (404, LLMRequestRejectedError),
        (500, LLMProviderError),
        (503, LLMProviderError),
    ],
)
def test_http_statuses_become_internal_errors(status: int, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        provider(failing_opener(http_error(status))).generate(request())


def test_rate_limit_carries_the_requested_wait() -> None:
    with pytest.raises(LLMRateLimitError) as error:
        provider(failing_opener(http_error(429, retry_after="7"))).generate(request())

    assert error.value.retry_after == 7.0


def test_a_non_numeric_retry_after_is_ignored_rather_than_crashing() -> None:
    with pytest.raises(LLMRateLimitError) as error:
        provider(
            failing_opener(http_error(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT"))
        ).generate(request())

    assert error.value.retry_after is None


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (401, False), (400, False)],
)
def test_retryability_is_declared_by_the_error_itself(status: int, retryable: bool) -> None:
    """Contracts §13: quem decide se insiste consulta a classificação, não
    reinventa um critério próprio."""
    with pytest.raises(LLMProviderError) as error:
        provider(failing_opener(http_error(status))).generate(request())

    assert error.value.retryable is retryable


def test_a_socket_timeout_becomes_a_timeout_error() -> None:
    with pytest.raises(LLMTimeoutError):
        provider(failing_opener(TimeoutError("estourou"))).generate(request())


def test_a_url_error_wrapping_a_timeout_becomes_a_timeout_error() -> None:
    error = urllib.error.URLError(TimeoutError("estourou"))

    with pytest.raises(LLMTimeoutError):
        provider(failing_opener(error)).generate(request())


def test_a_connection_failure_is_retryable() -> None:
    with pytest.raises(LLMProviderError) as error:
        provider(failing_opener(urllib.error.URLError("conexão recusada"))).generate(request())

    assert error.value.retryable is True
    assert not isinstance(error.value, LLMTimeoutError)


@pytest.mark.parametrize(
    "body",
    [
        b"nao sou json",
        b"[1, 2, 3]",
        json.dumps({"candidates": []}).encode(),
        json.dumps({"algo": "inesperado"}).encode(),
        json.dumps({"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}).encode(),
    ],
)
def test_an_unusable_body_becomes_an_invalid_response(body: bytes) -> None:
    with pytest.raises(LLMInvalidResponseError):
        provider(fake_opener(body)).generate(request())


def test_an_invalid_response_is_not_retryable() -> None:
    """Repetir a mesma chamada tende a produzir o mesmo lixo."""
    with pytest.raises(LLMInvalidResponseError) as error:
        provider(fake_opener(b"nao sou json")).generate(request())

    assert error.value.retryable is False


# --- vazamento ---------------------------------------------------------------


def test_no_error_message_repeats_the_credential_or_the_body() -> None:
    failures: list[Exception] = []
    for opener in (
        failing_opener(http_error(429)),
        failing_opener(http_error(401)),
        failing_opener(http_error(500)),
        failing_opener(TimeoutError()),
        fake_opener(b"corpo secreto com Marina"),
    ):
        with pytest.raises(LLMProviderError) as error:
            provider(opener).generate(request())
        failures.append(error.value)

    for failure in failures:
        assert API_KEY not in str(failure)
        assert "Marina" not in str(failure)
