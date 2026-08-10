"""Memory System: conhecimento durável, tipado e recuperável.

API pública do componente. As implementações concretas ficam em
`jarvis.memory.adapters` e são escolhidas pelo composition root, não importadas
por quem apenas usa o Core.

Documentação: [`docs/memory-system.md`](../../../docs/memory-system.md).
"""

from jarvis.memory.consolidation import ConsolidationReport, PromotionCandidate
from jarvis.memory.embedding import EmbeddingModel, MemoryEmbedding, cosine_similarity
from jarvis.memory.errors import (
    EmbeddingProviderError,
    InvalidMemoryError,
    MemoryReadError,
    MemoryRepositoryError,
    MemoryWriteError,
)
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import (
    Memory,
    MemoryOrigin,
    MemoryType,
    Provenance,
    StoredMemory,
    content_fingerprint,
    deterministic_memory_id,
    new_memory_id,
)
from jarvis.memory.ports import EmbeddingProvider, MemoryCriteria, MemoryRepository
from jarvis.memory.ranking import DEFAULT_RANKING_WEIGHTS, RankingWeights, RelevanceScore
from jarvis.memory.retrieval import (
    MemoryRetrieval,
    RetrievalOutcome,
    RetrievalQuery,
    RetrievalResult,
)

__all__ = [
    "DEFAULT_RANKING_WEIGHTS",
    "ConsolidationReport",
    "EmbeddingModel",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "InvalidMemoryError",
    "Memory",
    "MemoryCriteria",
    "MemoryEmbedding",
    "MemoryManager",
    "MemoryOrigin",
    "MemoryReadError",
    "MemoryRepository",
    "MemoryRepositoryError",
    "MemoryRetrieval",
    "MemoryType",
    "MemoryWriteError",
    "PromotionCandidate",
    "Provenance",
    "RankingWeights",
    "RelevanceScore",
    "RetrievalOutcome",
    "RetrievalQuery",
    "RetrievalResult",
    "StoredMemory",
    "content_fingerprint",
    "cosine_similarity",
    "deterministic_memory_id",
    "new_memory_id",
]
