"""`TextToSpeech` sobre a API REST do Google Cloud Text-to-Speech.

Adapter de Infrastructure: é o único módulo do componente que sabe o que é
`audioContent`, `LINEAR16` ou `speakingRate`. O Core fala texto e `PcmClip`.

**A credencial vai no header `x-goog-api-key`, nunca na query string** — mesma
regra do adapter Gemini
([ADR-0011](../../../../docs/adr/0011-gemini-rest-llm-adapter.md)): uma URL com
segredo vaza em log de exceção, em proxy e em histórico de shell, e `HTTPError`
imprime a URL por padrão.

**`LINEAR16`, não MP3.** MP3 economizaria banda que ninguém está pagando num
loopback local, e custaria um decoder — que custaria uma dependência. O que volta
é WAV, e `wave_io.decode_wav` já resolve.
"""

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Final

from jarvis.voice.adapters.retry import RetryPolicy, call_with_retry
from jarvis.voice.adapters.wave_io import decode_wav
from jarvis.voice.audio import PcmClip
from jarvis.voice.errors import (
    AudioFormatError,
    TextToSpeechError,
    TtsAuthenticationError,
    TtsInvalidResponseError,
    TtsRateLimitError,
    TtsRejectedError,
    TtsTimeoutError,
)

logger = logging.getLogger(__name__)

VENDOR: Final = "google"
API_URL: Final = "https://texttospeech.googleapis.com/v1/text:synthesize"

DEFAULT_VOICE: Final = "pt-BR-Neural2-B"
DEFAULT_LANGUAGE: Final = "pt-BR"
DEFAULT_SAMPLE_RATE: Final = 24_000

#: Teto de texto por chamada. A API aceita ~5000 bytes; falar por três minutos
#: seguidos também não é o comportamento desejado de um assistente.
DEFAULT_MAX_CHARS: Final = 1200

_SENTENCE_ENDINGS: Final = (". ", "! ", "? ", "; ", "\n")

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
        return None


def truncate(text: str, *, max_chars: int) -> str:
    """Corta na última fronteira de frase que couber, não no meio da palavra.

    Cortar no caractere exato produziria uma fala que termina no meio de uma
    sílaba — pior que dizer menos.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    # O espaço-sentinela faz a última frase contar mesmo quando ela termina
    # exatamente no limite: sem ele, "Uma. Duas." cortado em 10 viraria "Uma.",
    # jogando fora uma frase inteira que cabia.
    padded = f"{window} "
    cut = max(padded.rfind(ending) for ending in _SENTENCE_ENDINGS)
    return window[: cut + 1].strip() if cut > 0 else window.rstrip()


class GoogleCloudTextToSpeech:
    """Implementa `jarvis.voice.ports.TextToSpeech`."""

    def __init__(
        self,
        *,
        api_key: str,
        voice: str = DEFAULT_VOICE,
        language: str = DEFAULT_LANGUAGE,
        speaking_rate: float = 1.0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        max_chars: int = DEFAULT_MAX_CHARS,
        opener: Opener = _urlopen_bytes,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        cleaned_key = api_key.strip()
        if not cleaned_key:
            raise TtsAuthenticationError("credencial do Google Cloud TTS ausente")
        self._api_key = cleaned_key
        self._voice = voice
        self._language = language
        self._speaking_rate = speaking_rate
        self._sample_rate = sample_rate
        self._max_chars = max_chars
        self._opener = opener
        self._retry = retry if retry is not None else RetryPolicy()
        self._sleep = sleep if sleep is not None else time.sleep

    @property
    def voice(self) -> str:
        return self._voice

    def synthesize(self, text: str, *, timeout_seconds: float) -> PcmClip:
        spoken = truncate(text.strip(), max_chars=self._max_chars)
        if not spoken:
            raise TtsRejectedError("nada a sintetizar: o texto está vazio")
        if len(spoken) < len(text.strip()):
            logger.info(
                "voice.tts_truncated",
                extra={"original_chars": len(text), "spoken_chars": len(spoken)},
            )

        body = self._build_body(spoken)
        payload = call_with_retry(
            lambda: self._post(body, timeout=timeout_seconds),
            policy=self._retry,
            what=VENDOR,
            sleep=self._sleep,
        )
        return self._parse(payload)

    def _build_body(self, text: str) -> dict[str, object]:
        return {
            "input": {"text": text},
            "voice": {"languageCode": self._language, "name": self._voice},
            "audioConfig": {
                "audioEncoding": "LINEAR16",
                "sampleRateHertz": self._sample_rate,
                "speakingRate": self._speaking_rate,
            },
        }

    def _post(self, body: Mapping[str, object], *, timeout: float) -> bytes:
        request = urllib.request.Request(
            url=API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
            method="POST",
        )

        try:
            return self._opener(request, timeout)
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from error
        except TimeoutError as error:
            raise TtsTimeoutError(f"{VENDOR} não respondeu em {timeout}s") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TtsTimeoutError(f"{VENDOR} não respondeu em {timeout}s") from error
            raise TextToSpeechError(f"falha de conexão com {VENDOR}") from error
        except OSError as error:
            raise TextToSpeechError(f"falha de transporte com {VENDOR}") from error

    def _http_error(self, error: urllib.error.HTTPError) -> TextToSpeechError:
        # A resposta de erro ecoa o texto enviado, que é a fala do agente sobre o
        # contexto do usuário. Nenhum ramo a repete.
        logger.warning("voice.tts_http_error", extra={"provider": VENDOR, "status": error.code})
        if error.code == 429:
            return TtsRateLimitError(
                f"limite de requisições de {VENDOR} atingido", retry_after=_retry_after(error)
            )
        if error.code in (401, 403):
            return TtsAuthenticationError(f"credencial recusada por {VENDOR}")
        if error.code == 400:
            # O erro que uma pessoa comete ao configurar, e ele merece ser legível.
            return TtsRejectedError(
                f"{VENDOR} recusou a requisição: confira se a voz {self._voice!r} "
                f"existe para o idioma {self._language!r}"
            )
        if 400 < error.code < 500:
            return TtsRejectedError(f"{VENDOR} recusou a requisição (HTTP {error.code})")
        return TextToSpeechError(f"{VENDOR} indisponível (HTTP {error.code})")

    def _parse(self, body: bytes) -> PcmClip:
        try:
            decoded: object = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise TtsInvalidResponseError(f"{VENDOR} devolveu corpo não-JSON") from error
        if not isinstance(decoded, Mapping):
            raise TtsInvalidResponseError(f"{VENDOR} devolveu JSON que não é objeto")

        content = decoded.get("audioContent")
        if not isinstance(content, str) or not content:
            raise TtsInvalidResponseError(f"{VENDOR} devolveu resposta sem audioContent")

        try:
            raw = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as error:
            raise TtsInvalidResponseError(f"{VENDOR} devolveu audioContent inválido") from error

        try:
            # `LINEAR16` volta embrulhado em RIFF, e o formato real (24 kHz) vem
            # do próprio arquivo — não do que pedimos.
            return decode_wav(raw)
        except AudioFormatError as error:
            raise TtsInvalidResponseError(f"{VENDOR} devolveu áudio ilegível: {error}") from error
