"""Repositório de ações em SQLite.

Quarto banco do projeto (`actions.db`), pelo mesmo critério dos três anteriores
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): um componente, um
schema, um `user_version` — o Event Store não tem por que versionar a tabela de
ações, nem o contrário.

O que ele guarda é **estado operacional** (contracts §12): mutável, apagável, e a
única estrutura do sistema que contém os parâmetros de uma ação. Duas garantias
são impostas pelo banco, não por disciplina:

- **parâmetros são imutáveis** — trigger que aborta `UPDATE` das colunas de
  conteúdo. Mudá-los depois invalidaria o `parameters_fingerprint` que a
  confirmação e a aprovação usam para se amarrar a esta execução;
- **`put` não é upsert** — `execution_id` é chave primária, e reescrever uma
  execução existente falha em vez de sobrescrever silenciosamente.
"""

import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.events.event import JsonValue
from jarvis.execution.errors import (
    ActionReadError,
    ActionRepositoryError,
    ActionWriteError,
    UnknownExecutionError,
)
from jarvis.execution.model import Actor, ExecutionStatus, PendingAction

logger = logging.getLogger(__name__)

IN_MEMORY_DATABASE: Final = ":memory:"

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS actions (
    execution_id           TEXT PRIMARY KEY,
    skill                  TEXT NOT NULL,
    parameters             TEXT NOT NULL,
    parameters_fingerprint TEXT NOT NULL,
    actor                  TEXT NOT NULL,
    correlation_id         TEXT NOT NULL,
    causation_id           TEXT,
    decision_id            TEXT,
    status                 TEXT NOT NULL,
    reason                 TEXT NOT NULL DEFAULT '',
    requested_at           TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    expires_at             TEXT,
    confirmed_at           TEXT
);

CREATE INDEX IF NOT EXISTS actions_status_idx ON actions(status, requested_at);

CREATE TRIGGER IF NOT EXISTS actions_block_content_update
BEFORE UPDATE OF execution_id, skill, parameters, parameters_fingerprint,
                 actor, correlation_id, causation_id, decision_id, requested_at
ON actions
BEGIN
    SELECT RAISE(ABORT, 'action parameters are immutable');
END;
"""

_COLUMNS: Final = (
    "execution_id, skill, parameters, parameters_fingerprint, actor, correlation_id, "
    "causation_id, decision_id, status, reason, requested_at, updated_at, expires_at, confirmed_at"
)

_INSERT: Final = f"""
INSERT INTO actions ({_COLUMNS})
VALUES (:execution_id, :skill, :parameters, :parameters_fingerprint, :actor, :correlation_id,
        :causation_id, :decision_id, :status, :reason, :requested_at, :updated_at, :expires_at,
        :confirmed_at)
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM actions"


def _format(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat()


def _parse(raw: object, *, field_name: str) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ActionReadError(f"{field_name} não é um texto ISO-8601")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise ActionReadError(f"{field_name} não é uma data ISO-8601 válida") from error


def _require(moment: datetime | None, *, field_name: str) -> datetime:
    if moment is None:
        raise ActionReadError(f"{field_name} não pode ser nulo")
    return moment


class SqliteActionRepository:
    """Implementação de `ActionRepository` sobre SQLite.

    Nenhum tipo do driver atravessa a fronteira: o Core só vê `PendingAction`.
    """

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
            raise ActionRepositoryError(
                f"não foi possível abrir o repositório de ações em {database}"
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

    def put(self, pending: PendingAction) -> None:
        try:
            with self._connection:
                self._connection.execute(_INSERT, _to_record(pending))
        except sqlite3.IntegrityError as error:
            raise ActionWriteError(f"execução {pending.execution_id} já registrada") from error
        except sqlite3.Error as error:
            raise ActionWriteError(
                f"falha ao registrar a execução {pending.execution_id}"
            ) from error

    def get(self, execution_id: str) -> PendingAction | None:
        rows = self._query(f"{_SELECT} WHERE execution_id = ?", (execution_id,))
        return rows[0] if rows else None

    def list_by_status(
        self, status: ExecutionStatus, *, limit: int | None = None
    ) -> Sequence[PendingAction]:
        clause = "" if limit is None else " LIMIT ?"
        parameters: tuple[object, ...] = (status.value,)
        if limit is not None:
            parameters = (*parameters, limit)
        return self._query(f"{_SELECT} WHERE status = ? ORDER BY requested_at{clause}", parameters)

    def mark(
        self, execution_id: str, *, status: ExecutionStatus, moment: datetime, reason: str = ""
    ) -> PendingAction:
        self._update(
            "UPDATE actions SET status = ?, reason = ?, updated_at = ? WHERE execution_id = ?",
            (status.value, reason, _format(moment), execution_id),
            execution_id=execution_id,
        )
        return self._reload(execution_id)

    def confirm(self, execution_id: str, *, moment: datetime) -> PendingAction:
        self._update(
            "UPDATE actions SET confirmed_at = ?, updated_at = ? WHERE execution_id = ?",
            (_format(moment), _format(moment), execution_id),
            execution_id=execution_id,
        )
        return self._reload(execution_id)

    def expire_pending(self, *, moment: datetime) -> Sequence[PendingAction]:
        stamp = _format(moment)
        try:
            with self._connection:
                rows = self._connection.execute(
                    f"{_SELECT} WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                    (ExecutionStatus.AWAITING_CONFIRMATION.value, stamp),
                ).fetchall()
                if rows:
                    self._connection.execute(
                        "UPDATE actions SET status = ?, reason = ?, updated_at = ? "
                        "WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?",
                        (
                            ExecutionStatus.EXPIRED.value,
                            "confirmation_expired",
                            stamp,
                            ExecutionStatus.AWAITING_CONFIRMATION.value,
                            stamp,
                        ),
                    )
        except sqlite3.Error as error:
            raise ActionWriteError("falha ao expirar as ações pendentes") from error

        if rows:
            logger.info("action.pending_expired", extra={"expired": len(rows)})
        return [self._reload(str(row["execution_id"])) for row in rows]

    def _update(self, sql: str, parameters: tuple[object, ...], *, execution_id: str) -> None:
        try:
            with self._connection:
                cursor = self._connection.execute(sql, parameters)
        except sqlite3.Error as error:
            raise ActionWriteError(f"falha ao atualizar a execução {execution_id}") from error
        if cursor.rowcount == 0:
            raise UnknownExecutionError(f"execução não registrada: {execution_id}")

    def _reload(self, execution_id: str) -> PendingAction:
        found = self.get(execution_id)
        if found is None:  # pragma: no cover - a linha acabou de ser atualizada
            raise UnknownExecutionError(f"execução não registrada: {execution_id}")
        return found

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[PendingAction]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise ActionReadError("falha ao consultar as ações") from error
        return [_from_record(dict(row)) for row in rows]


def _to_record(pending: PendingAction) -> dict[str, object]:
    return {
        "execution_id": pending.execution_id,
        "skill": pending.skill,
        "parameters": json.dumps(_plain(pending.parameters), ensure_ascii=False, sort_keys=True),
        "parameters_fingerprint": pending.parameters_fingerprint,
        "actor": pending.actor.value,
        "correlation_id": pending.correlation_id,
        "causation_id": pending.causation_id,
        "decision_id": pending.decision_id,
        "status": pending.status.value,
        "reason": pending.reason,
        "requested_at": _format(pending.requested_at),
        "updated_at": _format(pending.updated_at),
        "expires_at": _format(pending.expires_at),
        "confirmed_at": _format(pending.confirmed_at),
    }


def _plain(value: JsonValue) -> object:
    """`MappingProxyType` e `tuple` não são serializáveis por `json` como estão."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, str) or not isinstance(value, Sequence):
        return value
    return [_plain(item) for item in value]


def _from_record(row: Mapping[str, object]) -> PendingAction:
    raw_parameters = row["parameters"]
    if not isinstance(raw_parameters, str):
        raise ActionReadError("parameters não é um documento JSON")
    try:
        decoded: object = json.loads(raw_parameters)
    except json.JSONDecodeError as error:
        raise ActionReadError("parameters não é JSON válido") from error
    if not isinstance(decoded, dict):
        raise ActionReadError("parameters precisa ser um objeto JSON")

    try:
        status = ExecutionStatus(str(row["status"]))
        actor = Actor(str(row["actor"]))
    except ValueError as error:
        raise ActionReadError("status ou actor desconhecido") from error

    return PendingAction(
        execution_id=str(row["execution_id"]),
        skill=str(row["skill"]),
        parameters=decoded,
        parameters_fingerprint=str(row["parameters_fingerprint"]),
        actor=actor,
        correlation_id=str(row["correlation_id"]),
        causation_id=_optional_text(row["causation_id"]),
        decision_id=_optional_text(row["decision_id"]),
        status=status,
        reason=str(row["reason"]),
        requested_at=_require(
            _parse(row["requested_at"], field_name="requested_at"), field_name="requested_at"
        ),
        updated_at=_require(
            _parse(row["updated_at"], field_name="updated_at"), field_name="updated_at"
        ),
        expires_at=_parse(row["expires_at"], field_name="expires_at"),
        confirmed_at=_parse(row["confirmed_at"], field_name="confirmed_at"),
    )


def _optional_text(raw: object) -> str | None:
    return None if raw is None else str(raw)
