"""`HashingEmbeddingProvider`: o adapter local e determinístico de `EmbeddingProvider`.

Produz vetores por *hashing* de trigramas de caracteres do texto normalizado —
**similaridade lexical, não semântica**. Existe para que o Memory System
funcione de ponta a ponta sem nenhum LLM ou serviço externo configurado
(`PHASE-3.md §17`); um provider de vendor real, com similaridade semântica de
verdade, é escopo da Fase 4, quando houver credenciais e configuração para ele.

Determinístico: o mesmo texto produz sempre o mesmo vetor, entre execuções e
processos — é o que torna os testes de retrieval reproduzíveis sem gravar
fixtures de modelo.
"""

import hashlib
import math
import unicodedata
from typing import Final

from jarvis.memory.embedding import EmbeddingModel
from jarvis.memory.errors import EmbeddingProviderError

DEFAULT_DIMENSIONS: Final = 256
_NGRAM_SIZE: Final = 3


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    without_accents = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def _ngrams(text: str, *, size: int = _NGRAM_SIZE) -> list[str]:
    # Preenchimento nas bordas para que palavras curtas ainda produzam um n-grama.
    padded = f"{' ' * (size - 1)}{text}{' ' * (size - 1)}"
    if len(padded) < size:
        return [padded]
    return [padded[index : index + size] for index in range(len(padded) - size + 1)]


class HashingEmbeddingProvider:
    """Similaridade lexical por hashing de n-gramas — não confundir com um
    modelo semântico real."""

    def __init__(self, *, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        self._model = EmbeddingModel(provider="hashing", model="hashing-v1", dimensions=dimensions)

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    def embed(self, text: str) -> tuple[float, ...]:
        if not text.strip():
            raise EmbeddingProviderError("não é possível gerar embedding de um texto vazio")

        dimensions = self._model.dimensions
        buckets = [0.0] * dimensions
        for ngram in _ngrams(_normalize(text)):
            digest = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            buckets[index] += sign

        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0.0:
            # Só ocorre por cancelamento exato de sinais entre n-gramas — raro,
            # mas o provider nunca devolve o vetor nulo (indistinguível de "sem
            # embedding" em várias comparações).
            buckets[0] = 1.0
            norm = 1.0
        return tuple(value / norm for value in buckets)
