"""Fase 8.7 — Performance: um teste leve por função de `scripts/benchmark.py`,
com limites **generosos** de propósito.

Isto é regressão grosseira (10x ou mais acima do medido nesta máquina), não
gate de performance rígido — o objetivo é pegar uma regressão de ordem de
grandeza (ex. alguém trocando a varredura de cosseno por algo O(N²) sem
perceber), não flutuação normal de CPU entre execuções de CI. Ver
`scripts/benchmark.py` e [ADR-0009](../docs/adr/0009-sqlite-memory-storage.md)
para o método e os números de referência.
"""

from scripts.benchmark import (
    benchmark_context_construction,
    benchmark_decision_parsing,
    benchmark_memory_retrieval,
)

# Medido nesta máquina (CPython 3.13, Windows): ~70ms/1000 memórias,
# ~1.1ms/20 providers, ~0.04ms para parse_decision. Os limites abaixo dão
# margem de mais de 10x para variação de hardware.
MEMORY_RETRIEVAL_LIMIT_MS = 1500.0
CONTEXT_CONSTRUCTION_LIMIT_MS = 200.0
DECISION_PARSING_LIMIT_MS = 50.0


def test_memory_retrieval_stays_within_order_of_magnitude() -> None:
    elapsed = benchmark_memory_retrieval(1_000)
    assert elapsed < MEMORY_RETRIEVAL_LIMIT_MS


def test_context_construction_stays_within_order_of_magnitude() -> None:
    elapsed = benchmark_context_construction(20)
    assert elapsed < CONTEXT_CONSTRUCTION_LIMIT_MS


def test_decision_parsing_stays_within_order_of_magnitude() -> None:
    elapsed = benchmark_decision_parsing()
    assert elapsed < DECISION_PARSING_LIMIT_MS
