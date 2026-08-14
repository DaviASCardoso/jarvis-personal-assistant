"""Os dois detectores de wake word: push-to-talk e transcrição."""

import io

import pytest

from jarvis.voice.adapters.wake_push_to_talk import PushToTalkWakeWord, StdinTrigger
from jarvis.voice.adapters.wake_transcription import (
    TranscriptionWakeWord,
    WakeBudget,
)
from jarvis.voice.vad import VadSettings
from jarvis.voice.wake import WakePhrase
from tests.voice_doubles import ScriptedSpeechToText, quiet, stream, stt_error, tone


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- push-to-talk ------------------------------------------------------------


def test_push_to_talk_fires_only_when_the_trigger_is_armed() -> None:
    armed = [False]
    detector = PushToTalkWakeWord(trigger=lambda: armed[0])

    assert detector.feed(quiet()) is None
    armed[0] = True
    detection = detector.feed(quiet())

    assert detection is not None
    assert detection.detector == "push-to-talk"


def test_push_to_talk_ignores_the_audio_entirely() -> None:
    # Nenhum áudio sai do dispositivo antes de o usuário pedir — é a razão de
    # este ser o modo padrão.
    detector = PushToTalkWakeWord(trigger=lambda: True)

    assert detector.feed(quiet()) is not None
    assert detector.feed(tone()) is not None


def test_reset_consumes_a_pending_trigger() -> None:
    # Uma tecla apertada enquanto o Jarvis fala não deve abrir outro turno
    # sozinha quando ele terminar.
    taken: list[bool] = []

    def trigger() -> bool:
        taken.append(True)
        return True

    PushToTalkWakeWord(trigger=trigger).reset()

    assert taken == [True]


def test_close_stops_whatever_was_reading_the_keyboard() -> None:
    stopped: list[bool] = []
    detector = PushToTalkWakeWord(trigger=lambda: False, stop=lambda: stopped.append(True))

    detector.close()

    assert stopped == [True]


def test_the_stdin_trigger_arms_once_per_line() -> None:
    trigger = StdinTrigger(source=io.StringIO("\n\n"))
    trigger.start()
    trigger._thread.join(timeout=2)  # type: ignore[union-attr]

    assert trigger.take() is True
    assert trigger.take() is False

    trigger.stop()


def test_a_trigger_that_never_started_never_fires() -> None:
    assert StdinTrigger(source=io.StringIO("")).take() is False


# --- orçamento ---------------------------------------------------------------


def test_the_budget_allows_up_to_the_ceiling_per_minute() -> None:
    clock = FakeClock()
    budget = WakeBudget(per_minute=2, monotonic=clock)

    assert [budget.take() for _ in range(3)] == [True, True, False]
    assert budget.refused == 1


def test_the_budget_window_slides_instead_of_resetting_on_the_minute() -> None:
    # Um contador que zera na virada do minuto permitiria o dobro na fronteira.
    clock = FakeClock()
    budget = WakeBudget(per_minute=1, monotonic=clock)

    assert budget.take() is True
    clock.now = 30.0
    assert budget.take() is False
    clock.now = 61.0
    assert budget.take() is True


def test_a_zero_budget_refuses_everything() -> None:
    assert WakeBudget(per_minute=0, monotonic=FakeClock()).take() is False


# --- detector por transcrição ------------------------------------------------


def _detector(
    stt: ScriptedSpeechToText,
    *,
    budget: int = 12,
    max_segment_seconds: float = 3.0,
) -> TranscriptionWakeWord:
    return TranscriptionWakeWord(
        stt=stt,
        phrases=(WakePhrase(text="jarvis"),),
        vad=VadSettings(silence_ms=300),
        budget_per_minute=budget,
        max_segment_seconds=max_segment_seconds,
        monotonic=FakeClock(),
    )


def _feed(detector: TranscriptionWakeWord, pattern: list[tuple[str, float]]) -> object | None:
    for chunk in stream(pattern):
        detection = detector.feed(chunk)
        if detection is not None:
            return detection
    return None


def test_silence_never_becomes_a_request() -> None:
    # O gate de energia é o que impede o ambiente inteiro de ir para a nuvem.
    stt = ScriptedSpeechToText(["jarvis"])
    detector = _detector(stt)

    assert _feed(detector, [("quiet", 3.0)]) is None
    assert stt.calls == []


def test_speech_with_the_phrase_activates_and_keeps_the_remainder() -> None:
    stt = ScriptedSpeechToText(["jarvis, que horas são"])
    detector = _detector(stt)

    detection = _feed(detector, [("loud", 0.6), ("quiet", 0.5)])

    assert detection is not None
    assert detection.remainder == "que horas sao"  # type: ignore[attr-defined]
    assert detection.detector == "transcription"  # type: ignore[attr-defined]


def test_speech_without_the_phrase_does_not_activate() -> None:
    stt = ScriptedSpeechToText(["preciso comprar pão"])
    detector = _detector(stt)

    assert _feed(detector, [("loud", 0.6), ("quiet", 0.5)]) is None
    assert len(stt.calls) == 1


def test_a_long_segment_is_speech_not_a_call_by_name() -> None:
    stt = ScriptedSpeechToText(["jarvis"])
    detector = _detector(stt, max_segment_seconds=0.5)

    assert _feed(detector, [("loud", 2.0), ("quiet", 0.5)]) is None
    assert stt.calls == []


def test_the_budget_stops_transcribing_when_the_room_is_noisy() -> None:
    stt = ScriptedSpeechToText(["nada", "nada", "nada"])
    detector = _detector(stt, budget=1)

    for _ in range(3):
        _feed(detector, [("loud", 0.6), ("quiet", 0.5)])

    assert len(stt.calls) == 1


def test_a_failing_transcription_does_not_kill_the_detector() -> None:
    stt = ScriptedSpeechToText(["jarvis"], error=stt_error(), fail_on=1)
    detector = _detector(stt)

    assert _feed(detector, [("loud", 0.6), ("quiet", 0.5)]) is None
    assert _feed(detector, [("loud", 0.6), ("quiet", 0.5)]) is not None


def test_an_empty_transcription_is_not_an_activation() -> None:
    stt = ScriptedSpeechToText([""])
    detector = _detector(stt)

    assert _feed(detector, [("loud", 0.6), ("quiet", 0.5)]) is None


def test_reset_drops_a_partial_utterance() -> None:
    stt = ScriptedSpeechToText(["jarvis"])
    detector = _detector(stt)
    for chunk in stream([("loud", 0.3)]):
        detector.feed(chunk)

    detector.reset()

    assert _feed(detector, [("quiet", 0.5)]) is None
    assert stt.calls == []


def test_the_detector_depends_on_the_port_not_on_a_vendor() -> None:
    # Trocar de provider de transcrição não toca uma linha do detector.
    stt = ScriptedSpeechToText(["jarvis"], model="outro-provider")

    assert _detector(stt) is not None
    with pytest.raises(AttributeError):
        _ = stt.api_key  # type: ignore[attr-defined]
