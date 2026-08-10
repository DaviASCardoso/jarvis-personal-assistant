"""Repositório de snapshots de contexto em SQLite.

Segue o padrão que a Fase 1 já estabeleceu
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): `sqlite3` da
biblioteca padrão, atrás de um port, sem serviço externo. Fica em um
**banco próprio** (`context.db`) e não numa tabela extra de `events.db`: os dois
componentes versionam schema de forma independente, e o Context Engine não tem por
que tocar no `user_version` do Event Store.

Duas propriedades são impostas pelo banco, não por disciplina de código:

- **imutabilidade do conteúdo** — trigger que aborta `UPDATE` nas colunas de
  conteúdo, e outro que aborta qualquer `DELETE`;
- **expiração sem perda** — expirar preenche `expired_at`, a única coluna mutável.
  O registro continua no banco e continua legível com `include_expired=True`.
"""

import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.context.adapters.snapshot_serialization import (
    format_timestamp,
    from_record,
    to_record,
)
from jarvis.context.errors import (
    ContextSnapshotError,
    ContextSnapshotReadError,
    ContextSnapshotWriteError,
)
from jarvis.context.snapshot import ContextSnapshot

logger = logging.getLogger(__name__)

IN_MEMORY_DATABASE: Final = ":memory:"

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS context_snapshots (
    sequence       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    TEXT    NOT NULL UNIQUE,
    captured_at    TEXT    NOT NULL,
    schema_version INTEGER NOT NULL,
    fingerprint    TEXT    NOT NULL,
    document       TEXT    NOT NULL,
    expired_at     TEXT
);

CREATE INDEX IF NOT EXISTS context_snapshots_captured_at_idx
    ON context_snapshots(captured_at);

CREATE TRIGGER IF NOT EXISTS context_snapshots_block_content_update
BEFORE UPDATE OF snapshot_id, captured_at, schema_version, fingerprint, document
ON context_snapshots
BEGIN
    SELECT RAISE(ABORT, 'context snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS context_snapshots_block_delete
BEFORE DELETE ON context_snapshots
BEGIN
    SELECT RAISE(ABORT, 'context snapshots are never deleted');
END;
"""

_COLUMNS: Final = "snapshot_id, captured_at, schema_version, fingerprint, document"

_INSERT: Final = f"""
INSERT INTO context_snapshots ({_COLUMNS})
VALUES (:snapshot_id, :captured_at, :schema_version, :fingerprint, :document)
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM context_snapshots"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqliteContextSnapshotRepository:
    """Implementação de `ContextSnapshotRepository` sobre SQLite.

    Nenhum tipo do driver (`Connection`, `Row`, cursor) atravessa a fronteira: o
    Core só vê `ContextSnapshot`.
    """

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._clock = clock

    @classmethod
    def open(cls, database: Path | str, *, clock: Callable[[], datetime] = _utc_now) -> Self:
        try:
            if isinstance(database, Path):
                database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database)
            connection.executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as error:
            raise ContextSnapshotError(
                f"não foi possível abrir o repositório de snapshots em {database}"
            ) from error
        return cls(connection, clock=clock)

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

    def save(self, snapshot: ContextSnapshot) -> None:
        record = to_record(snapshot)
        try:
            with self._connection:
                self._connection.execute(_INSERT, dict(record))
        except sqlite3.Error as error:
            raise ContextSnapshotWriteError(
                f"falha ao persistir o snapshot {snapshot.snapshot_id}"
            ) from error

    def latest(self) -> ContextSnapshot | None:
        found = self._query(
            f"{_SELECT} WHERE expired_at IS NULL ORDER BY sequence DESC LIMIT 1", ()
        )
        return found[0] if found else None

    def read_captured_between(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]:
        expiry_clause = "" if include_expired else " AND expired_at IS NULL"
        limit_clause = "" if limit is None else " LIMIT ?"
        parameters: tuple[object, ...] = (format_timestamp(start), format_timestamp(end))
        if limit is not None:
            parameters = (*parameters, limit)
        return self._query(
            f"{_SELECT} WHERE captured_at >= ? AND captured_at < ?{expiry_clause} "
            f"ORDER BY sequence{limit_clause}",
            parameters,
        )

    def expire_before(self, cutoff: datetime) -> int:
        """Marca — nunca apaga. `expired_at` é a única coluna que o trigger deixa mudar."""
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "UPDATE context_snapshots SET expired_at = ? "
                    "WHERE captured_at < ? AND expired_at IS NULL",
                    (format_timestamp(self._clock()), format_timestamp(cutoff)),
                )
                expired = cursor.rowcount
        except sqlite3.Error as error:
            raise ContextSnapshotWriteError("falha ao expirar snapshots") from error

        logger.info(
            "context.snapshots_marked_expired",
            extra={"cutoff": format_timestamp(cutoff), "expired": expired},
        )
        return expired

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[ContextSnapshot]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise ContextSnapshotReadError("falha ao consultar os snapshots") from error
        return [from_record(dict(row)) for row in rows]
