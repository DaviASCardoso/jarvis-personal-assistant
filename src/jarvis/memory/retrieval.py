"""Recuperação: lookup estruturado e busca semântica, na mesma API.

`PHASE-3.md §11` exige que os dois mecanismos não sejam confundidos, e deixa em
aberto se serão APIs separadas ou uma só capaz de combinar filtros. A escolha:
**uma API, dois modos**, distinguidos pela presença de `text` em
`RetrievalQuery`. Os candidatos vêm sempre do mesmo lugar —
`MemoryRepository.search`, já filtrado por `MemoryCriteria` — e só divergem
depois: com texto, a ordenação usa similaridade; sem texto, usa os sinais já
disponíveis sem consulta textual.

Esta é a versão desta subfase (3.3): candidatos + uma ordenação inicial. A
fórmula completa e ponderada (`RelevanceScore`, com recência/importância/
confiança combinadas) entra na 3.4 (`memory/ranking.py`), que substitui a
ordenação abaixo sem mudar o contrato de `RetrievalQuery`/`MemoryRepository`.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from jarvis.memory.embedding import cosine_similarity
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import StoredMemory
from jarvis.memory.ports import EmbeddingProvider, MemoryCriteria, MemoryRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalQuery:
    """`text is None` ⇒ lookup estruturado; `text` presente ⇒ busca semântica,
    **além** dos mesmos filtros — o texto acrescenta um termo, não substitui os
    outros."""

    text: str | None = None
    criteria: MemoryCriteria = field(default_factory=MemoryCriteria)
    limit: int = 10

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise InvalidMemoryError(f"limit precisa ser positivo, recebido {self.limit}")
        if self.text is not None and not self.text.strip():
            raise InvalidMemoryError("text não pode ser vazio quando informado")


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalResult:
    memory: StoredMemory
    score: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalOutcome:
    results: tuple[RetrievalResult, ...]
    scanned: int
    skipped_incompatible: int


def _sort_key(result: RetrievalResult) -> tuple[float, datetime, str]:
    # Desempate determinístico: score, depois o mais recentemente atualizado,
    # depois o id — duas execuções sobre os mesmos dados produzem a mesma ordem.
    return (result.score, result.memory.updated_at, result.memory.memory.memory_id)


class MemoryRetrieval:
    """Serviço de aplicação; não é port — implementação única, nenhum
    substituto real (contrato §1)."""

    def __init__(
        self, *, repository: MemoryRepository, embeddings: EmbeddingProvider | None = None
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings

    def retrieve(self, query: RetrievalQuery) -> RetrievalOutcome:
        candidates = self._repository.search(query.criteria)
        scanned = len(candidates)

        if query.text is None:
            scored = [
                RetrievalResult(memory=candidate, score=self._structural_score(candidate))
                for candidate in candidates
            ]
            skipped = 0
        else:
            scored, skipped = self._score_semantically(query.text, candidates)

        ordered = sorted(scored, key=_sort_key, reverse=True)
        return RetrievalOutcome(
            results=tuple(ordered[: query.limit]), scanned=scanned, skipped_incompatible=skipped
        )

    def _score_semantically(
        self, text: str, candidates: Sequence[StoredMemory]
    ) -> tuple[list[RetrievalResult], int]:
        if self._embeddings is None:
            raise InvalidMemoryError("busca semântica exige um EmbeddingProvider configurado")

        query_vector = self._embeddings.embed(text)
        query_model = self._embeddings.model

        results: list[RetrievalResult] = []
        skipped = 0
        for candidate in candidates:
            embedding = candidate.memory.embedding
            if embedding is None or embedding.model != query_model:
                skipped += 1
                continue
            score = cosine_similarity(query_vector, embedding.vector)
            results.append(RetrievalResult(memory=candidate, score=score))
        return results, skipped

    @staticmethod
    def _structural_score(candidate: StoredMemory) -> float:
        return candidate.memory.importance
