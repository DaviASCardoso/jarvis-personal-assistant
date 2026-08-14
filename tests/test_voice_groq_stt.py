"""`GroqSpeechToText`: corpo multipart, parsing e tradução de erro.

Nenhum teste aqui toca a rede — o transporte é injetado (`Opener`), como no
adapter Gemini. Sem essa costura, verificar o corpo de um multipart exigiria um
servidor.
"""

import json

import pytest

from jarvis.voice.adapters.groq_stt import (
    DEFAULT_STT_MODEL,
    GroqSpeechToText,
    build_multipart,
)
from jarvis.voice.adapters.retry import RetryPolicy
from jarvis.voice.audio import PcmClip
from jarvis.voice.errors import (
    SpeechToTextError,
    SttAuthenticationError,
    SttInvalidResponseError,
    SttRateLimitError,
    SttRejectedError,
    SttTimeoutError,
)
from tests.voice_doubles import (
    RecordingOpener,
    SleepSpy,
    failing_opener,
    http_error,
    pcm_tone,
)

API_KEY = "chave-de-teste-nunca-logar"


def clip(seconds: float = 0.5) -> PcmClip:
    return PcmClip(data=pcm_tone(seconds))


def provider(opener: object, **kwargs: object) -> GroqSpeechToText:
    return GroqSpeechToText(api_key=API_KEY, opener=opener, **kwargs)  # type: ignore[arg-type]


def ok(text: str = "que horas são") -> bytes:
    return json.dumps({"text": text}).encode("utf-8")


# --- requisição --------------------------------------------------------------


def test_an_empty_api_key_is_refused_at_construction() -> None:
    with pytest.raises(SttAuthenticationError):
        GroqSpeechToText(api_key="   ")


def test_the_credential_travels_in_a_header_never_in_the_url() -> None:
    opener = RecordingOpener(ok())

    provider(opener).transcribe(clip(), timeout_seconds=10.0)

    request = opener.captured[0]
    assert request.get_header("Authorization") == f"Bearer {API_KEY}"
    assert API_KEY not in request.full_url


def test_the_body_carries_a_wav_and_the_declared_fields() -> None:
    opener = RecordingOpener(ok())

    provider(opener).transcribe(clip(), language="pt", timeout_seconds=10.0)

    request = opener.captured[0]
    body = request.data
    assert isinstance(body, bytes)
    assert b'name="file"; filename="utterance.wav"' in body
    assert b"RIFF" in body
    assert DEFAULT_STT_MODEL.encode() in body
    assert b'name="language"' in body and b"pt" in body
    assert b'name="response_format"' in body


def test_the_boundary_in_the_header_matches_the_one_in_the_body() -> None:
    opener = RecordingOpener(ok())

    provider(opener).transcribe(clip(), timeout_seconds=10.0)

    request = opener.captured[0]
    content_type = request.get_header("Content-type") or ""
    boundary = content_type.split("boundary=")[1]
    body = request.data
    assert isinstance(body, bytes)
    assert body.startswith(f"--{boundary}".encode())
    assert body.rstrip().endswith(f"--{boundary}--".encode())


def test_language_is_omitted_when_not_configured() -> None:
    opener = RecordingOpener(ok())

    provider(opener).transcribe(clip(), language=None, timeout_seconds=10.0)

    body = opener.captured[0].data
    assert isinstance(body, bytes)
    assert b'name="language"' not in body


def test_the_timeout_reaches_the_transport() -> None:
    opener = RecordingOpener(ok())

    provider(opener).transcribe(clip(), timeout_seconds=7.5)

    assert opener.timeouts == [7.5]


def test_an_empty_clip_never_becomes_a_request() -> None:
    # Não se paga um POST para transcrever nada.
    opener = RecordingOpener(ok())

    transcript = provider(opener).transcribe(PcmClip(data=b""), timeout_seconds=10.0)

    assert transcript.is_empty
    assert opener.calls == 0


def test_build_multipart_puts_the_file_first_and_closes_the_boundary() -> None:
    body = build_multipart(
        fields=[("model", "m")], filename="a.wav", content=b"RIFFxx", boundary="B"
    )

    assert body.startswith(b'--B\r\nContent-Disposition: form-data; name="file"')
    assert body.endswith(b"--B--\r\n")


# --- resposta ----------------------------------------------------------------


def test_the_transcript_comes_back_trimmed() -> None:
    opener = RecordingOpener(json.dumps({"text": "  que horas são  "}).encode())

    transcript = provider(opener).transcribe(clip(), timeout_seconds=10.0)

    assert transcript.text == "que horas são"
    assert transcript.duration_seconds == pytest.approx(0.5, abs=0.01)


def test_the_language_of_the_response_wins_over_the_requested_one() -> None:
    opener = RecordingOpener(json.dumps({"text": "oi", "language": "portuguese"}).encode())

    transcript = provider(opener).transcribe(clip(), language="pt", timeout_seconds=10.0)

    assert transcript.language == "portuguese"


def test_silence_transcribed_as_nothing_is_an_empty_transcript_not_an_error() -> None:
    opener = RecordingOpener(json.dumps({"text": "   "}).encode())

    assert provider(opener).transcribe(clip(), timeout_seconds=10.0).is_empty


@pytest.mark.parametrize("body", [b"nao e json", b"[]", b'{"nada": 1}'])
def test_an_unusable_response_is_an_invalid_response_error(body: bytes) -> None:
    with pytest.raises(SttInvalidResponseError):
        provider(RecordingOpener(body)).transcribe(clip(), timeout_seconds=10.0)


# --- erros -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, SttRateLimitError),
        (401, SttAuthenticationError),
        (403, SttAuthenticationError),
        (413, SttRejectedError),
        (400, SttRejectedError),
        (500, SpeechToTextError),
        (503, SpeechToTextError),
    ],
)
def test_http_status_maps_to_the_core_taxonomy(status: int, expected: type[Exception]) -> None:
    stt = provider(failing_opener(http_error(status)), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(expected):
        stt.transcribe(clip(), timeout_seconds=10.0)


def test_a_timeout_is_a_timeout_error() -> None:
    stt = provider(failing_opener(TimeoutError()), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(SttTimeoutError):
        stt.transcribe(clip(), timeout_seconds=10.0)


def test_a_transport_failure_stays_inside_the_taxonomy() -> None:
    stt = provider(failing_opener(OSError("cabo solto")), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(SpeechToTextError):
        stt.transcribe(clip(), timeout_seconds=10.0)


def test_no_vendor_exception_escapes_to_the_core() -> None:
    stt = provider(failing_opener(http_error(500)), retry=RetryPolicy(max_attempts=1))

    with pytest.raises(SpeechToTextError) as raised:
        stt.transcribe(clip(), timeout_seconds=10.0)
    assert type(raised.value).__module__.startswith("jarvis.")


# --- retry -------------------------------------------------------------------


def test_a_retryable_failure_is_retried_once_and_then_succeeds() -> None:
    sleep = SleepSpy()
    opener = RecordingOpener(http_error(503), ok("pronto"))
    stt = provider(opener, retry=RetryPolicy(max_attempts=2, base_delay=1.0), sleep=sleep)

    transcript = stt.transcribe(clip(), timeout_seconds=10.0)

    assert transcript.text == "pronto"
    assert opener.calls == 2
    assert sleep.slept == [1.0]


def test_the_providers_retry_after_wins_over_the_backoff() -> None:
    sleep = SleepSpy()
    opener = RecordingOpener(http_error(429, retry_after="4"), ok())
    stt = provider(opener, retry=RetryPolicy(max_attempts=2, base_delay=1.0), sleep=sleep)

    stt.transcribe(clip(), timeout_seconds=10.0)

    assert sleep.slept == [4.0]


def test_a_permanent_failure_is_not_retried() -> None:
    sleep = SleepSpy()
    opener = RecordingOpener(http_error(401), ok())
    stt = provider(opener, retry=RetryPolicy(max_attempts=3), sleep=sleep)

    with pytest.raises(SttAuthenticationError):
        stt.transcribe(clip(), timeout_seconds=10.0)
    assert opener.calls == 1
    assert sleep.slept == []
