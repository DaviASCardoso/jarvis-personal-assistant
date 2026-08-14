"""Sessão de voz: identidade, imutabilidade e ciclo de vida."""

from datetime import timedelta
from typing import Any

import pytest

from jarvis.voice.errors import InvalidVoiceInputError, VoiceSessionError
from jarvis.voice.session import (
    SessionSettings,
    TurnRole,
    VoiceSession,
    VoiceState,
    VoiceStatus,
    VoiceTurn,
    new_session_id,
)
from tests.voice_doubles import EPOCH


def _session() -> VoiceSession:
    return VoiceSession(session_id="s-1", started_at=EPOCH)


def _turn(text: str = "oi", role: TurnRole = TurnRole.USER) -> VoiceTurn:
    return VoiceTurn(role=role, text=text, at=EPOCH)


def test_the_session_id_is_also_the_correlation_id() -> None:
    # É o que faz `events list --correlation-id` mostrar a conversa inteira.
    assert _session().correlation_id == "s-1"


def test_an_explicit_correlation_id_is_preserved() -> None:
    session = VoiceSession(session_id="s-1", started_at=EPOCH, correlation_id="c-9")

    assert session.correlation_id == "c-9"


def test_new_session_ids_are_unique() -> None:
    assert new_session_id() != new_session_id()


def test_append_returns_another_session_and_never_rewrites() -> None:
    original = _session()

    updated = original.append(_turn())

    assert original.turn_count == 0
    assert updated.turn_count == 1
    assert updated.turns[0].text == "oi"


def test_a_closed_session_refuses_new_turns() -> None:
    closed = _session().end(at=EPOCH, reason="timeout")

    assert not closed.is_open
    with pytest.raises(VoiceSessionError):
        closed.append(_turn())


def test_ending_preserves_the_turns_and_measures_the_duration() -> None:
    session = _session().append(_turn()).end(at=EPOCH + timedelta(seconds=30), reason="timeout")

    assert session.turn_count == 1
    assert session.ended_reason == "timeout"
    assert session.duration_ms == pytest.approx(30_000)


def test_an_open_session_has_no_duration_yet() -> None:
    assert _session().duration_ms is None


def test_last_returns_the_tail_and_nothing_for_zero() -> None:
    session = _session().append(_turn("um")).append(_turn("dois")).append(_turn("tres"))

    assert [turn.text for turn in session.last(2)] == ["dois", "tres"]
    assert session.last(0) == ()


def test_a_turn_needs_text_and_an_aware_timestamp() -> None:
    with pytest.raises(InvalidVoiceInputError):
        VoiceTurn(role=TurnRole.USER, text="   ", at=EPOCH)
    with pytest.raises(InvalidVoiceInputError):
        VoiceTurn(role=TurnRole.USER, text="oi", at=EPOCH.replace(tzinfo=None))


def test_a_session_needs_an_id_and_an_aware_start() -> None:
    with pytest.raises(InvalidVoiceInputError):
        VoiceSession(session_id=" ", started_at=EPOCH)
    with pytest.raises(InvalidVoiceInputError):
        VoiceSession(session_id="s-1", started_at=EPOCH.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("field", "value"),
    [("follow_up_seconds", -1.0), ("idle_timeout_seconds", 0.0), ("max_turns", 0)],
)
def test_session_settings_refuse_impossible_limits(field: str, value: float) -> None:
    limits: dict[str, Any] = {field: value}

    with pytest.raises(InvalidVoiceInputError):
        SessionSettings(**limits)


def test_status_carries_what_the_panel_shows_and_no_audio() -> None:
    status = VoiceStatus(state=VoiceState.SPEAKING, at=EPOCH, session_id="s-1", last_reply="oi")

    assert status.state is VoiceState.SPEAKING
    assert not hasattr(status, "data")
    assert not hasattr(status, "clip")
