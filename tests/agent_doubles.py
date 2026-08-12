"""Doubles do Agent Runtime, com defaults válidos.

Cada double controla exatamente uma variável do teste, no mesmo espírito de
`memory_doubles.py`:

- `RecordingOpener`/`failing_opener` — o que a rede devolve ao adapter Gemini,
  sem rede;
- `gemini_body` — uma resposta bem formada do provider, para não repetir JSON
  literal em cada teste.

Nenhum double aqui chama rede, disco ou relógio real.
"""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message as EmailMessage
from io import BytesIO
from typing import Final

from jarvis.agent.adapters.gemini import Opener
from jarvis.agent.messages import LLMModel

NOON: Final = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
STUB_MODEL: Final = LLMModel(vendor="stub", name="stub-v1")


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
