"""Doubles do Agent Runtime, com defaults válidos.

Cada double controla exatamente uma variável do teste, no mesmo espírito de
`memory_doubles.py`:

- `StubLLMProvider` — o que o modelo responde, turno a turno;
- `FailingLLMProvider` — qual erro o runtime vê, e por quantas tentativas;
- `fake_opener` — o que a rede devolve ao adapter Gemini, sem rede;
- `make_context` / `make_user_message` / `make_event_trigger` — entradas válidas
  com o mínimo de ruído;
- `decision_json` — uma resposta de modelo bem formada, para não repetir JSON
  literal em cada teste.

Nenhum double aqui chama rede, disco ou relógio real.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from email.message import Message as EmailMessage
from io import BytesIO
from typing import Final

from jarvis.agent.adapters.gemini import Opener
from jarvis.agent.errors import LLMProviderError
from jarvis.agent.input import EventTrigger, UserMessage
from jarvis.agent.messages import (
    LLMModel,
    LLMRequest,
    LLMResponse,
    StopReason,
    TokenUsage,
)
from jarvis.context.model import (
    ActivityContext,
    CurrentContext,
    EnvironmentContext,
    ScheduleContext,
    UserContext,
)
from jarvis.context.observation import Observation
from jarvis.events.event import JsonValue
from jarvis.memory.memory import MemoryType, StoredMemory
from jarvis.memory.ranking import DEFAULT_RANKING_WEIGHTS, RelevanceScore
from jarvis.memory.retrieval import RetrievalResult
from tests.memory_doubles import make_memory

NOON: Final = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
STUB_MODEL: Final = LLMModel(vendor="stub", name="stub-v1")


def make_retrieval_result(
    *,
    total: float = 0.5,
    content: str = "prefere café sem açúcar",
    memory_id: str | None = None,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    subject: str | None = "cafe.acucar",
) -> RetrievalResult:
    """Uma memória já recuperada e pontuada — o formato em que ela chega ao
    agente. Reúsa `make_memory` para não ter duas noções de memória válida."""
    memory = make_memory(memory_id=memory_id, type=memory_type, content=content, subject=subject)
    return RetrievalResult(
        memory=StoredMemory(
            memory=memory, recorded_at=NOON, updated_at=NOON, confidence=memory.confidence
        ),
        score=RelevanceScore(
            total=total,
            semantic=total,
            recency=0.5,
            importance=memory.importance,
            confidence=memory.confidence,
            weights=DEFAULT_RANKING_WEIGHTS,
        ),
    )


def make_context(
    *,
    as_of: datetime = NOON,
    availability: str | None = None,
    activity: str | None = None,
    place: str | None = None,
    next_entry_at: datetime | None = None,
    ttl: timedelta | None = None,
    observed_at: datetime | None = None,
) -> CurrentContext:
    """Contexto com só os campos que o teste precisa; o resto fica ausente —
    ausência é um estado legítimo, não um buraco a preencher."""
    moment = observed_at if observed_at is not None else as_of

    def observe[T](value: T) -> Observation[T]:
        return Observation(value=value, observed_at=moment, source="test-suite", ttl=ttl)

    return CurrentContext(
        as_of=as_of,
        user=UserContext(availability=None if availability is None else observe(availability)),
        environment=EnvironmentContext(place=None if place is None else observe(place)),
        activity=ActivityContext(current=None if activity is None else observe(activity)),
        schedule=ScheduleContext(
            next_entry_at=None if next_entry_at is None else observe(next_entry_at)
        ),
    )


def make_user_message(
    *,
    text: str = "o que você sabe sobre mim?",
    at: datetime = NOON,
    conversation_id: str = "conv-1",
) -> UserMessage:
    return UserMessage(text=text, at=at, conversation_id=conversation_id)


def make_event_trigger(
    *,
    event_id: str = "evt-1",
    event_type: str = "demo.happened",
    source: str = "test-suite",
    occurred_at: datetime = NOON,
    correlation_id: str = "corr-1",
    payload: Mapping[str, JsonValue] | None = None,
) -> EventTrigger:
    return EventTrigger(
        event_id=event_id,
        event_type=event_type,
        source=source,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        payload={"detail": "a impressão terminou"} if payload is None else payload,
    )


def decision_json(
    *,
    type: str = "notify",
    reason: str = "o usuário perguntou algo respondível",
    message: str | None = "tudo certo por aqui",
    memory: Mapping[str, object] | None = None,
    action: Mapping[str, object] | None = None,
    reasoning: str | None = None,
) -> str:
    payload: dict[str, object] = {"type": type, "reason": reason}
    if message is not None:
        payload["message"] = message
    if memory is not None:
        payload["memory"] = memory
    if action is not None:
        payload["action"] = action
    # `act`/`act_and_notify` exigem `reasoning` (Fase 10.1) — default aqui
    # para não obrigar todo teste existente que já monta um `act` a passar
    # o campo explicitamente.
    if reasoning is None and type in ("act", "act_and_notify"):
        reasoning = "avaliei a capacidade disponível e decidi executar"
    if reasoning is not None:
        payload["reasoning"] = reasoning
    return json.dumps(payload, ensure_ascii=False)


class StubLLMProvider:
    """Responde o roteiro, em ordem; repete a última resposta se acabar.

    Guarda cada `LLMRequest` recebida em `requests`, o que faz dele também o
    duplo de gravação — não vale um segundo double só para inspecionar entrada.
    """

    def __init__(
        self,
        responses: Sequence[str | LLMResponse] | None = None,
        *,
        model: LLMModel = STUB_MODEL,
    ) -> None:
        self._responses = list(responses) if responses else [decision_json()]
        self._model = model
        self.requests: list[LLMRequest] = []

    @property
    def model(self) -> LLMModel:
        return self._model

    @property
    def calls(self) -> int:
        return len(self.requests)

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._responses) - 1)
        canned = self._responses[index]
        if isinstance(canned, LLMResponse):
            return canned
        return LLMResponse(
            text=canned,
            stop_reason=StopReason.COMPLETE,
            model=self._model,
            usage=TokenUsage(input_tokens=100, output_tokens=20),
        )


class FailingLLMProvider:
    """Falha `fail_times` vezes e então responde — ou falha sempre, se
    `fail_times` for `None`."""

    def __init__(
        self,
        error: LLMProviderError,
        *,
        fail_times: int | None = None,
        then: str = decision_json(),
        model: LLMModel = STUB_MODEL,
    ) -> None:
        self._error = error
        self._fail_times = fail_times
        self._then = then
        self._model = model
        self.calls = 0

    @property
    def model(self) -> LLMModel:
        return self._model

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self._fail_times is None or self.calls <= self._fail_times:
            raise self._error
        return LLMResponse(text=self._then, stop_reason=StopReason.COMPLETE, model=self._model)


def gemini_body(
    *,
    text: str = '{"type": "ignore", "reason": "nada a fazer"}',
    finish_reason: str = "STOP",
    input_tokens: int = 120,
    output_tokens: int = 15,
) -> bytes:
    return json.dumps(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": text}], "role": "model"},
                    "finishReason": finish_reason,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": input_tokens,
                "candidatesTokenCount": output_tokens,
            },
        }
    ).encode("utf-8")


class RecordingOpener:
    """Transporte que devolve um corpo fixo e guarda o que recebeu.

    Classe, e não closure com atributo anexado, para que `captured` seja um
    campo tipado — é ele que os testes inspecionam para verificar header,
    URL e corpo da requisição.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.captured: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> bytes:
        self.captured.append(request)
        self.timeouts.append(timeout)
        return self._body


def fake_opener(body: bytes | None = None) -> RecordingOpener:
    return RecordingOpener(gemini_body() if body is None else body)


def failing_opener(error: Exception) -> Opener:
    def opener(request: urllib.request.Request, timeout: float) -> bytes:
        raise error

    return opener


def http_error(status: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = EmailMessage()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://example.invalid/v1beta/models/stub:generateContent",
        code=status,
        msg="erro de teste",
        hdrs=headers,
        fp=BytesIO(b"{}"),
    )
