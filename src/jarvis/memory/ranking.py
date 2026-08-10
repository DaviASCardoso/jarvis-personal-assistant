"""`relevance`: a fórmula que decide a ordem do retrieval — nunca armazenada.

Contracts §7 é explícito: `relevance` é "score de recuperação, combinando
importance + recência + confidence + match da query" e é "**calculado em tempo
de retrieval, nunca armazenado**". `PHASE-3.md §12` pede uma fórmula
determinística, explicável e testável — sem ML, sem treinamento.

## A fórmula

Para uma memória `m`, no instante `now`, com um termo semântico opcional:

```text
relevance(m) = Σ wᵢ · termᵢ(m)  /  Σ wᵢ        (i sobre os termos presentes)
```

Quatro termos, todos em `[0, 1]`:

| Termo | Definição | Peso padrão |
|---|---|---|
| `semantic` | `max(0, cos(consulta, memória))` — só existe com consulta textual | 0.45 |
| `recency` | `0.5 ** (idade / meia-vida do tipo)`, idade = `now - updated_at` | 0.20 |
| `importance` | `memory.importance` | 0.20 |
| `confidence` | `stored.confidence` (corrente) | 0.15 |

`semantic` domina porque responde à única pergunta que a consulta faz.
`recency` e `importance` pesam igual: uma memória antiga e importante compete
de igual para igual com uma recente e trivial. `confidence` é o menor porque
desempata, sem que uma dúvida moderada elimine um resultado pertinente.

**Renormalização:** num lookup estruturado (sem consulta textual) o termo
semântico não existe; em vez de valer zero — o que achataria todos os
resultados —, ele sai da soma e os pesos restantes são renormalizados por
`Σ wᵢ`. É a diferença entre "não perguntei sobre semântica" e "a semântica é
péssima".

## Meias-vidas por tipo

A âncora é `updated_at`, não `last_accessed_at`: reforçar uma memória a
rejuvenesce (houve evidência nova); consultá-la, não. Ancorar em acesso criaria
um viés de popularidade — o que já foi recuperado uma vez continuaria ganhando
por ter sido recuperado.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Final

from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import MemoryType, StoredMemory


@dataclass(frozen=True, slots=True, kw_only=True)
class RankingWeights:
    """Pesos da combinação. Ajustáveis e injetáveis — nunca aprendidos."""

    semantic: float = 0.45
    recency: float = 0.20
    importance: float = 0.20
    confidence: float = 0.15

    def __post_init__(self) -> None:
        for name in ("semantic", "recency", "importance", "confidence"):
            value: float = getattr(self, name)
            if value < 0.0:
                raise InvalidMemoryError(f"peso {name} não pode ser negativo, recebido {value!r}")
        if self.recency + self.importance + self.confidence <= 0.0:
            raise InvalidMemoryError(
                "a soma dos pesos não-semânticos precisa ser positiva, "
                "para que um lookup estruturado sempre tenha o que renormalizar"
            )


DEFAULT_RANKING_WEIGHTS: Final = RankingWeights()

DEFAULT_HALF_LIVES: Final[Mapping[MemoryType, timedelta]] = MappingProxyType(
    {
        # Vive dentro de uma tarefa/conversa.
        MemoryType.WORKING: timedelta(hours=2),
        # Dura o que a tarefa durar.
        MemoryType.TASK: timedelta(days=7),
        # Um acontecimento perde pertinência rápido.
        MemoryType.EPISODIC: timedelta(days=30),
        # Muda, mas devagar.
        MemoryType.PREFERENCE: timedelta(days=180),
        # Conhecimento consolidado.
        MemoryType.SEMANTIC: timedelta(days=365),
        # "Como fazer" envelhece pouco.
        MemoryType.PROCEDURAL: timedelta(days=365),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RelevanceScore:
    """O total, e o detalhamento de cada termo — o que torna o ranking
    explicável sem depurar código (`jarvis memory search --explain`)."""

    total: float
    semantic: float | None
    recency: float
    importance: float
    confidence: float
    weights: RankingWeights


def recency_score(
    stored: StoredMemory,
    *,
    now: datetime,
    half_lives: Mapping[MemoryType, timedelta] = DEFAULT_HALF_LIVES,
) -> float:
    """`0.5` exatamente na meia-vida; nunca negativo mesmo com `now` no passado."""
    half_life = half_lives.get(stored.memory.type)
    if half_life is None:
        raise InvalidMemoryError(
            f"nenhuma meia-vida definida para o tipo {stored.memory.type.value}"
        )

    age_seconds = max((now - stored.updated_at).total_seconds(), 0.0)
    half_life_seconds = half_life.total_seconds()
    return float(0.5 ** (age_seconds / half_life_seconds))


def score(
    stored: StoredMemory,
    *,
    now: datetime,
    semantic: float | None = None,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
    half_lives: Mapping[MemoryType, timedelta] = DEFAULT_HALF_LIVES,
) -> RelevanceScore:
    """A soma ponderada de §13 do plano. `semantic=None` renormaliza sem esse termo."""
    recency = recency_score(stored, now=now, half_lives=half_lives)
    importance = stored.memory.importance
    confidence = stored.confidence

    weighted = weights.recency * recency + weights.importance * importance
    weighted += weights.confidence * confidence
    weight_sum = weights.recency + weights.importance + weights.confidence

    if semantic is not None:
        # O cosseno pode ser negativo; achata para [0, 1] antes de compor a média.
        semantic = max(0.0, semantic)
        weighted += weights.semantic * semantic
        weight_sum += weights.semantic

    return RelevanceScore(
        total=weighted / weight_sum,
        semantic=semantic,
        recency=recency,
        importance=importance,
        confidence=confidence,
        weights=weights,
    )
