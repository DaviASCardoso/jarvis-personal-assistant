"""Benchmark leve dos componentes cuja escala foi apontada como sensível no
guia da Fase 8: retrieval de memória, construção de contexto e interpretação
de decisão do modelo (Fase 8.7).

Fora da suíte `pytest` de propósito — mede tempo de parede, que varia por
máquina, e o CI não pode depender disso para passar ou falhar
([ADR-0009](../docs/adr/0009-sqlite-memory-storage.md) já mediu e decidiu o
mesmo trade-off para o retrieval de memória: a tabela abaixo é o mesmo
método, atualizado). `tests/test_performance_benchmarks.py` usa as mesmas
funções com limites **generosos** — regressão grosseira, não gate de
performance rígido.

Uso:
    uv run python scripts/benchmark.py
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from jarvis.agent.decision import parse_decision
from jarvis.context.aggregator import ContextAggregator
from jarvis.context.model import ContextUpdate
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.embedding import MemoryEmbedding
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import Memory, MemoryOrigin, MemoryType, Provenance
from jarvis.memory.retrieval import RetrievalQuery

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
_REPEATS = 5


class _DummyProvider:
    """Provider sintético: mede o custo da agregação em si, não de I/O de
    sistema operacional — os providers reais da Fase 8.1 já são dublados
    (`ContextProvider`) nos próprios testes de unidade deles."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        return ContextUpdate()


def _time_ms(fn: Callable[[], object], *, repeats: int = _REPEATS) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return sum(samples) / len(samples)


def benchmark_memory_retrieval(count: int) -> float:
    """N memórias sintéticas, retrieval semântico com varredura de cosseno
    exata (mesmo método do ADR-0009, sobre `HashingEmbeddingProvider`).

    A população usa `repository.add()` direto, não `manager.remember()`: o
    que este benchmark mede é o custo do **retrieval** sobre N vetores já
    existentes, não o custo de deduplicação/contradição que `remember()`
    verifica a cada inserção (O(N) por inserção, O(N²) no total — um
    problema de escrita distinto, fora do escopo desta medição)."""
    embeddings = HashingEmbeddingProvider()
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        for index in range(count):
            content = f"fato numero {index} sobre o dia a dia do usuario"
            memory = Memory(
                memory_id=f"bench-{index}",
                type=MemoryType.SEMANTIC,
                content=content,
                provenance=Provenance(origin=MemoryOrigin.SYSTEM, reference=f"bench-{index}"),
                created_at=NOW,
                embedding=MemoryEmbedding(
                    vector=embeddings.embed(content), model=embeddings.model, created_at=NOW
                ),
            )
            repository.add(memory, recorded_at=NOW)

        manager = MemoryManager(repository=repository, embeddings=embeddings)
        return _time_ms(lambda: manager.retrieve(RetrievalQuery(text="fato do dia a dia", now=NOW)))


def benchmark_context_construction(provider_count: int) -> float:
    """`ContextAggregator.refresh` com N providers dublados — mede o custo da
    agregação/projeção, não de I/O de sistema operacional."""
    aggregator = ContextAggregator(
        providers=[_DummyProvider(f"provider-{index}") for index in range(provider_count)],
        clock=lambda: NOW,
    )
    return _time_ms(aggregator.refresh)


def benchmark_decision_parsing() -> float:
    """Custo de `parse_decision` sobre uma resposta típica do modelo."""
    text = '{"type": "notify", "reason": "teste", "message": "ola"}'
    return _time_ms(
        lambda: parse_decision(
            text, decision_id="dec-bench", correlation_id="corr-bench", decided_at=NOW
        )
    )


def main() -> None:
    print("Fase 8.7 — benchmark (ver docs/adr/0009-sqlite-memory-storage.md para o método)")
    print()
    for count in (100, 1_000, 5_000):
        elapsed = benchmark_memory_retrieval(count)
        print(f"memory.retrieve   {count:>6} memórias    {elapsed:8.2f} ms")
    print()
    for count in (5, 20):
        elapsed = benchmark_context_construction(count)
        print(f"context.refresh   {count:>6} providers   {elapsed:8.2f} ms")
    print()
    elapsed = benchmark_decision_parsing()
    print(f"parse_decision                          {elapsed:8.2f} ms")


if __name__ == "__main__":
    main()
