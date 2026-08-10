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

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

from jarvis.memory.embedding import EmbeddingModel, MemoryEmbedding
from jarvis.memory.errors import EmbeddingProviderError
from jarvis.memory.memory import Memory, MemoryOrigin, MemoryType, Provenance, new_memory_id

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
