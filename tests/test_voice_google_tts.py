"""`GoogleCloudTextToSpeech`: corpo JSON, decodificação do áudio e erros."""

import base64
import json
from typing import Any

import pytest

from jarvis.voice.adapters.google_tts import (
    DEFAULT_VOICE,
    GoogleCloudTextToSpeech,
    truncate,
)
from jarvis.voice.adapters.retry import RetryPolicy
from jarvis.voice.adapters.wave_io import encode_wav
from jarvis.voice.audio import AudioFormat, PcmClip
from jarvis.voice.errors import (
    TextToSpeechError,
    TtsAuthenticationError,
    TtsInvalidResponseError,
    TtsRateLimitError,
    TtsRejectedError,
    TtsTimeoutError,
)
from tests.voice_doubles import (
    RecordingOpener,
    SleepSpy,
    failing_opener,
    http_error,
    pcm_tone,
)

API_KEY = "chave-de-teste-nunca-logar"


def provider(opener: object, **kwargs: object) -> GoogleCloudTextToSpeech:
    return GoogleCloudTextToSpeech(api_key=API_KEY, opener=opener, **kwargs)  # type: ignore[arg-type]


def spoken(*, rate: int = 24_000, seconds: float = 0.2) -> bytes:
    audio_format = AudioFormat(sample_rate=rate)
    clip = PcmClip(data=pcm_tone(seconds, audio_format=audio_format), format=audio_format)
    return json.dumps({"audioContent": base64.b64encode(encode_wav(clip)).decode()}).encode()


def sent(opener: RecordingOpener) -> dict[str, Any]:
    body = opener.captured[0].data
    assert isinstance(body, bytes)
    decoded: dict[str, Any] = json.loads(body)
    return decoded


# --- requisição --------------------------------------------------------------


def test_an_empty_api_key_is_refused_at_construction() -> None:
    with pytest.raises(TtsAuthenticationError):
        GoogleCloudTextToSpeech(api_key="  ")


def test_the_credential_travels_in_a_header_never_in_the_url() -> None:
    opener = RecordingOpener(spoken())

    provider(opener).synthesize("olá", timeout_seconds=5.0)

    request = opener.captured[0]
    assert request.get_header("X-goog-api-key") == API_KEY
    assert API_KEY not in request.full_url


def test_the_body_asks_for_linear16_and_the_configured_voice() -> None:
    opener = RecordingOpener(spoken())

    provider(opener, voice="pt-BR-Neural2-A", language="pt-BR", speaking_rate=1.2).synthesize(
        "bom dia", timeout_seconds=5.0
    )

    body = sent(opener)
    assert body["input"] == {"text": "bom dia"}
    assert body["voice"] == {"languageCode": "pt-BR", "name": "pt-BR-Neural2-A"}
    assert body["audioConfig"]["audioEncoding"] == "LINEAR16"
    assert body["audioConfig"]["speakingRate"] == 1.2


def test_the_default_voice_is_the_documented_one() -> None:
    opener = RecordingOpener(spoken())

    assert provider(opener).voice == DEFAULT_VOICE


def test_long_text_is_cut_at_a_sentence_boundary_before_being_sent() -> None:
    opener = RecordingOpener(spoken())
    text = "Primeira frase. Segunda frase. Terceira frase que não cabe."

    provider(opener, max_chars=32).synthesize(text, timeout_seconds=5.0)

    assert sent(opener)["input"]["text"] == "Primeira frase. Segunda frase."


def test_empty_text_is_refused_without_a_request() -> None:
    opener = RecordingOpener(spoken())

    with pytest.raises(TtsRejectedError):
        provider(opener).synthesize("   ", timeout_seconds=5.0)
    assert opener.calls == 0


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("curto", 100, "curto"),
        ("Uma. Duas. Tres.", 10, "Uma. Duas."),
        ("palavraenormesemfronteira", 10, "palavraeno"),
    ],
)
def test_truncate_prefers_a_sentence_boundary(text: str, limit: int, expected: str) -> None:
    assert truncate(text, max_chars=limit) == expected


# --- resposta ----------------------------------------------------------------


def test_the_audio_comes_back_with_the_rate_declared_by_the_file() -> None:
    # Abrir o alto-falante a 16 kHz tocaria a resposta acelerada.
    clip = provider(RecordingOpener(spoken(rate=24_000))).synthesize("oi", timeout_seconds=5.0)

    assert clip.format == AudioFormat(sample_rate=24_000)
    assert clip.duration_seconds == pytest.approx(0.2, abs=0.01)


@pytest.mark.parametrize(
    "body",
    [
        b"nao e json",
        b"[]",
        b"{}",
        json.dumps({"audioContent": ""}).encode(),
        json.dumps({"audioContent": "!!!nao-e-base64!!!"}).encode(),
        json.dumps({"audioContent": base64.b64encode(b"nao e wav").decode()}).encode(),
    ],
)
def test_an_unusable_response_is_an_invalid_response_error(body: bytes) -> None:
    with pytest.raises(TtsInvalidResponseError):
        provider(RecordingOpener(body)).synthesize("oi", timeout_seconds=5.0)


# --- erros -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, TtsRateLimitError),
        (401, TtsAuthenticationError),
        (403, TtsAuthenticationError),
        (400, TtsRejectedError),
        (404, TtsRejectedError),
        (500, TextToSpeechError),
    ],
)
def test_http_status_maps_to_the_core_taxonomy(status: int, expected: type[Exception]) -> None:
    tts = provider(failing_opener(http_error(status)), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(expected):
        tts.synthesize("oi", timeout_seconds=5.0)


def test_a_bad_voice_says_so_in_words() -> None:
    # É o erro que uma pessoa comete ao configurar; ele merece ser legível.
    tts = provider(
        failing_opener(http_error(400)),
        voice="pt-BR-Inexistente",
        retry=RetryPolicy(max_attempts=1),
    )

    with pytest.raises(TtsRejectedError, match="pt-BR-Inexistente"):
        tts.synthesize("oi", timeout_seconds=5.0)


def test_a_timeout_is_a_timeout_error() -> None:
    tts = provider(failing_opener(TimeoutError()), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(TtsTimeoutError):
        tts.synthesize("oi", timeout_seconds=5.0)


def test_a_retryable_failure_is_retried_once_and_then_succeeds() -> None:
    sleep = SleepSpy()
    opener = RecordingOpener(http_error(503), spoken())
    tts = provider(opener, retry=RetryPolicy(max_attempts=2, base_delay=0.5), sleep=sleep)

    clip = tts.synthesize("oi", timeout_seconds=5.0)

    assert clip.duration_seconds > 0
    assert opener.calls == 2
    assert sleep.slept == [0.5]
