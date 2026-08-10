"""`MemoryManager`: o serviço de aplicação que orquestra o ciclo de vida completo.

Não é port — implementação única, nenhum substituto real (contrato §1). É o
único lugar que decide *quando* aplicar consolidação, gerar embedding ou
reforçar confiança; `MemoryRepository` e `EmbeddingProvider` continuam sendo
executores burros das operações que o manager pede.
"""

import dataclasses
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final

from jarvis.memory.consolidation import (
    ConsolidationReport,
    find_contradiction,
    find_duplicate,
    find_promotions,
)
from jarvis.memory.embedding import MemoryEmbedding
from jarvis.memory.errors import EmbeddingProviderError, InvalidMemoryError, MemoryWriteError
from jarvis.memory.memory import (
    Memory,
    MemoryOrigin,
    MemoryType,
    Provenance,
    StoredMemory,
    new_memory_id,
)
from jarvis.memory.ports import EmbeddingProvider, MemoryCriteria, MemoryRepository
from jarvis.memory.ranking import DEFAULT_RANKING_WEIGHTS, RankingWeights
from jarvis.memory.retrieval import MemoryRetrieval, RetrievalOutcome, RetrievalQuery

logger = logging.getLogger(__name__)

# Curva de reforço: c <- c + (cap - c) * taxa. A partir de 0.50: 0.67, 0.78,
# 0.85, 0.90 - cresce rápido no começo, satura perto do teto e nunca alcança 1.0.
REINFORCEMENT_CAP: Final = 0.99
REINFORCEMENT_RATE: Final = 0.34


def reinforced_confidence(current: float) -> float:
    return current + (REINFORCEMENT_CAP - current) * REINFORCEMENT_RATE


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryManager:
    def __init__(
        self,
        *,
        repository: MemoryRepository,
        embeddings: EmbeddingProvider | None = None,
        weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = new_memory_id,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings
        self._clock = clock
        self._new_id = new_id
        self._retrieval = MemoryRetrieval(
            repository=repository, embeddings=embeddings, weights=weights, clock=clock
        )

    def remember(
        self,
        *,
        type: MemoryType,
        content: str,
        provenance: Provenance,
        importance: float = 0.5,
        confidence: float = 0.8,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        subject: str | None = None,
        scope: str | None = None,
        entities: Sequence[str] = (),
        tags: Sequence[str] = (),
        derived_from: Sequence[str] = (),
        embed: bool | None = None,
    ) -> StoredMemory:
        """Cria uma memória, ou reforça uma duplicata; nunca as duas.

        Ordem: **validação (sem I/O) → consolidação inline → embedding → persistência.**
        Uma memória inválida nunca chega a tocar o repositório ou o provider.
        """
        now = self._clock()
        candidate = Memory(
            memory_id=self._new_id(),
            type=type,
            content=content,
            provenance=provenance,
            created_at=now,
            importance=importance,
            confidence=confidence,
            valid_from=valid_from,
            valid_until=valid_until,
            subject=subject,
            scope=scope,
            entities=tuple(entities),
            tags=tuple(tags),
            derived_from=tuple(derived_from),
        )

        existing = self._repository.search(
            MemoryCriteria(types=frozenset({candidate.type}), active_at=now)
        )

        duplicate = find_duplicate(candidate, existing, now=now)
        if duplicate is not None:
            return self._repository.reinforce(
                duplicate.memory.memory_id,
                confidence=reinforced_confidence(duplicate.confidence),
                moment=now,
            )

        candidate = self._with_embedding_if_wanted(candidate, embed=embed, now=now)
        stored = self._repository.add(candidate, recorded_at=now)

        contradiction = find_contradiction(candidate, existing, now=now)
        if contradiction is not None:
            self._repository.supersede(
                contradiction.memory.memory_id, by=stored.memory.memory_id, moment=now
            )

        return stored

    def retrieve(self, query: RetrievalQuery) -> RetrievalOutcome:
        return self._retrieval.retrieve(query)

    def record_access(self, memory_id: str) -> StoredMemory:
        """Uso deliberado, não curiosidade: `retrieve()` nunca chama isto por
        conta própria (ver `memory/retrieval.py`) — é quem efetivamente usou a
        memória que registra o acesso."""
        return self._repository.record_access(memory_id, moment=self._clock())

    def reinforce(self, memory_id: str) -> StoredMemory:
        """Reforço explícito — a mesma curva assintótica do caminho de
        duplicata em `remember`, para quando algo fora de uma nova afirmação
        (ex. o Agent Runtime confirmando que usou a memória) deveria aumentar
        a confiança."""
        current = self._repository.get(memory_id)
        if current is None:
            raise MemoryWriteError(f"memória {memory_id} não encontrada")
        return self._repository.reinforce(
            memory_id, confidence=reinforced_confidence(current.confidence), moment=self._clock()
        )

    def forget(self, memory_id: str, *, reason: str) -> StoredMemory:
        """Invalidação lógica: a memória some do retrieval padrão, mas a
        evidência permanece (`include_invalidated=True` a recupera)."""
        return self._repository.invalidate(memory_id, reason=reason, moment=self._clock())

    def forget_scope(self, scope: str, *, reason: str) -> tuple[StoredMemory, ...]:
        """Invalida em bloco as memórias de uma tarefa encerrada — o que
        `PHASE-3.md §14` descreve para Task Memory, sem precisar de um segundo
        armazenamento."""
        now = self._clock()
        active = self._repository.search(MemoryCriteria(scope=scope, active_at=now))
        return tuple(
            self._repository.invalidate(item.memory.memory_id, reason=reason, moment=now)
            for item in active
        )

    def purge(self, memory_id: str) -> bool:
        """Remoção física e irreversível — o direito de apagar dado pessoal
        (`PHASE-3.md §16`), nunca automática."""
        return self._repository.purge(memory_id)

    def reembed(self, *, embeddings: EmbeddingProvider | None = None) -> int:
        """Regenera vetores **incompatíveis** com o modelo corrente — o
        caminho de recuperação depois de trocar de `EmbeddingProvider`
        (contracts §7). Memórias sem embedding (ex. `WORKING`, por design) não
        são tocadas: ausência intencional não é incompatibilidade."""
        provider = embeddings if embeddings is not None else self._embeddings
        if provider is None:
            raise InvalidMemoryError("reembed exige um EmbeddingProvider configurado")

        now = self._clock()
        active = self._repository.search(MemoryCriteria(active_at=now))
        updated = 0
        for item in active:
            embedding = item.memory.embedding
            if embedding is None or embedding.model == provider.model:
                continue
            try:
                vector = provider.embed(item.memory.content)
            except EmbeddingProviderError as error:
                logger.warning(
                    "memory.reembed_failed",
                    extra={
                        "memory_id": item.memory.memory_id,
                        "error_type": type(error).__name__,
                    },
                )
                continue
            new_embedding = MemoryEmbedding(vector=vector, model=provider.model, created_at=now)
            self._repository.replace_embedding(item.memory.memory_id, new_embedding, moment=now)
            updated += 1
        return updated

    def consolidate(self) -> ConsolidationReport:
        """Deduplicação e contradição já acontecem em `remember`; esta é a
        regra que só um pedido explícito deveria disparar — promoção
        episódica → semântica (`PHASE-3.md §5`)."""
        now = self._clock()
        active = self._repository.search(
            MemoryCriteria(
                types=frozenset({MemoryType.EPISODIC, MemoryType.SEMANTIC}), active_at=now
            )
        )
        promotions = find_promotions(active, now=now)

        created = tuple(
            self.remember(
                type=MemoryType.SEMANTIC,
                content=candidate.content,
                provenance=Provenance(origin=MemoryOrigin.SYSTEM),
                confidence=candidate.confidence,
                subject=candidate.subject,
                derived_from=tuple(item.memory.memory_id for item in candidate.contributors),
            )
            for candidate in promotions
        )
        if created:
            logger.info("memory.consolidated", extra={"promoted": len(created)})
        return ConsolidationReport(promoted=created)

    def _with_embedding_if_wanted(
        self, candidate: Memory, *, embed: bool | None, now: datetime
    ) -> Memory:
        # Working memory não recebe embedding por padrão: vive horas, é
        # recuperada por `scope`, e gastar uma chamada de embedding nela seria
        # custo sem retorno (docs/context-system.md segue o mesmo critério para
        # providers sem consumidor real).
        wants_embedding = embed if embed is not None else candidate.type is not MemoryType.WORKING
        if not wants_embedding or self._embeddings is None:
            return candidate

        try:
            vector = self._embeddings.embed(candidate.content)
        except EmbeddingProviderError as error:
            logger.warning(
                "memory.embedding_failed",
                extra={"memory_id": candidate.memory_id, "error_type": type(error).__name__},
            )
            return candidate

        embedding = MemoryEmbedding(vector=vector, model=self._embeddings.model, created_at=now)
        return dataclasses.replace(candidate, embedding=embedding)
