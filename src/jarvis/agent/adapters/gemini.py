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

from jarvis.agent.decision import DecisionType
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
# O default anterior (`gemini-2.0-flash`) foi aposentado e passou a responder 404
# — o risco previsto no plano da Fase 4 se concretizou; conferir disponibilidade
# ao trocar.
DEFAULT_GEMINI_MODEL: Final = "gemini-3.6-flash"

# `role` do lado do modelo na API: o Core chama de `assistant`, o Gemini de `model`.
_ROLE_NAMES: Final[Mapping[Role, str]] = {Role.USER: "user", Role.ASSISTANT: "model"}
_MEMORY_TYPE_VALUES: Final = (
    "episodic",
    "semantic",
    "preference",
    "procedural",
    "working",
    "task",
)
# O MIME type sozinho torna JSON mais provável, mas não impede o modelo de
# responder com prosa. Este é o subconjunto OpenAPI aceito por `responseSchema`;
# a validação completa (incluindo a matriz das seis variantes) continua no Core.
_DECISION_RESPONSE_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": [item.value for item in DecisionType]},
        "reason": {"type": "string"},
        "message": {"type": "string"},
        "memory": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": _MEMORY_TYPE_VALUES},
                "content": {"type": "string"},
                "subject": {"type": "string"},
                "importance": {"type": "number", "minimum": 0, "maximum": 1},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["type", "content"],
        },
        "action": {
            "type": "object",
            "properties": {
                "skill": {"type": "string"},
                # Texto, e não objeto, por limitação medida do `responseSchema`:
                # o subconjunto OpenAPI não expressa "objeto de forma livre", e
                # um `{"type": "object"}` sem `properties` faz o modelo devolver
                # `{}` em toda chamada — o que tornaria `act` inútil para
                # qualquer Skill com parâmetro obrigatório. Volta a ser objeto em
                # `_decode_action_parameters`, antes de o Core ver o texto.
                "parameters": {
                    "type": "string",
                    "description": (
                        "Os parâmetros da skill como documento JSON. "
                        'Exemplo: {"path": "nota.txt", "content": "oi"}'
                    ),
                },
            },
            "required": ["skill"],
        },
    },
    "required": ["type", "reason"],
}

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
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = _DECISION_RESPONSE_SCHEMA

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
        text = _decode_action_parameters(_candidate_text(candidate))
        if not text and stop_reason is StopReason.COMPLETE:
            raise LLMInvalidResponseError(f"{self._model} devolveu texto vazio")

        return LLMResponse(text=text, stop_reason=stop_reason, model=self._model, usage=usage)


def _decode_action_parameters(text: str) -> str:
    """Desfaz a codificação que o `responseSchema` do Gemini obriga.

    Tradução de vendor, e por isso mora no adapter: o Core continua recebendo
    `action.parameters` como objeto, exatamente como `ActionProposal` exige, sem
    saber que no fio ele viajou como texto.

    Nada aqui inventa parâmetro. Quando a decodificação não é possível, o texto
    segue intacto e quem recusa é o Core — errar para o lado da proposta
    rejeitada é o desfecho seguro quando o assunto é o que será executado.
    """
    try:
        payload: object = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(payload, dict):
        return text

    action = payload.get("action")
    if not isinstance(action, dict):
        return text
    raw = action.get("parameters")
    if not isinstance(raw, str):
        return text

    if not raw.strip():
        # "sem parâmetros" dito como texto vazio: uma Skill sem campo
        # obrigatório é atendida, e uma com campo obrigatório continua sendo
        # recusada pela validação de schema, mais adiante.
        action["parameters"] = {}
        return json.dumps(payload)

    try:
        action["parameters"] = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return text
    return json.dumps(payload)


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
