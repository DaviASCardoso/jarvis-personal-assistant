"""Os comandos de voz e do painel no composition root.

Nenhum teste aqui abre microfone, alto-falante ou fala com a nuvem: os providers
são substituídos por `monkeypatch` nos builders de `cli.py`, que é exatamente o
que a fronteira de ports existe para permitir.
"""

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.cli import main
from jarvis.voice.adapters.wave_io import encode_wav
from jarvis.voice.audio import PcmClip
from jarvis.voice.errors import AudioDeviceError
from tests.voice_doubles import (
    ScriptedSpeechToText,
    ScriptedTextToSpeech,
    pcm_tone,
    tts_error,
)


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "CRITICAL")
    return data_dir


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_GROQ_API_KEY", "chave-de-teste")
    monkeypatch.setenv("JARVIS_GOOGLE_TTS_API_KEY", "chave-de-teste")


def wav(path: Path, *, seconds: float = 0.3) -> Path:
    path.write_bytes(encode_wav(PcmClip(data=pcm_tone(seconds))))
    return path


# --- info e ajuda ------------------------------------------------------------


def test_info_reports_the_fifth_store(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info"]) == 0

    assert "voice.db" in capsys.readouterr().out


def test_voice_without_a_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["voice"]) == 0
    assert "usage: jarvis voice" in capsys.readouterr().out


def test_panel_without_a_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["panel"]) == 0
    assert "usage: jarvis panel" in capsys.readouterr().out


# --- credenciais -------------------------------------------------------------


def test_speaking_without_a_credential_fails_with_an_instruction(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Código 1 pelo mesmo motivo que uma `JARVIS_GEMINI_API_KEY` ausente:
    # credencial que falta é indisponibilidade do provider, não entrada inválida.
    assert main(["voice", "say", "olá"]) == 1

    assert "JARVIS_GOOGLE_TTS_API_KEY" in capsys.readouterr().err


def test_transcribing_without_a_credential_fails_with_an_instruction(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["voice", "transcribe", str(wav(tmp_path / "a.wav"))]) == 1

    assert "JARVIS_GROQ_API_KEY" in capsys.readouterr().err


def test_the_credential_is_read_only_by_the_composition_root(
    monkeypatch: pytest.MonkeyPatch, credentials: None
) -> None:
    # Se o segredo saísse daqui, ele chegaria a um adapter que loga — e o
    # `build_*` é o único lugar do sistema que chama `get_secret_value`.
    captured: list[str] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("não deve haver rede")
    )

    def build(settings: object) -> ScriptedTextToSpeech:
        captured.append("tts")
        return ScriptedTextToSpeech()

    monkeypatch.setattr(cli, "build_tts", build)

    main(["voice", "say", "oi", "--out", "saida.wav"])

    assert captured == ["tts"]


# --- say / transcribe --------------------------------------------------------


def test_say_writes_a_playable_wav(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_tts", lambda settings: ScriptedTextToSpeech())
    destination = tmp_path / "out" / "fala.wav"

    assert main(["voice", "say", "bom dia", "--out", str(destination)]) == 0

    assert destination.read_bytes().startswith(b"RIFF")
    assert "gravado" in capsys.readouterr().out


def test_say_without_out_uses_the_speaker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tests.voice_doubles import FakeAudioSource, RecordingAudioSink

    sink = RecordingAudioSink()
    monkeypatch.setattr(cli, "build_tts", lambda settings: ScriptedTextToSpeech())
    monkeypatch.setattr(cli, "build_audio_io", lambda settings: (FakeAudioSource(), sink))

    assert main(["voice", "say", "bom dia"]) == 0

    assert len(sink.played) == 1
    assert "falado" in capsys.readouterr().out


def test_a_missing_audio_backend_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], credentials: None
) -> None:
    # Descobrir a falta do extra por `ImportError` seria hostil.
    monkeypatch.setattr(cli, "build_tts", lambda settings: ScriptedTextToSpeech())

    def refuse(settings: object) -> None:
        raise AudioDeviceError("áudio indisponível: instale o extra com `uv sync --extra voice`")

    monkeypatch.setattr(cli, "build_audio_io", refuse)

    assert main(["voice", "say", "oi"]) == 1
    assert "uv sync --extra voice" in capsys.readouterr().err


def test_devices_without_the_audio_backend_says_how_to_install_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Achado da revisão de release da 8.10: `voice devices` importava o
    backend direto, sem a mesma tradução de `ImportError` que `build_audio_io`
    já dá às outras Skills de voz — um `ModuleNotFoundError` cru vazava."""
    monkeypatch.setitem(sys.modules, "jarvis.voice.adapters.sounddevice_audio", None)

    assert main(["voice", "devices"]) == 1
    assert "uv sync --extra voice" in capsys.readouterr().err


def test_transcribe_reads_a_wav_from_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_stt", lambda settings: ScriptedSpeechToText(["que horas são"]))

    assert main(["voice", "transcribe", str(wav(tmp_path / "a.wav"))]) == 0

    assert "que horas são" in capsys.readouterr().out


def test_transcribing_a_missing_file_is_invalid_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_stt", lambda settings: ScriptedSpeechToText([]))

    assert main(["voice", "transcribe", "nao-existe.wav"]) == 2
    assert "não encontrado" in capsys.readouterr().err


def test_a_synthesis_failure_is_an_infrastructure_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "build_tts", lambda settings: ScriptedTextToSpeech(error=tts_error("provedor fora"))
    )

    assert main(["voice", "say", "oi", "--out", "x.wav"]) == 1


# --- sessões -----------------------------------------------------------------


def _seed_session(data_dir: Path) -> str:
    from jarvis.voice.adapters.sqlite_sessions import SqliteVoiceSessionRepository
    from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn
    from tests.voice_doubles import EPOCH

    session = (
        VoiceSession(session_id="s-1", started_at=EPOCH)
        .append(VoiceTurn(role=TurnRole.USER, text="que horas são", at=EPOCH))
        .append(VoiceTurn(role=TurnRole.ASSISTANT, text="nove e vinte", at=EPOCH))
        .end(at=EPOCH, reason="timeout")
    )
    with SqliteVoiceSessionRepository.open(data_dir / "voice.db") as sessions:
        sessions.save(session)
    return session.session_id


def test_listing_sessions_when_there_are_none(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["voice", "sessions", "list"]) == 0
    assert "nenhuma sessão" in capsys.readouterr().out


def test_listing_and_showing_a_session(
    isolated_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = _seed_session(isolated_data_dir)

    assert main(["voice", "sessions", "list"]) == 0
    assert session_id in capsys.readouterr().out

    assert main(["voice", "sessions", "show", session_id]) == 0
    output = capsys.readouterr().out
    assert "que horas são" in output
    assert "nove e vinte" in output


def test_showing_an_unknown_session_is_invalid_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["voice", "sessions", "show", "nao-existe"]) == 2
    assert "não encontrada" in capsys.readouterr().err


def test_purging_a_session_removes_its_transcripts(
    isolated_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = _seed_session(isolated_data_dir)

    assert main(["voice", "sessions", "purge", session_id]) == 0

    with sqlite3.connect(isolated_data_dir / "voice.db") as connection:
        turns = connection.execute("SELECT count(*) FROM voice_turns").fetchone()[0]
    assert turns == 0


def test_purging_everything_needs_the_explicit_flag(
    isolated_data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_session(isolated_data_dir)

    assert main(["voice", "sessions", "purge"]) == 2
    assert main(["voice", "sessions", "purge", "--all"]) == 0
    assert "apagadas 1" in capsys.readouterr().out


def test_the_voice_store_never_holds_audio(isolated_data_dir: Path) -> None:
    _seed_session(isolated_data_dir)

    with sqlite3.connect(isolated_data_dir / "voice.db") as connection:
        columns = {
            str(row[1])
            for table in ("voice_sessions", "voice_turns")
            for row in connection.execute(f"PRAGMA table_info({table})")
        }

    assert not {name for name in columns if "audio" in name or "pcm" in name or "wav" in name}


# --- painel ------------------------------------------------------------------


def test_the_panel_publishes_one_snapshot_and_exits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["panel", "serve", "--once"]) == 0

    assert "http://127.0.0.1" in capsys.readouterr().out


def test_the_panel_refuses_a_non_local_host(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("JARVIS_PANEL_HOST", "0.0.0.0")

    assert main(["panel", "serve", "--once"]) == 2
    assert "loopback" in capsys.readouterr().err


def test_running_with_neither_piece_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--no-voice", "--no-panel"]) == 2
    assert "nada a fazer" in capsys.readouterr().err


def test_the_panel_serves_the_state_of_a_real_store(
    monkeypatch: pytest.MonkeyPatch, isolated_data_dir: Path
) -> None:
    # Um evento de verdade, lido pelo painel de verdade — sem voz e sem rede.
    main(
        [
            "events",
            "emit",
            "--type",
            "email.received",
            "--source",
            "gmail-watcher",
            "--payload",
            '{"subject": "oi"}',
        ]
    )
    published: list[object] = []
    monkeypatch.setattr(
        cli.PanelBridge, "_publish", lambda self, snapshot: published.append(snapshot)
    )

    assert main(["panel", "serve", "--once"]) == 0

    snapshot = published[-1]
    assert [entry.event_type for entry in snapshot.timeline] == ["email.received"]  # type: ignore[attr-defined]


def test_voice_events_carry_identity_and_never_the_conversation() -> None:
    from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn
    from tests.voice_doubles import EPOCH

    session = (
        VoiceSession(session_id="s-1", started_at=EPOCH)
        .append(VoiceTurn(role=TurnRole.USER, text="segredo absoluto", at=EPOCH))
        .end(at=EPOCH, reason="timeout")
    )

    started = cli.voice_session_event(session, started=True)
    ended = cli.voice_session_event(session, started=False)

    assert set(started.payload) == {"session_id"}
    assert set(ended.payload) <= {"session_id", "turn_count", "reason", "duration_ms"}
    assert "segredo" not in json.dumps(dict(ended.payload))
    # Determinístico: republicar o mesmo marco é no-op no Event Store.
    assert cli.voice_session_event(session, started=True).event_id == started.event_id
    assert started.event_id != ended.event_id
