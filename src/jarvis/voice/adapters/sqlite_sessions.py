"""Sessões de voz em SQLite.

Quinto banco do projeto (`voice.db`), pelo mesmo critério dos quatro anteriores
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): um componente, um
schema, um `user_version`.

O que ele guarda é **estado operacional** (contracts §12): mutável, apagável, com
retenção. A alternativa — transcrições no Event Store — foi descartada em
[ADR-0025](../../../../docs/adr/0025-voice-transcripts-as-operational-state.md)
pelo mesmo motivo que o ADR-0014 tirou os parâmetros de ação de lá: um evento é
para sempre, e conversa é dado pessoal com validade curta.

**Não existe coluna de áudio.** Nem bytes, nem caminho, nem duração de gravação —
`tests/test_voice_privacy.py` compara a lista de colunas com um conjunto fechado.

`save` é upsert de propósito, ao contrário de `SqliteActionRepository.put`: uma
sessão cresce turno a turno e é salva várias vezes ao longo da conversa, enquanto
uma execução é registrada uma vez e nunca reescrita.
"""

import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.voice.errors import VoiceRepositoryError
from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn

logger = logging.getLogger(__name__)

IN_MEMORY_DATABASE: Final = ":memory:"

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS voice_sessions (
    session_id     TEXT PRIMARY KEY,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    ended_reason   TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL,
    turn_count     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS voice_turns (
    session_id     TEXT NOT NULL REFERENCES voice_sessions(session_id) ON DELETE CASCADE,
    ordinal        INTEGER NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    text           TEXT NOT NULL,
    at             TEXT NOT NULL,
    latency_ms     REAL,
    decision_type  TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (session_id, ordinal)
);

CREATE INDEX IF NOT EXISTS voice_sessions_started_idx
    ON voice_sessions (started_at DESC);
"""

_UPSERT_SESSION: Final = """
INSERT INTO voice_sessions (session_id, started_at, ended_at, ended_reason,
                            correlation_id, turn_count)
VALUES (:session_id, :started_at, :ended_at, :ended_reason, :correlation_id, :turn_count)
ON CONFLICT(session_id) DO UPDATE SET
    ended_at = excluded.ended_at,
    ended_reason = excluded.ended_reason,
    turn_count = excluded.turn_count
"""

_INSERT_TURN: Final = """
INSERT OR REPLACE INTO voice_turns (session_id, ordinal, role, text, at, latency_ms,
                                    decision_type, correlation_id)
VALUES (:session_id, :ordinal, :role, :text, :at, :latency_ms, :decision_type, :correlation_id)
"""


def _format(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _parse(raw: object, *, field_name: str) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise VoiceRepositoryError(f"{field_name} não é um texto ISO-8601")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise VoiceRepositoryError(f"{field_name} não é uma data ISO-8601 válida") from error


class SqliteVoiceSessionRepository:
    """Implementa `jarvis.voice.ports.VoiceSessionRepository`."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row

    @classmethod
    def open(cls, database: Path | str) -> Self:
        try:
            if isinstance(database, Path):
                database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database)
            connection.executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as error:
            raise VoiceRepositoryError(
                f"não foi possível abrir o repositório de sessões em {database}"
            ) from error
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def save(self, session: VoiceSession) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    _UPSERT_SESSION,
                    {
                        "session_id": session.session_id,
                        "started_at": _format(session.started_at),
                        "ended_at": _format(session.ended_at),
                        "ended_reason": session.ended_reason,
                        "correlation_id": session.correlation_id,
                        "turn_count": session.turn_count,
                    },
                )
                self._connection.executemany(
                    _INSERT_TURN,
                    [
                        {
                            "session_id": session.session_id,
                            "ordinal": ordinal,
                            "role": turn.role.value,
                            "text": turn.text,
                            "at": _format(turn.at),
                            "latency_ms": turn.latency_ms,
                            "decision_type": turn.decision_type,
                            "correlation_id": turn.correlation_id,
                        }
                        for ordinal, turn in enumerate(session.turns)
                    ],
                )
        except sqlite3.Error as error:
            raise VoiceRepositoryError(
                f"falha ao salvar a sessão de voz {session.session_id}"
            ) from error

    def get(self, session_id: str) -> VoiceSession | None:
        rows = self._query("SELECT * FROM voice_sessions WHERE session_id = ?", (session_id,))
        return rows[0] if rows else None

    def list(self, *, limit: int) -> Sequence[VoiceSession]:
        return self._query(
            "SELECT * FROM voice_sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        )

    def purge(self, session_id: str) -> bool:
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "DELETE FROM voice_sessions WHERE session_id = ?", (session_id,)
                )
        except sqlite3.Error as error:
            raise VoiceRepositoryError(f"falha ao apagar a sessão {session_id}") from error
        return cursor.rowcount > 0

    def purge_before(self, cutoff: datetime) -> int:
        """Retenção: o que começou antes do corte deixa de existir, com os turnos."""
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "DELETE FROM voice_sessions WHERE started_at < ?", (_format(cutoff),)
                )
        except sqlite3.Error as error:
            raise VoiceRepositoryError("falha ao aplicar a retenção de sessões") from error
        if cursor.rowcount:
            logger.info("voice.sessions_purged", extra={"purged": cursor.rowcount})
        return cursor.rowcount

    # `Sequence`, e não `list[...]`: dentro do corpo da classe o nome `list` já é
    # o método público acima, e a anotação resolveria para ele.
    def _query(self, sql: str, parameters: tuple[object, ...]) -> Sequence[VoiceSession]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
            return [self._build(dict(row)) for row in rows]
        except sqlite3.Error as error:
            raise VoiceRepositoryError("falha ao consultar as sessões de voz") from error

    def _build(self, row: dict[str, object]) -> VoiceSession:
        session_id = str(row["session_id"])
        started_at = _parse(row["started_at"], field_name="started_at")
        if started_at is None:
            raise VoiceRepositoryError("started_at não pode ser nulo")

        turns = self._connection.execute(
            "SELECT role, text, at, latency_ms, decision_type, correlation_id "
            "FROM voice_turns WHERE session_id = ? ORDER BY ordinal",
            (session_id,),
        ).fetchall()

        return VoiceSession(
            session_id=session_id,
            started_at=started_at,
            correlation_id=str(row["correlation_id"]),
            turns=tuple(self._turn(dict(turn)) for turn in turns),
            ended_at=_parse(row["ended_at"], field_name="ended_at"),
            ended_reason=str(row["ended_reason"]),
        )

    def _turn(self, row: dict[str, object]) -> VoiceTurn:
        at = _parse(row["at"], field_name="at")
        if at is None:
            raise VoiceRepositoryError("at não pode ser nulo")
        latency = row["latency_ms"]
        try:
            role = TurnRole(str(row["role"]))
        except ValueError as error:
            raise VoiceRepositoryError("papel de turno desconhecido") from error
        return VoiceTurn(
            role=role,
            text=str(row["text"]),
            at=at,
            latency_ms=float(latency) if isinstance(latency, int | float) else None,
            decision_type=str(row["decision_type"]),
            correlation_id=str(row["correlation_id"]),
        )
