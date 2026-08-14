"""WAV: ida, volta, e recusa explícita do que o pipeline não processa."""

import io
import wave

import pytest

from jarvis.voice.adapters.wave_io import decode_wav, encode_wav
from jarvis.voice.audio import AudioFormat, PcmClip
from jarvis.voice.errors import AudioFormatError
from tests.voice_doubles import pcm_tone


def _wav(*, channels: int, width: int, rate: int, frames: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def test_encode_produces_a_riff_container() -> None:
    data = encode_wav(PcmClip(data=pcm_tone(0.2)))

    assert data.startswith(b"RIFF")
    assert b"WAVE" in data[:16]


def test_encode_then_decode_returns_the_same_audio() -> None:
    clip = PcmClip(data=pcm_tone(0.3))

    restored = decode_wav(encode_wav(clip))

    assert restored.data == clip.data
    assert restored.format == clip.format


def test_decode_reads_the_rate_from_the_file_not_from_expectation() -> None:
    # O Google devolve 24 kHz; abrir o alto-falante na taxa errada tocaria a
    # resposta acelerada.
    payload = _wav(
        channels=1,
        width=2,
        rate=24_000,
        frames=pcm_tone(0.1, audio_format=AudioFormat(sample_rate=24_000)),
    )

    clip = decode_wav(payload)

    assert clip.format == AudioFormat(sample_rate=24_000)
    assert clip.duration_seconds == pytest.approx(0.1, abs=0.01)


@pytest.mark.parametrize(
    ("channels", "width"),
    [(2, 2), (1, 1)],
)
def test_decode_refuses_formats_instead_of_converting_them(channels: int, width: int) -> None:
    payload = _wav(channels=channels, width=width, rate=16_000, frames=b"\x00" * 640)

    with pytest.raises(AudioFormatError):
        decode_wav(payload)


@pytest.mark.parametrize("payload", [b"", b"not a wav at all", b"RIFF\x00\x00\x00\x00WAVE"])
def test_decode_refuses_content_that_is_not_a_readable_wav(payload: bytes) -> None:
    with pytest.raises(AudioFormatError):
        decode_wav(payload)
