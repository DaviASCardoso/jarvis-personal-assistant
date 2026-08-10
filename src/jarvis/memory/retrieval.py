"""Recuperação: lookup estruturado e busca semântica, na mesma API.

`PHASE-3.md §11` exige que os dois mecanismos não sejam confundidos, e deixa em
aberto se serão APIs separadas ou uma só capaz de combinar filtros. A escolha:
**uma API, dois modos**, distinguidos pela presença de `text` em
`RetrievalQuery`. Os candidatos vêm sempre do mesmo lugar —
`MemoryRepository.search`, já filtrado por `MemoryCriteria` — e só divergem
depois: com texto, o termo semântico entra na combinação de `memory/ranking.py`;
sem texto, a fórmula é a mesma, renormalizada sem esse termo.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jarvis.memory.embedding import cosine_similarity
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import StoredMemory
from jarvis.memory.ports import EmbeddingProvider, MemoryCriteria, MemoryRepository
from jarvis.memory.ranking import DEFAULT_RANKING_WEIGHTS, RankingWeights, RelevanceScore
from jarvis.memory.ranking import score as compute_score

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalQuery:
    """`text is None` ⇒ lookup estruturado; `text` presente ⇒ busca semântica,
    **além** dos mesmos filtros — o texto acrescenta um termo, não substitui os
    outros."""

    text: str | None = None
    criteria: MemoryCriteria = field(default_factory=MemoryCriteria)
    limit: int = 10
    now: datetime | None = None

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise InvalidMemoryError(f"limit precisa ser positivo, recebido {self.limit}")
        if self.text is not None and not self.text.strip():
            raise InvalidMemoryError("text não pode ser vazio quando informado")


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalResult:
    memory: StoredMemory
    score: RelevanceScore


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalOutcome:
    results: tuple[RetrievalResult, ...]
    scanned: int
    skipped_incompatible: int


def _sort_key(result: RetrievalResult) -> tuple[float, float, str]:
    # Desempate determinístico: score, depois o mais recente, depois o id — duas
    # execuções sobre os mesmos dados produzem exatamente a mesma ordem.
    return (
        -result.score.total,
        -result.memory.memory.created_at.timestamp(),
        result.memory.memory.memory_id,
    )


class MemoryRetrieval:
    """Serviço de aplicação; não é port — implementação única, nenhum
    substituto real (contrato §1)."""

    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embeddings: EmbeddingProvider | None = None,
        weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._weights = weights
        self._clock = clock

    def retrieve(self, query: RetrievalQuery) -> RetrievalOutcome:
        now = query.now if query.now is not None else self._clock()
        candidates = self._repository.search(query.criteria)
        scanned = len(candidates)

        if query.text is None:
            scored = [
                RetrievalResult(
                    memory=candidate,
                    score=compute_score(candidate, now=now, weights=self._weights),
                )
                for candidate in candidates
            ]
            skipped = 0
        else:
            scored, skipped = self._score_semantically(query.text, candidates, now=now)

        ordered = sorted(scored, key=_sort_key)
        return RetrievalOutcome(
            results=tuple(ordered[: query.limit]), scanned=scanned, skipped_incompatible=skipped
        )

    def _score_semantically(
        self, text: str, candidates: Sequence[StoredMemory], *, now: datetime
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
            semantic = cosine_similarity(query_vector, embedding.vector)
            results.append(
                RetrievalResult(
                    memory=candidate,
                    score=compute_score(
                        candidate, now=now, semantic=semantic, weights=self._weights
                    ),
                )
            )
        return results, skipped
