"""Doubles do Memory System, com defaults válidos.

Cada double controla exatamente uma variável do teste:

- `make_memory` — constrói uma `Memory` válida com defaults seguros (tipo
  `EPISODIC`, sem as exigências condicionais de `WORKING`/`TASK`/`PREFERENCE`);
- `StubEmbeddingProvider` — qual vetor cada texto produz, sem depender do
  algoritmo de hashing real;
- `FailingEmbeddingProvider` — qual exceção o manager vê (traduzida ou não);
- `FakeMemoryRepository` — o histórico, em memória, com a mesma semântica do
  adapter SQLite (imutabilidade de conteúdo, filtros, ciclo de vida);
- `frozen_clock` — a passagem do tempo, única forma de testar recência, reforço
  e expiração sem esperar de verdade.
"""

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

from jarvis.memory.embedding import EmbeddingModel, MemoryEmbedding
from jarvis.memory.errors import EmbeddingProviderError, MemoryWriteError
from jarvis.memory.memory import (
    Memory,
    MemoryOrigin,
    MemoryType,
    Provenance,
    StoredMemory,
    new_memory_id,
)
from jarvis.memory.ports import MemoryCriteria

DEFAULT_CREATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

DEFAULT_EMBEDDING_MODEL: Final = EmbeddingModel(provider="stub", model="stub-v1", dimensions=4)


def frozen_clock(*moments: datetime) -> Callable[[], datetime]:
    """Relógio que devolve cada instante uma vez e repete o último para sempre."""
    remaining = list(moments)

    def clock() -> datetime:
        if len(remaining) > 1:
            return remaining.pop(0)
        return remaining[0]

    return clock


def make_memory(
    *,
    memory_id: str | None = None,
    type: MemoryType = MemoryType.EPISODIC,
    content: str = "conteúdo de teste",
    provenance: Provenance | None = None,
    created_at: datetime = DEFAULT_CREATED_AT,
    importance: float = 0.5,
    confidence: float = 0.8,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    subject: str | None = None,
    scope: str | None = None,
    entities: Sequence[str] = (),
    tags: Sequence[str] = (),
    derived_from: Sequence[str] = (),
    embedding: MemoryEmbedding | None = None,
) -> Memory:
    return Memory(
        memory_id=memory_id if memory_id is not None else new_memory_id(),
        type=type,
        content=content,
        provenance=provenance if provenance is not None else Provenance(origin=MemoryOrigin.USER),
        created_at=created_at,
        importance=importance,
        confidence=confidence,
        valid_from=valid_from,
        valid_until=valid_until,
        subject=subject,
        scope=scope,
        entities=tuple(entities),
        tags=tuple(tags),
        derived_from=tuple(derived_from),
        embedding=embedding,
    )


def make_embedding(
    vector: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0),
    *,
    model: EmbeddingModel = DEFAULT_EMBEDDING_MODEL,
    created_at: datetime = DEFAULT_CREATED_AT,
) -> MemoryEmbedding:
    return MemoryEmbedding(vector=vector, model=model, created_at=created_at)


class StubEmbeddingProvider:
    """Devolve um vetor fixo por texto (ou um default), e registra o que pediu."""

    def __init__(
        self,
        *,
        model: EmbeddingModel = DEFAULT_EMBEDDING_MODEL,
        default_vector: tuple[float, ...] | None = None,
        by_text: Mapping[str, tuple[float, ...]] | None = None,
    ) -> None:
        self._model = model
        self._default_vector = default_vector or (1.0, *([0.0] * (model.dimensions - 1)))
        self._by_text = dict(by_text or {})
        self.embedded: list[str] = []

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    def embed(self, text: str) -> tuple[float, ...]:
        self.embedded.append(text)
        return self._by_text.get(text, self._default_vector)


class FailingEmbeddingProvider:
    """Falha sempre, com o erro que o teste escolher."""

    def __init__(
        self, *, model: EmbeddingModel = DEFAULT_EMBEDDING_MODEL, error: Exception | None = None
    ) -> None:
        self._model = model
        self._error = error or EmbeddingProviderError("provider indisponível")

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    def embed(self, text: str) -> tuple[float, ...]:
        raise self._error


class FakeMemoryRepository:
    """Histórico em memória com a mesma semântica de negócio do adapter SQLite:
    conteúdo imutável (mutações passam por `dataclasses.replace`, que revalida),
    `invalidate` idempotente, `supersede` validado e fechando `valid_until`,
    `purge` físico."""

    def __init__(self) -> None:
        self._rows: dict[str, StoredMemory] = {}

    def add(self, memory: Memory, *, recorded_at: datetime) -> StoredMemory:
        if memory.memory_id in self._rows:
            raise MemoryWriteError(f"memory_id {memory.memory_id} já existe")
        stored = StoredMemory(
            memory=memory,
            recorded_at=recorded_at,
            updated_at=recorded_at,
            confidence=memory.confidence,
        )
        self._rows[memory.memory_id] = stored
        return stored

    def get(self, memory_id: str) -> StoredMemory | None:
        return self._rows.get(memory_id)

    def search(self, criteria: MemoryCriteria) -> Sequence[StoredMemory]:
        rows = list(self._rows.values())
        if criteria.types is not None:
            rows = [row for row in rows if row.memory.type in criteria.types]
        if criteria.subject is not None:
            rows = [row for row in rows if row.memory.subject == criteria.subject]
        if criteria.scope is not None:
            rows = [row for row in rows if row.memory.scope == criteria.scope]
        if criteria.created_from is not None:
            rows = [row for row in rows if row.memory.created_at >= criteria.created_from]
        if criteria.created_until is not None:
            rows = [row for row in rows if row.memory.created_at < criteria.created_until]
        if criteria.minimum_importance is not None:
            rows = [row for row in rows if row.memory.importance >= criteria.minimum_importance]
        if criteria.active_at is not None:
            rows = [row for row in rows if row.memory.is_valid_at(criteria.active_at)]
        if not criteria.include_invalidated:
            rows = [row for row in rows if row.invalidated_at is None]
        if not criteria.include_superseded:
            rows = [row for row in rows if row.superseded_by is None]
        if criteria.embedding_model is not None:
            rows = [
                row
                for row in rows
                if row.memory.embedding is not None
                and row.memory.embedding.model == criteria.embedding_model
            ]
        if criteria.tags:
            rows = [row for row in rows if criteria.tags <= set(row.memory.tags)]
        if criteria.entities:
            rows = [row for row in rows if criteria.entities <= set(row.memory.entities)]
        return rows if criteria.limit is None else rows[: criteria.limit]

    def record_access(self, memory_id: str, *, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
        updated = dataclasses.replace(
            existing, last_accessed_at=moment, access_count=existing.access_count + 1
        )
        self._rows[memory_id] = updated
        return updated

    def reinforce(self, memory_id: str, *, confidence: float, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
        updated = dataclasses.replace(
            existing,
            confidence=confidence,
            reinforced_count=existing.reinforced_count + 1,
            updated_at=moment,
        )
        self._rows[memory_id] = updated
        return updated

    def invalidate(self, memory_id: str, *, reason: str, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
        if existing.invalidated_at is not None:
            return existing
        updated = dataclasses.replace(
            existing, invalidated_at=moment, invalidation_reason=reason, updated_at=moment
        )
        self._rows[memory_id] = updated
        return updated

    def supersede(self, memory_id: str, *, by: str, moment: datetime) -> StoredMemory:
        existing = self._must_get(memory_id)
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

        new_memory = dataclasses.replace(existing.memory, valid_until=closing)
        updated = dataclasses.replace(
            existing, memory=new_memory, superseded_by=by, updated_at=moment
        )
        self._rows[memory_id] = updated
        return updated

    def replace_embedding(
        self, memory_id: str, embedding: MemoryEmbedding, *, moment: datetime
    ) -> StoredMemory:
        existing = self._must_get(memory_id)
        new_memory = dataclasses.replace(existing.memory, embedding=embedding)
        updated = dataclasses.replace(existing, memory=new_memory, updated_at=moment)
        self._rows[memory_id] = updated
        return updated

    def purge(self, memory_id: str) -> bool:
        return self._rows.pop(memory_id, None) is not None

    def _must_get(self, memory_id: str) -> StoredMemory:
        existing = self.get(memory_id)
        if existing is None:
            raise MemoryWriteError(f"memória {memory_id} não encontrada")
        return existing
