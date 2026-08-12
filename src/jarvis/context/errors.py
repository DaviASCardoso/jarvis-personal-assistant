"""Erros do Context Engine.

Segue a taxonomia compartilhada de
[`architecture-contracts.md §13`](../../../docs/architecture-contracts.md#13-error-contract):
violação de invariante do domínio é permanente, falha de adapter é transitória por
padrão. `ContextProviderError` herda de `ProviderError` desde a Fase 4, quando o
`LLMProvider` deu à categoria compartilhada um segundo consumidor real.
"""

from jarvis.errors import DomainError, InfrastructureError, ProviderError


class InvalidContextError(DomainError):
    """Uma observação, rótulo ou payload viola uma invariante do contexto."""


class ContextProviderError(ProviderError):
    """Falha declarada de um Context Provider.

    É o único erro de provider que o agregador degrada: um adapter que deixa
    escapar a exceção nativa tem bug, e bug não vira degradação silenciosa.
    """


class ContextSnapshotError(InfrastructureError):
    """Falha na camada de persistência de snapshots."""


class ContextSnapshotWriteError(ContextSnapshotError):
    """Falha ao persistir ou expirar um snapshot."""


class ContextSnapshotReadError(ContextSnapshotError):
    """Falha ao recuperar ou decodificar um snapshot."""
