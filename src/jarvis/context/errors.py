"""Erros do Context Engine.

Segue a taxonomia compartilhada de
[`architecture-contracts.md §13`](../../../docs/architecture-contracts.md#13-error-contract):
violação de invariante do domínio é permanente, falha de adapter é transitória por
padrão. Não existe uma categoria `ProviderError` compartilhada ainda — ela só faz
sentido quando houver um segundo provider fora do Context Engine (LLM/MCP, Fase 4).
"""

from jarvis.errors import DomainError, InfrastructureError


class InvalidContextError(DomainError):
    """Uma observação, rótulo ou payload viola uma invariante do contexto."""


class ContextProviderError(InfrastructureError):
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
