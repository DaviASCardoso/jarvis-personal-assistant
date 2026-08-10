"""Ports do Memory System.

`MemoryRepository` é port porque contracts §11 proíbe o domínio de conhecer a
tecnologia de persistência. `EmbeddingProvider` é port separado de qualquer
`LLMProvider` — [ADR-0002](../../../docs/adr/0002-llm-provider-abstraction.md) —
para que trocar o modelo de raciocínio do futuro Agent Runtime nunca arrisque
quebrar a busca semântica já indexada, e vice-versa.

Nenhum outro serviço do Memory System (`MemoryManager`, `MemoryRetrieval`,
consolidação) é port: cada um tem implementação única e nenhum substituto real
— mesma assimetria de `EventBus`/`EventStore` na Fase 1 e de
`ContextAggregator`/`ContextSnapshotRepository` na Fase 2.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from jarvis.memory.embedding import EmbeddingModel, MemoryEmbedding, require_aware
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import (
    Memory,
    MemoryType,
    StoredMemory,
    require_identifier,
    require_slug,
    require_unit_interval,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCriteria:
    """Filtros estruturados. Todos opcionais; combinam por `AND`.

    `include_invalidated`/`include_superseded` controlam se linhas fora de
    vigência por ciclo de vida entram no resultado — independentemente de
    `active_at`, que é o filtro de vigência **temporal**
    (`valid_from ≤ active_at < valid_until`). Vigência plena (o default seguro
    do retrieval) é a combinação dos três defaults: `active_at` setado para
    "agora" e os dois `include_*` em `False`.
    """

    types: frozenset[MemoryType] | None = None
    subject: str | None = None
    scope: str | None = None
    tags: frozenset[str] | None = None
    entities: frozenset[str] | None = None
    created_from: datetime | None = None
    created_until: datetime | None = None
    minimum_importance: float | None = None
    active_at: datetime | None = None
    include_invalidated: bool = False
    include_superseded: bool = False
    embedding_model: EmbeddingModel | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        if self.subject is not None:
            overwrite(self, "subject", require_slug(self.subject, field_name="criteria.subject"))
        if self.scope is not None:
            overwrite(self, "scope", require_identifier(self.scope, field_name="criteria.scope"))
        if self.minimum_importance is not None:
            overwrite(
                self,
                "minimum_importance",
                require_unit_interval(self.minimum_importance, field_name="minimum_importance"),
            )

        for field_name in ("created_from", "created_until", "active_at"):
            value = getattr(self, field_name)
            if value is not None:
                aware = require_aware(value, field_name=field_name)
                overwrite(self, field_name, aware.astimezone(UTC))

        if (
            self.created_from is not None
            and self.created_until is not None
            and self.created_until <= self.created_from
        ):
            raise InvalidMemoryError("created_until precisa ser posterior a created_from")

        if self.limit is not None and self.limit <= 0:
            raise InvalidMemoryError(f"limit precisa ser positivo, recebido {self.limit}")


class MemoryRepository(Protocol):
    """Registro durável e consultável de memórias.

    Sem `update` genérico, de propósito: o conteúdo de uma memória é imutável
    (contrato §7, `PHASE-3.md §7`), e cada método aqui nomeia exatamente a
    mudança de ciclo de vida que autoriza.
    """

    def add(self, memory: Memory, *, recorded_at: datetime) -> StoredMemory: ...

    def get(self, memory_id: str) -> StoredMemory | None: ...

    def search(self, criteria: MemoryCriteria) -> Sequence[StoredMemory]: ...

    def record_access(self, memory_id: str, *, moment: datetime) -> StoredMemory: ...

    def reinforce(self, memory_id: str, *, confidence: float, moment: datetime) -> StoredMemory: ...

    def invalidate(self, memory_id: str, *, reason: str, moment: datetime) -> StoredMemory: ...

    def supersede(self, memory_id: str, *, by: str, moment: datetime) -> StoredMemory: ...

    def replace_embedding(
        self, memory_id: str, embedding: MemoryEmbedding, *, moment: datetime
    ) -> StoredMemory: ...

    def purge(self, memory_id: str) -> bool:
        """Remoção física e irreversível — só por pedido explícito (§16 de
        `PHASE-3.md`, direito de apagar dado pessoal). Devolve `False` se o
        `memory_id` não existir."""
        ...


class EmbeddingProvider(Protocol):
    """Fonte de vetores semânticos, independente de `LLMProvider`.

    Entrada: uma string já normalizada pelo chamador (trim + colapso de
    espaços). Saída: vetor L2-normalizado, com exatamente `model.dimensions`
    posições. Falha ⇒ `EmbeddingProviderError` — o adapter traduz a exceção
    nativa e nunca a deixa vazar.
    """

    @property
    def model(self) -> EmbeddingModel: ...

    def embed(self, text: str) -> tuple[float, ...]: ...
