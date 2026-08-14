"""O que a Fase 6 promete não vazar, verificado.

A fase aumenta a superfície de privacidade do Jarvis mais que qualquer outra:
áudio do ambiente, transcrição do que foi dito, e uma terceira e quarta
credencial. As cinco afirmações abaixo são o que impede isso de virar promessa.
"""

import ast
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from jarvis import cli
from jarvis.interface.viewmodel import safe_summary
from jarvis.voice.adapters.sqlite_sessions import IN_MEMORY_DATABASE, SqliteVoiceSessionRepository
from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn
from tests.interface_doubles import external_event
from tests.voice_doubles import EPOCH

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"

#: Tudo que um payload de evento de voz pode conter. Nada aqui é conteúdo.
ALLOWED_EVENT_KEYS = {"session_id", "turn_count", "reason", "duration_ms"}

#: Nomes que **não** podem aparecer num `extra=` de log da camada de voz: são o
#: que a pessoa disse, o que o agente respondeu, e os bytes do microfone.
FORBIDDEN_LOG_KEYS = {"text", "transcript", "reply", "data", "clip", "audio", "content", "api_key"}


def _modules(root: Path) -> Iterator[Path]:
    yield from sorted(root.rglob("*.py"))


def _tree(module: Path) -> ast.Module:
    return ast.parse(module.read_text(encoding="utf-8"), filename=str(module))


def test_only_the_composition_root_reads_a_secret() -> None:
    """`get_secret_value` fora do root significaria uma credencial viajando por
    um módulo que loga (contracts §12)."""
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in _modules(SOURCE_ROOT)
        if module.name != "cli.py"
        and any(
            isinstance(node, ast.Attribute) and node.attr == "get_secret_value"
            for node in ast.walk(_tree(module))
        )
    ]

    assert offenders == []


def test_no_voice_log_carries_what_was_said() -> None:
    offenders: list[str] = []
    for module in _modules(SOURCE_ROOT / "voice"):
        for node in ast.walk(_tree(module)):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and key.value in FORBIDDEN_LOG_KEYS:
                        offenders.append(f"{module.name}:{key.value}")

    assert offenders == []


def test_a_voice_event_carries_identity_and_nothing_else() -> None:
    session = (
        VoiceSession(session_id="s-1", started_at=EPOCH)
        .append(VoiceTurn(role=TurnRole.USER, text="minha senha é 1234", at=EPOCH))
        .append(VoiceTurn(role=TurnRole.ASSISTANT, text="não vou repetir isso", at=EPOCH))
        .end(at=EPOCH, reason="timeout")
    )

    for started in (True, False):
        event = cli.voice_session_event(session, started=started)
        body = json.dumps(dict(event.payload), ensure_ascii=False)

        assert set(event.payload) <= ALLOWED_EVENT_KEYS
        assert "senha" not in body
        assert "repetir" not in body


def test_the_voice_store_has_no_column_for_audio() -> None:
    with SqliteVoiceSessionRepository.open(IN_MEMORY_DATABASE) as repository:
        columns = {
            str(row[1])
            for table in ("voice_sessions", "voice_turns")
            for row in repository._connection.execute(f"PRAGMA table_info({table})")
        }

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


def test_the_panel_never_echoes_the_payload_of_an_external_event() -> None:
    """Um evento de fora pode carregar corpo de e-mail ou trecho de arquivo. A
    linha do tempo mostra o tipo, e mais nada."""
    recorded = external_event(
        payload={"subject": "confidencial", "body": "número do cartão 4111 1111 1111 1111"}
    )

    summary = safe_summary(recorded)

    assert summary == "email.received"
    assert "4111" not in summary
    assert "confidencial" not in summary


def test_no_audio_ever_reaches_the_disk_through_the_repository() -> None:
    # O único caminho de escrita da camada de voz é o repositório de sessões, e
    # ele só aceita texto: os bytes não têm por onde entrar.
    session = VoiceSession(session_id="s-2", started_at=EPOCH).append(
        VoiceTurn(role=TurnRole.USER, text="oi", at=EPOCH)
    )

    with SqliteVoiceSessionRepository.open(IN_MEMORY_DATABASE) as repository:
        repository.save(session)
        rows = repository._connection.execute("SELECT * FROM voice_turns").fetchall()

    assert all(not isinstance(value, sqlite3.Binary | bytes) for row in rows for value in row)
