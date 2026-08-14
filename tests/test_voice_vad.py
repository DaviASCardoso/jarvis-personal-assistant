"""Segmentação determinística de fala.

Todo teste aqui alimenta uma sequência conhecida de blocos e afirma exatamente
quando o segmento fecha — é a propriedade que justifica um VAD por energia em vez
de um modelo: o comportamento é reproduzível sem gravação e sem microfone.
"""

from typing import Any

import pytest

from jarvis.voice.errors import InvalidVoiceInputError
from jarvis.voice.vad import SegmentEnd, Segmenter, SpeechSegment, VadSettings
from tests.voice_doubles import BLOCK_SECONDS, EPOCH, stream


def _feed(segmenter: Segmenter, pattern: list[tuple[str, float]]) -> list[SpeechSegment]:
    segments: list[SpeechSegment] = []
    for chunk in stream(pattern):
        segment = segmenter.feed(chunk)
        if segment is not None:
            segments.append(segment)
    return segments


def test_silence_alone_never_opens_a_segment() -> None:
    segmenter = Segmenter()

    assert _feed(segmenter, [("quiet", 3.0)]) == []
    assert not segmenter.is_speaking


def test_speech_followed_by_silence_closes_one_segment() -> None:
    segmenter = Segmenter()

    segments = _feed(segmenter, [("quiet", 0.5), ("loud", 1.0), ("quiet", 1.0)])

    assert len(segments) == 1
    assert segments[0].reason is SegmentEnd.SILENCE
    assert segments[0].speech_seconds == pytest.approx(1.0, abs=0.05)
    assert not segmenter.is_speaking


def test_a_short_burst_is_discarded_as_noise() -> None:
    # Tosse, clique, porta batendo: passam do limiar por 100 ms e não são fala.
    segmenter = Segmenter(settings=VadSettings(min_speech_ms=300))

    assert _feed(segmenter, [("loud", 0.1), ("quiet", 1.0)]) == []


def test_the_pre_roll_keeps_the_first_syllable() -> None:
    # Sem pre-roll, o limiar corta o início e o transcritor recebe "arvis".
    with_pre_roll = Segmenter(settings=VadSettings(pre_roll_ms=300))
    without = Segmenter(settings=VadSettings(pre_roll_ms=0))
    pattern = [("quiet", 0.5), ("loud", 1.0), ("quiet", 1.0)]

    kept = _feed(with_pre_roll, pattern)[0]
    trimmed = _feed(without, pattern)[0]

    assert kept.clip.duration_seconds > trimmed.clip.duration_seconds
    assert kept.clip.duration_seconds == pytest.approx(
        trimmed.clip.duration_seconds + 0.3, abs=BLOCK_SECONDS
    )


def test_a_long_utterance_closes_on_the_hard_ceiling() -> None:
    segmenter = Segmenter(settings=VadSettings(max_utterance_seconds=1.0))

    segments = _feed(segmenter, [("loud", 3.0)])

    assert [segment.reason for segment in segments] == [SegmentEnd.MAX_DURATION] * 3


def test_a_pause_shorter_than_the_threshold_does_not_split_the_utterance() -> None:
    segmenter = Segmenter(settings=VadSettings(silence_ms=800))

    segments = _feed(segmenter, [("loud", 0.5), ("quiet", 0.4), ("loud", 0.5), ("quiet", 1.0)])

    # 0,5 de fala + 0,4 de pausa + 0,5 de fala + os 0,8 de silêncio que fecham.
    assert len(segments) == 1
    assert segments[0].clip.duration_seconds == pytest.approx(2.2, abs=0.15)


def test_segment_timestamps_come_from_the_blocks() -> None:
    segmenter = Segmenter(settings=VadSettings(pre_roll_ms=0))

    segment = _feed(segmenter, [("quiet", 0.5), ("loud", 0.5), ("quiet", 1.0)])[0]

    assert segment.started_at >= EPOCH
    assert segment.ended_at > segment.started_at


def test_flush_closes_what_is_open_and_returns_nothing_when_idle() -> None:
    segmenter = Segmenter()
    for chunk in stream([("loud", 0.5)]):
        segmenter.feed(chunk)

    flushed = segmenter.flush()

    assert flushed is not None
    assert flushed.reason is SegmentEnd.FLUSH
    assert segmenter.flush() is None


def test_reset_forgets_a_partial_utterance() -> None:
    segmenter = Segmenter()
    for chunk in stream([("loud", 0.5)]):
        segmenter.feed(chunk)

    segmenter.reset()

    assert not segmenter.is_speaking
    assert segmenter.flush() is None


def test_two_utterances_produce_two_segments() -> None:
    segmenter = Segmenter()

    segments = _feed(segmenter, [("loud", 0.5), ("quiet", 1.0), ("loud", 0.5), ("quiet", 1.0)])

    assert len(segments) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rms_threshold", 0.0),
        ("rms_threshold", 1.0),
        ("silence_ms", 0),
        ("pre_roll_ms", -1),
        ("max_utterance_seconds", 0.0),
        ("max_utterance_seconds", 120.0),
    ],
)
def test_settings_refuse_impossible_limits(field: str, value: float) -> None:
    limits: dict[str, Any] = {field: value}

    with pytest.raises(InvalidVoiceInputError):
        VadSettings(**limits)
