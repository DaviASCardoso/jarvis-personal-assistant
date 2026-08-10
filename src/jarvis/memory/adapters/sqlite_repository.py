"""Repositório de memórias em SQLite.

Segue o padrão já estabelecido nas Fases 1 e 2
([ADR-0007](../../../../docs/adr/0007-sqlite-event-store.md)): `sqlite3` da
biblioteca padrão, atrás de um port, sem serviço externo. Fica em um **banco
próprio** (`memory.db`) — três componentes, três bancos, cada um versionando
schema de forma independente.

Uma propriedade é imposta pelo banco, não por disciplina de código: **o
conteúdo de uma memória é imutável.** Um trigger aborta `UPDATE` nas colunas de
conteúdo. Duas exceções nomeadas e deliberadas escapam do trigger, porque são
operações de ciclo de vida com nome próprio, não reescrita de conteúdo:

- `valid_until` — fechado **uma vez** por `supersede`, para que a vigência de
  uma memória contraditada feche exatamente quando a nova começa
  (ver ADR-0010);
- as colunas de `embedding` — substituídas **apenas** por `replace_embedding`,
  quando o modelo de embedding muda (ver `EmbeddingProvider`, contracts §7).

Ao contrário de `events` e `context_snapshots`, **não há trigger de `DELETE`**:
memória guarda dado pessoal, e `purge` precisa poder apagá-la de verdade — é o
direito de apagar que `PHASE-3.md §16` exige. `invalidate` ("esquecer") é a
operação que preserva evidência; `purge` ("apagar") é a que não preserva, e por
isso é sempre explícita e nunca automática.
"""

import logging
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from jarvis.memory.adapters.serialization import (
    encode_vector,
    format_timestamp,
    from_record,
    to_record,
)
from jarvis.memory.embedding import MemoryEmbedding
from jarvis.memory.errors import MemoryReadError, MemoryRepositoryError, MemoryWriteError
from jarvis.memory.memory import Memory, StoredMemory, require_identifier, require_unit_interval
from jarvis.memory.ports import MemoryCriteria

logger = logging.getLogger(__name__)

IN_MEMORY_DATABASE: Final = ":memory:"

_SCHEMA: Final = """
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS memories (
    sequence             INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id            TEXT    NOT NULL UNIQUE,
    type                 TEXT    NOT NULL,
    content              TEXT    NOT NULL,
    content_fingerprint  TEXT    NOT NULL,
    subject              TEXT,
    scope                TEXT,
    origin               TEXT    NOT NULL,
    provenance_reference TEXT,
    created_at           TEXT    NOT NULL,
    recorded_at          TEXT    NOT NULL,
    valid_from           TEXT    NOT NULL,
    valid_until          TEXT,
    importance           REAL    NOT NULL,
    initial_confidence   REAL    NOT NULL,
    confidence           REAL    NOT NULL,
    entities             TEXT    NOT NULL,
    tags                 TEXT    NOT NULL,
    derived_from         TEXT    NOT NULL,
    embedding            BLOB,
    embedding_provider   TEXT,
    embedding_model      TEXT,
    embedding_dimensions INTEGER,
    embedding_created_at TEXT,
    updated_at           TEXT    NOT NULL,
    last_accessed_at     TEXT,
    access_count         INTEGER NOT NULL DEFAULT 0,
    reinforced_count     INTEGER NOT NULL DEFAULT 0,
    superseded_by        TEXT,
    invalidated_at       TEXT,
    invalidation_reason  TEXT
);

CREATE INDEX IF NOT EXISTS memories_type_idx        ON memories(type);
CREATE INDEX IF NOT EXISTS memories_subject_idx     ON memories(subject);
CREATE INDEX IF NOT EXISTS memories_scope_idx       ON memories(scope);
CREATE INDEX IF NOT EXISTS memories_fingerprint_idx ON memories(content_fingerprint);
CREATE INDEX IF NOT EXISTS memories_created_at_idx  ON memories(created_at);

-- O conteúdo é imutável. `valid_until` (fechamento de vigência por `supersede`)
-- e as colunas de embedding (substituídas por `replace_embedding`) são as
-- únicas exceções nomeadas — ver docstring do módulo.
CREATE TRIGGER IF NOT EXISTS memories_block_content_update
BEFORE UPDATE OF memory_id, type, content, content_fingerprint, subject, scope,
                 origin, provenance_reference, created_at, valid_from, importance,
                 initial_confidence, entities, tags, derived_from
ON memories
BEGIN
    SELECT RAISE(ABORT, 'memory content is immutable');
END;
"""

_COLUMNS: Final = (
    "memory_id, type, content, content_fingerprint, subject, scope, origin, "
    "provenance_reference, created_at, recorded_at, valid_from, valid_until, "
    "importance, initial_confidence, confidence, entities, tags, derived_from, "
    "embedding, embedding_provider, embedding_model, embedding_dimensions, "
    "embedding_created_at, updated_at, last_accessed_at, access_count, "
    "reinforced_count, superseded_by, invalidated_at, invalidation_reason"
)

_INSERT: Final = f"""
INSERT INTO memories ({_COLUMNS})
VALUES (:memory_id, :type, :content, :content_fingerprint, :subject, :scope, :origin,
        :provenance_reference, :created_at, :recorded_at, :valid_from, :valid_until,
        :importance, :initial_confidence, :confidence, :entities, :tags, :derived_from,
        :embedding, :embedding_provider, :embedding_model, :embedding_dimensions,
        :embedding_created_at, :updated_at, :last_accessed_at, :access_count,
        :reinforced_count, :superseded_by, :invalidated_at, :invalidation_reason)
"""

_SELECT: Final = f"SELECT {_COLUMNS} FROM memories"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SqliteMemoryRepository:
    """Implementação de `MemoryRepository` sobre SQLite.

    Nenhum tipo do driver (`Connection`, `Row`, cursor) atravessa a fronteira: o
    Core só vê `Memory`/`StoredMemory`.
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
            raise MemoryRepositoryError(
                f"não foi possível abrir o repositório de memórias em {database}"
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

    def add(self, memory: Memory, *, recorded_at: datetime) -> StoredMemory:
        stored = StoredMemory(
            memory=memory,
            recorded_at=recorded_at,
            updated_at=recorded_at,
            confidence=memory.confidence,
        )
        record = to_record(stored)
        try:
            with self._connection:
                self._connection.execute(_INSERT, dict(record))
        except sqlite3.IntegrityError as error:
            raise MemoryWriteError(f"memory_id {memory.memory_id} já existe") from error
        except sqlite3.Error as error:
            raise MemoryWriteError(f"falha ao persistir a memória {memory.memory_id}") from error
        return self._must_get(memory.memory_id)

    def get(self, memory_id: str) -> StoredMemory | None:
        found = self._query(f"{_SELECT} WHERE memory_id = ?", (memory_id,))
        return found[0] if found else None

    def search(self, criteria: MemoryCriteria) -> Sequence[StoredMemory]:
        clauses: list[str] = []
        params: list[object] = []

        if criteria.types:
            placeholders = ",".join("?" for _ in criteria.types)
            clauses.append(f"type IN ({placeholders})")
            params.extend(sorted(item.value for item in criteria.types))
        if criteria.subject is not None:
            clauses.append("subject = ?")
            params.append(criteria.subject)
        if criteria.scope is not None:
            clauses.append("scope = ?")
            params.append(criteria.scope)
        if criteria.created_from is not None:
            clauses.append("created_at >= ?")
            params.append(format_timestamp(criteria.created_from))
        if criteria.created_until is not None:
            clauses.append("created_at < ?")
            params.append(format_timestamp(criteria.created_until))
        if criteria.minimum_importance is not None:
            clauses.append("importance >= ?")
            params.append(criteria.minimum_importance)
        if criteria.active_at is not None:
            moment = format_timestamp(criteria.active_at)
            clauses.append("valid_from <= ?")
            params.append(moment)
            clauses.append("(valid_until IS NULL OR valid_until > ?)")
            params.append(moment)
        if not criteria.include_invalidated:
            clauses.append("invalidated_at IS NULL")
        if not criteria.include_superseded:
            clauses.append("superseded_by IS NULL")
        if criteria.embedding_model is not None:
            clauses.append(
                "embedding_provider = ? AND embedding_model = ? AND embedding_dimensions = ?"
            )
            params.extend(
                [
                    criteria.embedding_model.provider,
                    criteria.embedding_model.model,
                    criteria.embedding_model.dimensions,
                ]
            )

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"{_SELECT}{where} ORDER BY sequence", tuple(params))

        # Filtros de conjunto (tags/entities: "todas presentes") não têm SQL simples
        # e portável sem depender de JSON1 — refinados aqui, sobre o já filtrado por SQL.
        if criteria.tags:
            rows = [row for row in rows if criteria.tags <= set(row.memory.tags)]
        if criteria.entities:
            rows = [row for row in rows if criteria.entities <= set(row.memory.entities)]

        return rows if criteria.limit is None else rows[: criteria.limit]

    def record_access(self, memory_id: str, *, moment: datetime) -> StoredMemory:
        self._must_get(memory_id)
        self._execute(
            "UPDATE memories SET last_accessed_at = ?, access_count = access_count + 1 "
            "WHERE memory_id = ?",
            (format_timestamp(moment), memory_id),
            failure=f"falha ao registrar acesso a {memory_id}",
        )
        return self._must_get(memory_id)

    def reinforce(self, memory_id: str, *, confidence: float, moment: datetime) -> StoredMemory:
        self._must_get(memory_id)
        validated = require_unit_interval(confidence, field_name="confidence")
        self._execute(
            "UPDATE memories SET confidence = ?, reinforced_count = reinforced_count + 1, "
            "updated_at = ? WHERE memory_id = ?",
            (validated, format_timestamp(moment), memory_id),
            failure=f"falha ao reforçar {memory_id}",
        )
        return self._must_get(memory_id)

    def invalidate(self, memory_id: str, *, reason: str, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
        validated_reason = require_identifier(reason, field_name="reason")
        if existing.invalidated_at is not None:
            # Esquecer o que já foi esquecido não muda nada — idempotente.
            return existing
        self._execute(
            "UPDATE memories SET invalidated_at = ?, invalidation_reason = ?, updated_at = ? "
            "WHERE memory_id = ?",
            (format_timestamp(moment), validated_reason, format_timestamp(moment), memory_id),
            failure=f"falha ao invalidar {memory_id}",
        )
        return self._must_get(memory_id)

    def supersede(self, memory_id: str, *, by: str, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
        require_identifier(by, field_name="by")

        if existing.superseded_by is not None:
            if existing.superseded_by == by:
                return existing
            raise MemoryWriteError(f"{memory_id} já foi superseded por outra memória")

        current_valid_until = existing.memory.valid_until
        closing = moment if current_valid_until is None else min(current_valid_until, moment)
        assert existing.memory.valid_from is not None
        if closing <= existing.memory.valid_from:
            raise MemoryWriteError(
                f"não é possível supersede {memory_id}: a vigência resultante seria vazia"
            )

        self._execute(
            "UPDATE memories SET superseded_by = ?, valid_until = ?, updated_at = ? "
            "WHERE memory_id = ?",
            (by, format_timestamp(closing), format_timestamp(moment), memory_id),
            failure=f"falha ao aplicar supersede em {memory_id}",
        )
        return self._must_get(memory_id)

    def replace_embedding(
        self, memory_id: str, embedding: MemoryEmbedding, *, moment: datetime
    ) -> StoredMemory:
        self._must_get(memory_id)
        self._execute(
            "UPDATE memories SET embedding = ?, embedding_provider = ?, embedding_model = ?, "
            "embedding_dimensions = ?, embedding_created_at = ?, updated_at = ? "
            "WHERE memory_id = ?",
            (
                encode_vector(embedding.vector),
                embedding.model.provider,
                embedding.model.model,
                embedding.model.dimensions,
                format_timestamp(embedding.created_at),
                format_timestamp(moment),
                memory_id,
            ),
            failure=f"falha ao substituir o embedding de {memory_id}",
        )
        return self._must_get(memory_id)

    def purge(self, memory_id: str) -> bool:
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "DELETE FROM memories WHERE memory_id = ?", (memory_id,)
                )
                deleted = cursor.rowcount > 0
        except sqlite3.Error as error:
            raise MemoryWriteError(f"falha ao apagar {memory_id}") from error
        if deleted:
            logger.warning("memory.purged", extra={"memory_id": memory_id})
        return deleted

    def _must_get(self, memory_id: str) -> StoredMemory:
        existing = self.get(memory_id)
        if existing is None:
            raise MemoryWriteError(f"memória {memory_id} não encontrada")
        return existing

    def _execute(self, sql: str, parameters: tuple[object, ...], *, failure: str) -> None:
        try:
            with self._connection:
                self._connection.execute(sql, parameters)
        except sqlite3.Error as error:
            raise MemoryWriteError(failure) from error

    def _query(self, sql: str, parameters: tuple[object, ...]) -> list[StoredMemory]:
        try:
            rows = self._connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise MemoryReadError("falha ao consultar as memórias") from error
        return [from_record(dict(row)) for row in rows]
