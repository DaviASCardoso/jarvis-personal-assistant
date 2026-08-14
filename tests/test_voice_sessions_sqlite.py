"""Persistência de sessões de voz — estado operacional, apagável."""

import sqlite3
from datetime import timedelta

import pytest

from jarvis.voice.adapters.sqlite_sessions import (
    IN_MEMORY_DATABASE,
    SqliteVoiceSessionRepository,
)
from jarvis.voice.errors import VoiceRepositoryError
from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn
from tests.voice_doubles import EPOCH


@pytest.fixture
def repository() -> SqliteVoiceSessionRepository:
    return SqliteVoiceSessionRepository.open(IN_MEMORY_DATABASE)


def _session(session_id: str = "s-1", *, started_at: object = None) -> VoiceSession:
    return VoiceSession(
        session_id=session_id,
        started_at=started_at if started_at is not None else EPOCH,  # type: ignore[arg-type]
    )


def _with_turns(session: VoiceSession) -> VoiceSession:
    return session.append(VoiceTurn(role=TurnRole.USER, text="que horas são", at=EPOCH)).append(
        VoiceTurn(
            role=TurnRole.ASSISTANT,
            text="nove e vinte",
            at=EPOCH + timedelta(seconds=2),
            latency_ms=1200.5,
            decision_type="notify",
            correlation_id="s-1",
        )
    )


def test_a_saved_session_comes_back_whole(repository: SqliteVoiceSessionRepository) -> None:
    original = _with_turns(_session()).end(at=EPOCH + timedelta(seconds=30), reason="timeout")

    repository.save(original)
    restored = repository.get("s-1")

    assert restored == original


def test_turns_come_back_in_order(repository: SqliteVoiceSessionRepository) -> None:
    repository.save(_with_turns(_session()))

    restored = repository.get("s-1")

    assert restored is not None
    assert [turn.role for turn in restored.turns] == [TurnRole.USER, TurnRole.ASSISTANT]
    assert restored.turns[1].latency_ms == pytest.approx(1200.5)
    assert restored.turns[1].decision_type == "notify"


def test_saving_twice_updates_instead_of_failing(
    repository: SqliteVoiceSessionRepository,
) -> None:
    # Uma sessão cresce turno a turno e é salva várias vezes — ao contrário de uma
    # execução, que é registrada uma vez e nunca reescrita.
    session = _session()
    repository.save(session)
    repository.save(_with_turns(session))

    restored = repository.get("s-1")

    assert restored is not None
    assert restored.turn_count == 2


def test_an_unknown_session_is_none(repository: SqliteVoiceSessionRepository) -> None:
    assert repository.get("nao-existe") is None


def test_listing_returns_the_most_recent_first(
    repository: SqliteVoiceSessionRepository,
) -> None:
    repository.save(_session("velha", started_at=EPOCH))
    repository.save(_session("nova", started_at=EPOCH + timedelta(hours=1)))

    found = repository.list(limit=10)

    assert [session.session_id for session in found] == ["nova", "velha"]
    assert [session.session_id for session in repository.list(limit=1)] == ["nova"]


def test_purging_a_session_takes_its_turns_with_it(
    repository: SqliteVoiceSessionRepository,
) -> None:
    repository.save(_with_turns(_session()))

    assert repository.purge("s-1") is True
    assert repository.get("s-1") is None
    assert repository.purge("s-1") is False


def test_retention_removes_what_started_before_the_cutoff(
    repository: SqliteVoiceSessionRepository,
) -> None:
    repository.save(_with_turns(_session("velha", started_at=EPOCH)))
    repository.save(_session("nova", started_at=EPOCH + timedelta(days=10)))

    purged = repository.purge_before(EPOCH + timedelta(days=7))

    assert purged == 1
    assert repository.get("velha") is None
    assert repository.get("nova") is not None


def test_the_schema_has_no_audio_column(repository: SqliteVoiceSessionRepository) -> None:
    # Uma sessão guarda o que foi dito, nunca o que foi ouvido (ADR-0025).
    connection = sqlite3.connect(IN_MEMORY_DATABASE)
    with SqliteVoiceSessionRepository.open(IN_MEMORY_DATABASE) as opened:
        columns = {
            str(row[1])
            for table in ("voice_sessions", "voice_turns")
            for row in opened._connection.execute(f"PRAGMA table_info({table})")
        }
    connection.close()

    assert columns == {
        "session_id",
        "started_at",
        "ended_at",
        "ended_reason",
        "correlation_id",
        "turn_count",
        "ordinal",
        "role",
        "text",
        "at",
        "latency_ms",
        "decision_type",
    }


def test_the_schema_is_versioned_like_the_other_four_stores() -> None:
    with SqliteVoiceSessionRepository.open(IN_MEMORY_DATABASE) as opened:
        version = opened._connection.execute("PRAGMA user_version").fetchone()[0]

    assert version == 1


def test_a_closed_repository_reports_a_domain_error(
    repository: SqliteVoiceSessionRepository,
) -> None:
    repository.close()

    with pytest.raises(VoiceRepositoryError):
        repository.save(_session())


def test_opening_an_impossible_path_is_an_infrastructure_error(tmp_path: object) -> None:
    with pytest.raises(VoiceRepositoryError):
        SqliteVoiceSessionRepository.open("/dev/null/voice.db")
