"""`LLMProvider` sobre a API REST do Google Gemini.

Adapter de Infrastructure: é o único módulo do componente que sabe o que é
`contents`, `parts` ou `finishReason`. O Core fala `LLMRequest`/`LLMResponse`.

**Sem SDK de vendor, por decisão registrada em
[ADR-0011](../../../../docs/adr/0011-gemini-rest-llm-adapter.md).** O SDK oficial
traria grpc/protobuf/google-auth para um projeto que tem uma dependência de
runtime; o que este adapter precisa é de um POST JSON e de um parse tolerante.

**A credencial vai no header `x-goog-api-key`, nunca na query string.** A API
aceita `?key=`, mas uma URL com segredo vaza em log de exceção, em proxy e em
histórico de shell — e `HTTPError` imprime a URL por padrão.
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from jarvis.agent.errors import (
    LLMAuthenticationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestRejectedError,
    LLMTimeoutError,
)
from jarvis.agent.messages import (
    LLMModel,
    LLMRequest,
    LLMResponse,
    ResponseFormat,
    Role,
    StopReason,
    TokenUsage,
)

logger = logging.getLogger(__name__)

VENDOR: Final = "google"
API_BASE: Final = "https://generativelanguage.googleapis.com/v1beta/models"

# Modelo do tier gratuito do AI Studio. É default de **configuração**
# (`JARVIS_GEMINI_MODEL`), não constante de contrato: o catálogo do provider muda
# mais rápido que este repositório, e um rename não deve exigir mudança de código.
DEFAULT_GEMINI_MODEL: Final = "gemini-2.0-flash"

# `role` do lado do modelo na API: o Core chama de `assistant`, o Gemini de `model`.
_ROLE_NAMES: Final[Mapping[Role, str]] = {Role.USER: "user", Role.ASSISTANT: "model"}

_STOP_REASONS: Final[Mapping[str, StopReason]] = {
    "STOP": StopReason.COMPLETE,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "SAFETY": StopReason.BLOCKED,
    "RECITATION": StopReason.BLOCKED,
    "PROHIBITED_CONTENT": StopReason.BLOCKED,
    "BLOCKLIST": StopReason.BLOCKED,
    "SPII": StopReason.BLOCKED,
}

# Assinatura do transporte. Existir como parâmetro é o que permite testar o
# adapter inteiro — corpo da requisição, parsing e mapeamento de erro — sem rede.
type Opener = Callable[[urllib.request.Request, float], bytes]


def _urlopen_bytes(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
    return body


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    raw = error.headers.get("Retry-After") if error.headers is not None else None
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        # O header também admite data HTTP. Não vale um parser: a política de
        # retry tem backoff próprio para cair de volta.
        return None


class GeminiLLMProvider:
    """Implementa `jarvis.agent.ports.LLMProvider`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_GEMINI_MODEL,
        opener: Opener = _urlopen_bytes,
    ) -> None:
        if not api_key.strip():
            raise LLMAuthenticationError("credencial do Gemini ausente")
        self._api_key = api_key
        self._model = LLMModel(vendor=VENDOR, name=model)
        self._opener = opener

    @property
    def model(self) -> LLMModel:
        return self._model

    def generate(self, request: LLMRequest) -> LLMResponse:
        body = self._post(self._build_body(request), timeout=request.timeout_seconds)
        return self._parse(body)

    def _build_body(self, request: LLMRequest) -> dict[str, object]:
        generation: dict[str, object] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if request.response_format is ResponseFormat.JSON_OBJECT:
            # Structured output sem enviar schema: a validação autoritativa é do
            # Core de qualquer forma (ADR-0012), e pedir só o mime type funciona
            # em provider que não suporte schema.
            generation["responseMimeType"] = "application/json"

        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [
                {"role": _ROLE_NAMES[message.role], "parts": [{"text": message.content}]}
                for message in request.messages
            ],
            "generationConfig": generation,
        }

    def _post(self, body: Mapping[str, object], *, timeout: float) -> bytes:
        http_request = urllib.request.Request(
            url=f"{API_BASE}/{self._model.name}:generateContent",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )

        try:
            return self._opener(http_request, timeout)
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from error
        except TimeoutError as error:
            raise LLMTimeoutError(f"{self._model} não respondeu em {timeout}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise LLMTimeoutError(f"{self._model} não respondeu em {timeout}s") from error
            raise LLMProviderError(f"falha de conexão com {self._model}") from error
        except OSError as error:
            raise LLMProviderError(f"falha de transporte com {self._model}") from error

    def _http_error(self, error: urllib.error.HTTPError) -> LLMProviderError:
        # Nenhum ramo repete o corpo da resposta: ela ecoa o prompt em vários
        # provedores, e o prompt carrega contexto e memória do usuário.
        logger.warning(
            "agent.llm_http_error",
            extra={"model": str(self._model), "status": error.code},
        )
        if error.code == 429:
            return LLMRateLimitError(
                f"limite de requisições de {self._model} atingido",
                retry_after=_retry_after(error),
            )
        if error.code in (401, 403):
            return LLMAuthenticationError(f"credencial recusada por {self._model}")
        if 400 <= error.code < 500:
            return LLMRequestRejectedError(
                f"{self._model} recusou a requisição (HTTP {error.code})"
            )
        return LLMProviderError(f"{self._model} indisponível (HTTP {error.code})")

    def _parse(self, body: bytes) -> LLMResponse:
        try:
            decoded: object = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise LLMInvalidResponseError(f"{self._model} devolveu corpo não-JSON") from error
        if not isinstance(decoded, Mapping):
            raise LLMInvalidResponseError(f"{self._model} devolveu JSON que não é objeto")

        usage = _parse_usage(decoded.get("usageMetadata"))
        candidate = _first_candidate(decoded)
        if candidate is None:
            # Sem candidato só é aceitável quando o próprio prompt foi barrado;
            # qualquer outro caso é resposta inutilizável.
            if _block_reason(decoded) is None:
                raise LLMInvalidResponseError(f"{self._model} devolveu resposta sem candidatos")
            return LLMResponse(
                text="", stop_reason=StopReason.BLOCKED, model=self._model, usage=usage
            )

        stop_reason = _stop_reason(candidate.get("finishReason"))
        text = _candidate_text(candidate)
        if not text and stop_reason is StopReason.COMPLETE:
            raise LLMInvalidResponseError(f"{self._model} devolveu texto vazio")

        return LLMResponse(text=text, stop_reason=stop_reason, model=self._model, usage=usage)


def _first_candidate(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    candidates = payload.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, str | bytes):
        return None
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _block_reason(payload: Mapping[str, object]) -> str | None:
    feedback = payload.get("promptFeedback")
    if not isinstance(feedback, Mapping):
        return None
    reason = feedback.get("blockReason")
    return reason if isinstance(reason, str) else None


def _stop_reason(raw: object) -> StopReason:
    if not isinstance(raw, str):
        return StopReason.OTHER
    return _STOP_REASONS.get(raw, StopReason.OTHER)


def _candidate_text(candidate: Mapping[str, object]) -> str:
    content = candidate.get("content")
    if not isinstance(content, Mapping):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, Sequence) or isinstance(parts, str | bytes):
        return ""
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks)


def _parse_usage(raw: object) -> TokenUsage:
    if not isinstance(raw, Mapping):
        return TokenUsage()
    return TokenUsage(
        input_tokens=_optional_int(raw.get("promptTokenCount")),
        output_tokens=_optional_int(raw.get("candidatesTokenCount")),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
