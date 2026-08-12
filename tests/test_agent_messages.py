"""O contrato do port: o que uma `LLMRequest` aceita e o que recusa."""

import pytest

from jarvis.agent.errors import InvalidLLMRequestError
from jarvis.agent.messages import (
    LLMModel,
    LLMRequest,
    LLMResponse,
    Message,
    ResponseFormat,
    Role,
    StopReason,
    TokenUsage,
)


def user(text: str = "oi") -> Message:
    return Message(role=Role.USER, content=text)


def test_a_valid_request_keeps_its_defaults() -> None:
    request = LLMRequest(system="instrução", messages=(user(),))

    assert request.response_format is ResponseFormat.TEXT
    assert request.temperature == 0.2
    assert request.timeout_seconds == 30.0


def test_message_content_cannot_be_blank() -> None:
    with pytest.raises(InvalidLLMRequestError):
        Message(role=Role.USER, content="   ")


def test_system_cannot_be_blank() -> None:
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(system="  ", messages=(user(),))


def test_messages_cannot_be_empty() -> None:
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(system="instrução", messages=())


def test_the_last_message_must_come_from_the_user() -> None:
    """Pedir geração depois da própria fala do modelo não tem semântica
    definida em nenhum provider — é bug de montagem."""
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(
            system="instrução",
            messages=(user(), Message(role=Role.ASSISTANT, content="já respondi")),
        )


@pytest.mark.parametrize("temperature", [-0.1, 2.1, float("nan")])
def test_temperature_outside_the_range_is_refused(temperature: float) -> None:
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(system="instrução", messages=(user(),), temperature=temperature)


@pytest.mark.parametrize("value", [0, -1])
def test_a_non_positive_token_budget_is_refused(value: int) -> None:
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(system="instrução", messages=(user(),), max_output_tokens=value)


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_a_non_positive_timeout_is_refused(value: float) -> None:
    with pytest.raises(InvalidLLMRequestError):
        LLMRequest(system="instrução", messages=(user(),), timeout_seconds=value)


def test_a_request_is_immutable() -> None:
    request = LLMRequest(system="instrução", messages=(user(),))

    with pytest.raises(AttributeError):
        request.temperature = 1.0  # type: ignore[misc]


def test_usage_is_absent_by_default_rather_than_zero() -> None:
    """Zero e "não informado" são coisas diferentes: um provider que não conta
    tokens não gastou zero."""
    response = LLMResponse(
        text="ok", stop_reason=StopReason.COMPLETE, model=LLMModel(vendor="v", name="m")
    )

    assert response.usage == TokenUsage(input_tokens=None, output_tokens=None)


def test_the_model_renders_as_vendor_and_name() -> None:
    assert str(LLMModel(vendor="google", name="gemini-2.0-flash")) == "google/gemini-2.0-flash"
