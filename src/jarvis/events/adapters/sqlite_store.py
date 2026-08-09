"""Event Store persistente em SQLite.

Ver [ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md) para por que SQLite,
e não PostgreSQL ou um log de arquivo. Três propriedades do contrato de evento são
impostas pelo próprio banco, e não por disciplina de código:

- **identidade e idempotência** — `UNIQUE(event_id)` + `ON CONFLICT DO NOTHING`;
- **imutabilidade** — triggers que abortam qualquer `UPDATE` ou `DELETE`;
- **ordenação estável de leitura** — `sequence` autoincremental, que desempata
  `recorded_at` idênticos.
"""

import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.events.adapters.serialization import (
    event_fingerprint,
    format_timestamp,
    from_record,
    to_record,
)
from jarvis.events.errors import EventAppendError, EventReadError, EventStoreError
from jarvis.events.event import Event, RecordedEvent
from jarvis.events.ports import AppendResult

logger = logging.getLogger(__name__)

IN_MEMORY_DATABASE: Final = ":memory:"

# Índices: um por consulta exigida pela fase (por tipo, por correlação, temporal).
# Triggers: imutabilidade em ADR-0004 vale também na persistência, não só no domínio.
_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS events (
    sequence       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT    NOT NULL UNIQUE,
    event_type     TEXT    NOT NULL,
    occurred_at    TEXT    NOT NULL,
    recorded_at    TEXT    NOT NULL,
    source         TEXT    NOT NULL,
    schema_version INTEGER NOT NULL,
    correlation_id TEXT    NOT NULL,
    causation_id   TEXT,
    payload        TEXT    NOT NULL,
    metadata       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS events_event_type_idx     ON events(event_type);
CREATE INDEX IF NOT EXISTS events_correlation_id_idx ON events(correlation_id);
CREATE INDEX IF NOT EXISTS events_occurred_at_idx    ON events(occurred_at);

CREATE TRIGGER IF NOT EXISTS events_block_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are immutable');
END;

CREATE TRIGGER IF NOT EXISTS events_block_delete BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are immutable');
END;
"""

_COLUMNS: Final = (
    "event_id, event_type, occurred_at, recorded_at, source, "
    "schema_version, correlation_id, causation_id, payload, metadata"
)

_INSERT: Final = f"""
INSERT INTO events ({_COLUMNS})
VALUES (:event_id, :event_type, :occurred_at, :recorded_at, :source,
        :schema_version, :correlation_id, :causation_id, :payload, :metadata)
ON CONFLICT(event_id) DO NOTHING
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM events"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqliteEventStore:
    """Implementação de `EventStore` sobre SQLite.

    Nenhum tipo do driver (`Connection`, `Row`, cursor) atravessa a fronteira: o
    Core só vê `Event`, `RecordedEvent` e `AppendResult`.
    """

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self._clock = clock

    @classmethod
    def open(cls, database: Path | str, *, clock: Callable[[], datetime] = _utc_now) -> Self:
        """Abre o banco e garante o schema; criar o schema é idempotente.

        Um `Path` tem o diretório-pai criado se faltar; use `IN_MEMORY_DATABASE`
        para um store efêmero.
        """
        try:
            if isinstance(database, Path):
                database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database)
            connection.executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as error:
            raise EventStoreError(f"não foi possível abrir o event store em {database}") from error
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

    def append(self, event: Event) -> AppendResult:
        """Registra o evento, atribuindo `recorded_at`.

        Reinserir um `event_id` já conhecido é no-op (contrato §5): devolve o
        registro original, com o `recorded_at` da primeira vez, e `is_duplicate`.
        """
        record = to_record(event, self._clock())
        try:
            with self._connection:
                cursor = self._connection.execute(_INSERT, dict(record))
                inserted = cursor.rowcount == 1
        except sqlite3.Error as error:
            raise EventAppendError(f"falha ao registrar o evento {event.event_id}") from error

        stored = self.get(event.event_id)
        if stored is None:  # pragma: no cover - só ocorreria com escrita perdida
            raise EventAppendError(f"o evento {event.event_id} sumiu logo após ser registrado")

        if not inserted:
            self._warn_if_divergent(event, stored)
            logger.info("event.duplicate", extra=_log_fields(stored))
            return AppendResult(event=stored, is_duplicate=True)

        logger.info("event.recorded", extra=_log_fields(stored))
        return AppendResult(event=stored, is_duplicate=False)

    def get(self, event_id: str) -> RecordedEvent | None:
        rows = self._query(f"{_SELECT} WHERE event_id = ?", (event_id,))
        return rows[0] if rows else None

    def read_by_type(self, event_type: str, *, limit: int | None = None) -> Sequence[RecordedEvent]:
        return self._query(
            f"{_SELECT} WHERE event_type = ? ORDER BY sequence{_limit_clause(limit)}",
            _with_limit((event_type,), limit),
        )

    def read_by_correlation(self, correlation_id: str) -> Sequence[RecordedEvent]:
        """Toda a cadeia causal, na ordem em que foi registrada."""
        return self._query(
            f"{_SELECT} WHERE correlation_id = ? ORDER BY sequence", (correlation_id,)
        )

    def read_occurred_between(
        self, start: datetime, end: datetime, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]:
        """Filtra tempo de domínio (`occurred_at`) no intervalo semiaberto."""
        return self._query(
            f"{_SELECT} WHERE occurred_at >= ? AND occurred_at < ? "
            f"ORDER BY sequence{_limit_clause(limit)}",
            _with_limit((format_timestamp(start), format_timestamp(end)), limit),
        )

    def read_latest(self, *, limit: int) -> Sequence[RecordedEvent]:
        """Os `limit` eventos mais recentes, devolvidos em ordem de persistência."""
        newest_first = self._query(f"{_SELECT} ORDER BY sequence DESC LIMIT ?", (limit,))
        return list(reversed(newest_first))

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[RecordedEvent]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise EventReadError("falha ao consultar o event store") from error
        return [from_record(dict(row)) for row in rows]

    def _warn_if_divergent(self, incoming: Event, stored: RecordedEvent) -> None:
        """Avisa quando um `event_id` conhecido reaparece com outro conteúdo.

        O registro original prevalece — imutabilidade não admite exceção. Mas
        divergência costuma indicar bug no producer, e silêncio total esconderia
        isso. Compara resumos, nunca o conteúdo (`PHASE-1.md §20`).
        """
        incoming_fingerprint = event_fingerprint(incoming)
        stored_fingerprint = event_fingerprint(stored.event)
        if incoming_fingerprint != stored_fingerprint:
            logger.warning(
                "event.duplicate_divergent",
                extra=_log_fields(stored)
                | {
                    "stored_fingerprint": stored_fingerprint,
                    "incoming_fingerprint": incoming_fingerprint,
                },
            )


def _limit_clause(limit: int | None) -> str:
    return "" if limit is None else " LIMIT ?"


def _with_limit(parameters: tuple[object, ...], limit: int | None) -> tuple[object, ...]:
    return parameters if limit is None else (*parameters, limit)


def _log_fields(recorded: RecordedEvent) -> dict[str, object]:
    """Metadados de diagnóstico — nunca payload nem metadata (`PHASE-1.md §20`)."""
    return {
        "event_id": recorded.event.event_id,
        "event_type": recorded.event.event_type,
        "source": recorded.event.source,
        "correlation_id": recorded.event.correlation_id,
        "causation_id": recorded.event.causation_id,
        "recorded_at": format_timestamp(recorded.recorded_at),
    }
