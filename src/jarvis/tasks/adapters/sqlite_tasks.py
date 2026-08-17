"""Repositório de tarefas em background, em SQLite.

Sexto banco do projeto (`tasks.db`), mesmo critério dos anteriores
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): um componente,
um schema, um `user_version`. A `ActionRequest` embutida é imutável depois de
gravada — trigger que aborta `UPDATE` das colunas de conteúdo, mesma garantia
de `sqlite_actions.py`.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.events.event import JsonValue
from jarvis.execution.model import ActionRequest, Actor
from jarvis.tasks.errors import TaskReadError, TaskRepositoryError, TaskWriteError, UnknownTaskError
from jarvis.tasks.model import BackgroundTask, TaskStatus

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS tasks (
    task_id          TEXT PRIMARY KEY,
    skill            TEXT NOT NULL,
    parameters       TEXT NOT NULL,
    correlation_id   TEXT NOT NULL,
    actor            TEXT NOT NULL,
    decision_id      TEXT,
    causation_id     TEXT,
    status           TEXT NOT NULL,
    attempts         INTEGER NOT NULL,
    max_attempts     INTEGER NOT NULL,
    next_attempt_at  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_error       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS tasks_status_idx ON tasks(status, next_attempt_at);

CREATE TRIGGER IF NOT EXISTS tasks_block_content_update
BEFORE UPDATE OF task_id, skill, parameters, correlation_id, actor, decision_id,
                 causation_id, created_at
ON tasks
BEGIN
    SELECT RAISE(ABORT, 'task request is immutable');
END;
"""

_COLUMNS: Final = (
    "task_id, skill, parameters, correlation_id, actor, decision_id, causation_id, "
    "status, attempts, max_attempts, next_attempt_at, created_at, updated_at, last_error"
)

_INSERT: Final = f"""
INSERT INTO tasks ({_COLUMNS})
VALUES (:task_id, :skill, :parameters, :correlation_id, :actor, :decision_id, :causation_id,
        :status, :attempts, :max_attempts, :next_attempt_at, :created_at, :updated_at, :last_error)
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM tasks"


def _format(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(raw: object, *, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise TaskReadError(f"{field_name} não é um texto ISO-8601")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise TaskReadError(f"{field_name} não é uma data ISO-8601 válida") from error


def _plain(value: JsonValue) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, str) or not isinstance(value, Sequence):
        return value
    return [_plain(item) for item in value]


class SqliteTaskRepository:
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
            raise TaskRepositoryError(
                f"não foi possível abrir o repositório de tarefas em {database}"
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

    def put(self, task: BackgroundTask) -> None:
        try:
            with self._connection:
                self._connection.execute(_INSERT, _to_record(task))
        except sqlite3.IntegrityError as error:
            raise TaskWriteError(f"tarefa {task.task_id} já registrada") from error
        except sqlite3.Error as error:
            raise TaskWriteError(f"falha ao registrar a tarefa {task.task_id}") from error

    def get(self, task_id: str) -> BackgroundTask | None:
        rows = self._query(f"{_SELECT} WHERE task_id = ?", (task_id,))
        return rows[0] if rows else None

    def list_by_status(
        self, status: TaskStatus, *, limit: int | None = None
    ) -> Sequence[BackgroundTask]:
        clause = "" if limit is None else " LIMIT ?"
        parameters: tuple[object, ...] = (status.value,)
        if limit is not None:
            parameters = (*parameters, limit)
        return self._query(f"{_SELECT} WHERE status = ? ORDER BY created_at{clause}", parameters)

    def due(self, *, moment: datetime, limit: int | None = None) -> Sequence[BackgroundTask]:
        clause = "" if limit is None else " LIMIT ?"
        parameters: tuple[object, ...] = (
            TaskStatus.PENDING.value,
            TaskStatus.RETRYING.value,
            _format(moment),
        )
        if limit is not None:
            parameters = (*parameters, limit)
        return self._query(
            f"{_SELECT} WHERE status IN (?, ?) AND next_attempt_at <= ? "
            f"ORDER BY next_attempt_at{clause}",
            parameters,
        )

    def mark_running(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        self._update(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (TaskStatus.RUNNING.value, _format(moment), task_id),
            task_id=task_id,
        )
        return self._reload(task_id)

    def mark_succeeded(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        self._update(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (TaskStatus.SUCCEEDED.value, _format(moment), task_id),
            task_id=task_id,
        )
        return self._reload(task_id)

    def mark_failed(self, task_id: str, *, moment: datetime, error: str) -> BackgroundTask:
        self._update(
            "UPDATE tasks SET status = ?, last_error = ?, updated_at = ? WHERE task_id = ?",
            (TaskStatus.FAILED.value, error, _format(moment), task_id),
            task_id=task_id,
        )
        return self._reload(task_id)

    def schedule_retry(
        self, task_id: str, *, moment: datetime, next_attempt_at: datetime, error: str
    ) -> BackgroundTask:
        self._update(
            "UPDATE tasks SET status = ?, attempts = attempts + 1, next_attempt_at = ?, "
            "last_error = ?, updated_at = ? WHERE task_id = ?",
            (
                TaskStatus.RETRYING.value,
                _format(next_attempt_at),
                error,
                _format(moment),
                task_id,
            ),
            task_id=task_id,
        )
        return self._reload(task_id)

    def cancel(self, task_id: str, *, moment: datetime) -> BackgroundTask:
        self._update(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (TaskStatus.CANCELLED.value, _format(moment), task_id),
            task_id=task_id,
        )
        return self._reload(task_id)

    def _update(self, sql: str, parameters: tuple[object, ...], *, task_id: str) -> None:
        try:
            with self._connection:
                cursor = self._connection.execute(sql, parameters)
        except sqlite3.Error as error:
            raise TaskWriteError(f"falha ao atualizar a tarefa {task_id}") from error
        if cursor.rowcount == 0:
            raise UnknownTaskError(f"tarefa não registrada: {task_id}")

    def _reload(self, task_id: str) -> BackgroundTask:
        found = self.get(task_id)
        if found is None:  # pragma: no cover - a linha acabou de ser atualizada
            raise UnknownTaskError(f"tarefa não registrada: {task_id}")
        return found

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[BackgroundTask]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise TaskReadError("falha ao consultar as tarefas") from error
        return [_from_record(dict(row)) for row in rows]


def _to_record(task: BackgroundTask) -> dict[str, object]:
    request = task.request
    return {
        "task_id": task.task_id,
        "skill": request.skill,
        "parameters": json.dumps(_plain(request.parameters), ensure_ascii=False, sort_keys=True),
        "correlation_id": request.correlation_id,
        "actor": request.actor.value,
        "decision_id": request.decision_id,
        "causation_id": request.causation_id,
        "status": task.status.value,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "next_attempt_at": _format(task.next_attempt_at),
        "created_at": _format(task.created_at),
        "updated_at": _format(task.updated_at),
        "last_error": task.last_error,
    }


def _optional_text(raw: object) -> str | None:
    return None if raw is None else str(raw)


def _from_record(row: Mapping[str, object]) -> BackgroundTask:
    raw_parameters = row["parameters"]
    if not isinstance(raw_parameters, str):
        raise TaskReadError("parameters não é um documento JSON")
    try:
        decoded: object = json.loads(raw_parameters)
    except json.JSONDecodeError as error:
        raise TaskReadError("parameters não é JSON válido") from error
    if not isinstance(decoded, dict):
        raise TaskReadError("parameters precisa ser um objeto JSON")

    try:
        status = TaskStatus(str(row["status"]))
        actor = Actor(str(row["actor"]))
    except ValueError as error:
        raise TaskReadError("status ou actor desconhecido") from error

    request = ActionRequest(
        skill=str(row["skill"]),
        parameters=decoded,
        correlation_id=str(row["correlation_id"]),
        actor=actor,
        decision_id=_optional_text(row["decision_id"]),
        causation_id=_optional_text(row["causation_id"]),
    )
    return BackgroundTask(
        task_id=str(row["task_id"]),
        request=request,
        status=status,
        attempts=int(row["attempts"]),  # type: ignore[call-overload]
        max_attempts=int(row["max_attempts"]),  # type: ignore[call-overload]
        next_attempt_at=_parse(row["next_attempt_at"], field_name="next_attempt_at"),
        created_at=_parse(row["created_at"], field_name="created_at"),
        updated_at=_parse(row["updated_at"], field_name="updated_at"),
        last_error=str(row["last_error"]),
    )
