"""Repositório de checkpoints do Goal Pursuit Loop, em SQLite.

Sétimo banco do projeto (`pursuits.db`), mesmo critério dos anteriores
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): um componente,
um schema, um `user_version`. `pursuit_id`/`goal`/`conversation_id`/
`created_at` são imutáveis depois de gravados — trigger que aborta `UPDATE`
dessas colunas, mesma garantia de `sqlite_tasks.py`.
"""

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.events.event import JsonValue
from jarvis.pursuits.errors import (
    PursuitReadError,
    PursuitRepositoryError,
    PursuitWriteError,
    UnknownPursuitError,
)
from jarvis.pursuits.model import PursuitState, PursuitStatus

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS pursuits (
    pursuit_id          TEXT PRIMARY KEY,
    goal                TEXT NOT NULL,
    conversation_id     TEXT NOT NULL,
    max_steps           INTEGER NOT NULL,
    step                INTEGER NOT NULL,
    status              TEXT NOT NULL,
    last_action_result  TEXT,
    previous_proposal   TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS pursuits_block_identity_update
BEFORE UPDATE OF pursuit_id, goal, conversation_id, created_at
ON pursuits
BEGIN
    SELECT RAISE(ABORT, 'pursuit identity is immutable');
END;
"""

_COLUMNS: Final = (
    "pursuit_id, goal, conversation_id, max_steps, step, status, "
    "last_action_result, previous_proposal, created_at, updated_at"
)

_INSERT: Final = f"""
INSERT INTO pursuits ({_COLUMNS})
VALUES (:pursuit_id, :goal, :conversation_id, :max_steps, :step, :status,
        :last_action_result, :previous_proposal, :created_at, :updated_at)
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM pursuits"


def _format(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(raw: object, *, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise PursuitReadError(f"{field_name} não é um texto ISO-8601")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise PursuitReadError(f"{field_name} não é uma data ISO-8601 válida") from error


def _dump(value: Mapping[str, JsonValue] | None) -> str | None:
    return None if value is None else json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def _load(raw: object, *, field_name: str) -> Mapping[str, JsonValue] | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise PursuitReadError(f"{field_name} não é um documento JSON")
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PursuitReadError(f"{field_name} não é JSON válido") from error
    if not isinstance(decoded, dict):
        raise PursuitReadError(f"{field_name} precisa ser um objeto JSON")
    return decoded


class SqlitePursuitRepository:
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
            raise PursuitRepositoryError(
                f"não foi possível abrir o repositório de pursuits em {database}"
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

    def put(self, pursuit: PursuitState) -> None:
        try:
            with self._connection:
                self._connection.execute(_INSERT, _to_record(pursuit))
        except sqlite3.IntegrityError as error:
            raise PursuitWriteError(f"pursuit {pursuit.pursuit_id} já registrado") from error
        except sqlite3.Error as error:
            raise PursuitWriteError(f"falha ao registrar o pursuit {pursuit.pursuit_id}") from error

    def get(self, pursuit_id: str) -> PursuitState | None:
        rows = self._query(f"{_SELECT} WHERE pursuit_id = ?", (pursuit_id,))
        return rows[0] if rows else None

    def advance(
        self,
        pursuit_id: str,
        *,
        step: int,
        status: PursuitStatus,
        last_action_result: Mapping[str, JsonValue] | None,
        previous_proposal: Mapping[str, JsonValue] | None,
        moment: datetime,
    ) -> PursuitState:
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "UPDATE pursuits SET step = ?, status = ?, last_action_result = ?, "
                    "previous_proposal = ?, updated_at = ? WHERE pursuit_id = ?",
                    (
                        step,
                        status.value,
                        _dump(last_action_result),
                        _dump(previous_proposal),
                        _format(moment),
                        pursuit_id,
                    ),
                )
        except sqlite3.Error as error:
            raise PursuitWriteError(f"falha ao atualizar o pursuit {pursuit_id}") from error
        if cursor.rowcount == 0:
            raise UnknownPursuitError(f"pursuit não registrado: {pursuit_id}")
        return self._reload(pursuit_id)

    def _reload(self, pursuit_id: str) -> PursuitState:
        found = self.get(pursuit_id)
        if found is None:  # pragma: no cover - a linha acabou de ser atualizada
            raise UnknownPursuitError(f"pursuit não registrado: {pursuit_id}")
        return found

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[PursuitState]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise PursuitReadError("falha ao consultar os pursuits") from error
        return [_from_record(dict(row)) for row in rows]


def _to_record(pursuit: PursuitState) -> dict[str, object]:
    return {
        "pursuit_id": pursuit.pursuit_id,
        "goal": pursuit.goal,
        "conversation_id": pursuit.conversation_id,
        "max_steps": pursuit.max_steps,
        "step": pursuit.step,
        "status": pursuit.status.value,
        "last_action_result": _dump(pursuit.last_action_result),
        "previous_proposal": _dump(pursuit.previous_proposal),
        "created_at": _format(pursuit.created_at),
        "updated_at": _format(pursuit.updated_at),
    }


def _from_record(row: Mapping[str, object]) -> PursuitState:
    try:
        status = PursuitStatus(str(row["status"]))
    except ValueError as error:
        raise PursuitReadError("status desconhecido") from error

    return PursuitState(
        pursuit_id=str(row["pursuit_id"]),
        goal=str(row["goal"]),
        conversation_id=str(row["conversation_id"]),
        max_steps=int(row["max_steps"]),  # type: ignore[call-overload]
        step=int(row["step"]),  # type: ignore[call-overload]
        status=status,
        last_action_result=_load(row["last_action_result"], field_name="last_action_result"),
        previous_proposal=_load(row["previous_proposal"], field_name="previous_proposal"),
        created_at=_parse(row["created_at"], field_name="created_at"),
        updated_at=_parse(row["updated_at"], field_name="updated_at"),
    )
