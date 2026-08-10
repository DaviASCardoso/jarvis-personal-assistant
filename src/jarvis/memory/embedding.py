"""Identidade do espaço vetorial e o embedding armazenado numa memória.

`PHASE-3.md §8` exige que "o sistema saiba qual provider/modelo produziu
determinado embedding" e que vetores de modelos diferentes "não devem ser
comparados silenciosamente". `EmbeddingModel` é a chave dessa comparação —
`(provider, model, dimensions)` — e `MemoryEmbedding.is_comparable_to` é o único
lugar que decide se dois vetores podem entrar no mesmo cálculo de cosseno.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.memory.errors import InvalidMemoryError


def require_aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidMemoryError(
            f"{field_name} precisa ser um datetime, recebido {type(value).__name__}"
        )
    if value.utcoffset() is None:
        raise InvalidMemoryError(f"{field_name} precisa ser timezone-aware, recebido {value!r}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingModel:
    """Identidade de um espaço vetorial. Dois vetores só se comparam se isto coincidir."""

    provider: str
    model: str
    dimensions: int

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise InvalidMemoryError("embedding provider não pode ser vazio")
        if not self.model.strip():
            raise InvalidMemoryError("embedding model não pode ser vazio")
        if self.dimensions <= 0:
            raise InvalidMemoryError(
                f"embedding dimensions precisa ser positivo, recebido {self.dimensions}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEmbedding:
    """Um vetor, com a identidade do modelo que o produziu e quando."""

    vector: tuple[float, ...]
    model: EmbeddingModel
    created_at: datetime

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        if len(self.vector) != self.model.dimensions:
            raise InvalidMemoryError(
                f"vetor tem {len(self.vector)} posições, esperado {self.model.dimensions}"
            )
        if any(not math.isfinite(value) for value in self.vector):
            raise InvalidMemoryError("vetor de embedding contém valor não finito")

        created_at = require_aware(self.created_at, field_name="embedding.created_at")
        overwrite(self, "created_at", created_at.astimezone(UTC))

    def is_comparable_to(self, other: "MemoryEmbedding") -> bool:
        """Regra única de compatibilidade: mesmo `(provider, model, dimensions)`."""
        return self.model == other.model


def cosine_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Similaridade de cosseno em `[-1.0, 1.0]`; vetor nulo devolve `0.0`.

    Não valida compatibilidade de modelo — quem chama já filtrou por
    `is_comparable_to` (ver `memory/retrieval.py`). Só exige a mesma dimensão.
    """
    if len(a) != len(b):
        raise InvalidMemoryError("vetores de dimensões diferentes não são comparáveis")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
