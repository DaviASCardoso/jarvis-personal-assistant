"""Erros do Memory System.

Segue a taxonomia compartilhada de
[`architecture-contracts.md §13`](../../../docs/architecture-contracts.md#13-error-contract):
violação de invariante do domínio é permanente, falha de adapter é transitória por
padrão. `EmbeddingProviderError` herda de `ProviderError` desde a Fase 4, quando
o `LLMProvider` deu à categoria compartilhada um segundo consumidor real.
"""

from jarvis.errors import DomainError, InfrastructureError, ProviderError


class InvalidMemoryError(DomainError):
    """Uma memória, payload ou consulta viola uma invariante do domínio."""


class EmbeddingProviderError(ProviderError):
    """Falha declarada de um `EmbeddingProvider`.

    É o único erro de provider que o `MemoryManager` degrada (memória criada sem
    embedding, com aviso): um adapter que deixa escapar exceção nativa tem bug, e
    bug não vira degradação silenciosa.
    """


class MemoryRepositoryError(InfrastructureError):
    """Falha na camada de persistência de memórias."""


class MemoryWriteError(MemoryRepositoryError):
    """Falha ao persistir, atualizar ou remover uma memória."""


class MemoryReadError(MemoryRepositoryError):
    """Falha ao recuperar ou decodificar uma memória."""
