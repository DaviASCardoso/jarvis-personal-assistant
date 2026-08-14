"""`SpeechToText` sobre a API REST da Groq (Whisper).

Adapter de Infrastructure: é o único módulo do componente que sabe o que é
`multipart/form-data`, `Authorization: Bearer` ou o campo `text` da resposta. O
Core fala `PcmClip` e `Transcript`.

**Sem SDK de vendor**, pelo precedente do
[ADR-0011](../../../../docs/adr/0011-gemini-rest-llm-adapter.md) e registrado no
[ADR-0022](../../../../docs/adr/0022-cloud-speech-over-stdlib-rest.md): o pacote
`groq` traria `httpx` e sua árvore para montar um POST, e enfraqueceria o teste
que afirma "nenhum SDK de vendor entra aqui".

O multipart é montado à mão porque é curto e porque o `opener` injetável só tem
valor se o corpo for verificável byte a byte no teste.
"""

import json
import logging
import secrets
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from jarvis.voice.adapters.retry import RetryPolicy, call_with_retry
from jarvis.voice.adapters.wave_io import encode_wav
from jarvis.voice.audio import PcmClip
from jarvis.voice.errors import (
    SpeechToTextError,
    SttAuthenticationError,
    SttInvalidResponseError,
    SttRateLimitError,
    SttRejectedError,
    SttTimeoutError,
)
from jarvis.voice.ports import Transcript

logger = logging.getLogger(__name__)

VENDOR: Final = "groq"
API_URL: Final = "https://api.groq.com/openai/v1/audio/transcriptions"

#: Configuração, não constante de contrato: o catálogo do provider muda mais
#: rápido que este repositório.
DEFAULT_STT_MODEL: Final = "whisper-large-v3-turbo"

UPLOAD_FILENAME: Final = "utterance.wav"

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


def build_multipart(
    *, fields: Sequence[tuple[str, str]], filename: str, content: bytes, boundary: str
) -> bytes:
    """Corpo `multipart/form-data`, com o arquivo primeiro.

    Separado da classe porque é uma função pura sobre bytes — e porque é
    exatamente o que o teste precisa inspecionar sem subir um cliente HTTP.
    """
    marker = f"--{boundary}".encode()
    parts: list[bytes] = [
        marker,
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
        b"Content-Type: audio/wav",
        b"",
        content,
    ]
    for name, value in fields:
        parts.extend(
            [
                marker,
                f'Content-Disposition: form-data; name="{name}"'.encode(),
                b"",
                value.encode("utf-8"),
            ]
        )
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    return b"\r\n".join(parts)


class GroqSpeechToText:
    """Implementa `jarvis.voice.ports.SpeechToText`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_STT_MODEL,
        opener: Opener = _urlopen_bytes,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise SttAuthenticationError("credencial da Groq ausente")
        self._api_key = api_key
        self._model = model
        self._opener = opener
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep if sleep is not None else time.sleep

    @property
    def model(self) -> str:
        return self._model

    def transcribe(
        self, clip: PcmClip, *, language: str | None = None, timeout_seconds: float
    ) -> Transcript:
        if clip.is_empty:
            # Não vale um POST para transcrever nada, e a resposta seria vazia
            # de qualquer forma.
            return Transcript(text="", language=language, duration_seconds=0.0)

        body = self._build_body(clip, language=language)
        payload = call_with_retry(
            lambda: self._post(body, timeout=timeout_seconds),
            policy=self._retry,
            what=VENDOR,
            sleep=self._sleep,
        )
        return self._parse(payload, language=language, clip=clip)

    def _build_body(self, clip: PcmClip, *, language: str | None) -> tuple[bytes, str]:
        boundary = secrets.token_hex(16)
        fields: list[tuple[str, str]] = [
            ("model", self._model),
            ("response_format", "json"),
            ("temperature", "0"),
        ]
        if language:
            fields.append(("language", language))
        return (
            build_multipart(
                fields=fields,
                filename=UPLOAD_FILENAME,
                content=encode_wav(clip),
                boundary=boundary,
            ),
            boundary,
        )

    def _post(self, body: tuple[bytes, str], *, timeout: float) -> bytes:
        data, boundary = body
        request = urllib.request.Request(
            url=API_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            return self._opener(request, timeout)
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from error
        except TimeoutError as error:
            raise SttTimeoutError(f"{VENDOR} não respondeu em {timeout}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise SttTimeoutError(f"{VENDOR} não respondeu em {timeout}s") from error
            raise SpeechToTextError(f"falha de conexão com {VENDOR}") from error
        except OSError as error:
            raise SpeechToTextError(f"falha de transporte com {VENDOR}") from error

    def _http_error(self, error: urllib.error.HTTPError) -> SpeechToTextError:
        # Nenhum ramo repete o corpo da resposta: ela ecoa a transcrição, que é
        # fala do usuário.
        logger.warning("voice.stt_http_error", extra={"provider": VENDOR, "status": error.code})
        if error.code == 429:
            return SttRateLimitError(
                f"limite de requisições de {VENDOR} atingido", retry_after=_retry_after(error)
            )
        if error.code in (401, 403):
            return SttAuthenticationError(f"credencial recusada por {VENDOR}")
        if error.code == 413:
            return SttRejectedError(f"{VENDOR} recusou o áudio: grande demais")
        if 400 <= error.code < 500:
            return SttRejectedError(f"{VENDOR} recusou a requisição (HTTP {error.code})")
        return SpeechToTextError(f"{VENDOR} indisponível (HTTP {error.code})")

    def _parse(self, body: bytes, *, language: str | None, clip: PcmClip) -> Transcript:
        try:
            decoded: object = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SttInvalidResponseError(f"{VENDOR} devolveu corpo não-JSON") from error
        if not isinstance(decoded, Mapping):
            raise SttInvalidResponseError(f"{VENDOR} devolveu JSON que não é objeto")

        text = decoded.get("text")
        if not isinstance(text, str):
            raise SttInvalidResponseError(f"{VENDOR} devolveu resposta sem campo text")

        return Transcript(
            text=text.strip(),
            language=_language_of(decoded, fallback=language),
            duration_seconds=clip.duration_seconds,
        )


def _language_of(payload: Mapping[str, object], *, fallback: str | None) -> str | None:
    """Campo opcional em `verbose_json`; ausente no formato simples."""
    value = payload.get("language")
    return value if isinstance(value, str) and value else fallback
