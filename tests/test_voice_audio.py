"""Os tipos de áudio do Core e a aritmética sobre eles."""

import math

import pytest

from jarvis.voice.audio import (
    CAPTURE_FORMAT,
    MAX_CLIP_SECONDS,
    AudioChunk,
    AudioFormat,
    PcmClip,
    concat,
    rms,
    silence,
)
from jarvis.voice.errors import InvalidVoiceInputError
from tests.voice_doubles import EPOCH, pcm_tone, quiet, tone


def test_format_derives_sizes_from_the_sample_layout() -> None:
    audio_format = AudioFormat()

    assert audio_format.frame_bytes == 2
    assert audio_format.bytes_per_second == 32_000
    assert audio_format.duration_of(b"\x00" * 32_000) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sample_rate", 0), ("channels", 2), ("sample_width", 4)],
)
def test_format_refuses_what_the_pipeline_does_not_process(field: str, value: int) -> None:
    with pytest.raises(InvalidVoiceInputError):
        AudioFormat(**{field: value})


def test_rms_of_a_sine_is_the_amplitude_over_root_two() -> None:
    # A propriedade que torna o limiar do VAD verificável em vez de empírico.
    data = pcm_tone(0.5, amplitude=0.5)

    assert rms(data) == pytest.approx(0.5 / math.sqrt(2), abs=0.01)


def test_rms_of_silence_is_zero_and_of_nothing_is_zero() -> None:
    assert rms(b"\x00" * 1000) == 0.0
    assert rms(b"") == 0.0


def test_rms_ignores_a_trailing_partial_sample() -> None:
    # Um dispositivo pode entregar um frame cortado ao fechar o stream; isso não
    # é motivo para perder o enunciado.
    data = pcm_tone(0.1) + b"\x01"

    assert rms(data) > 0


def test_rms_refuses_a_width_the_pipeline_does_not_use() -> None:
    with pytest.raises(InvalidVoiceInputError):
        rms(b"\x00\x00", sample_width=4)


def test_chunk_exposes_duration_and_energy() -> None:
    chunk = tone(0.25)

    assert chunk.duration_seconds == pytest.approx(0.25)
    assert chunk.rms > 0.3
    assert quiet(0.25).rms == 0.0


def test_chunk_requires_an_aware_timestamp() -> None:
    with pytest.raises(InvalidVoiceInputError):
        AudioChunk(data=b"", captured_at=EPOCH.replace(tzinfo=None))


def test_clip_refuses_data_that_ends_mid_sample() -> None:
    with pytest.raises(InvalidVoiceInputError):
        PcmClip(data=b"\x00")


def test_clip_refuses_more_than_the_ceiling() -> None:
    oversized = b"\x00" * int((MAX_CLIP_SECONDS + 1) * CAPTURE_FORMAT.bytes_per_second)

    with pytest.raises(InvalidVoiceInputError):
        PcmClip(data=oversized)


def test_concat_joins_contiguous_blocks() -> None:
    clip = concat([tone(0.1), quiet(0.1), tone(0.1)])

    assert clip.duration_seconds == pytest.approx(0.3)
    assert clip.format == CAPTURE_FORMAT
    assert not clip.is_empty


def test_concat_refuses_mixed_formats_instead_of_resampling() -> None:
    other = AudioFormat(sample_rate=24_000)

    with pytest.raises(InvalidVoiceInputError):
        concat([tone(0.1), tone(0.1, audio_format=other)])


def test_concat_of_nothing_is_an_error_not_an_empty_clip() -> None:
    with pytest.raises(InvalidVoiceInputError):
        concat([])


def test_silence_has_the_requested_duration() -> None:
    clip = silence(0.5)

    assert clip.duration_seconds == pytest.approx(0.5)
    assert rms(clip.data) == 0.0

    with pytest.raises(InvalidVoiceInputError):
        silence(-1.0)
