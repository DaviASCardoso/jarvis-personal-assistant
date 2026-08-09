"""Erros do Event System.

Não existe um `DuplicateEventError`: por contrato
([`architecture-contracts.md §5`](../../../docs/architecture-contracts.md#5-event-contract)
e [ADR-0004](../../../docs/adr/0004-event-immutability-and-timestamps.md)), reinserir
um `event_id` já registrado é um **no-op**, não uma falha. O chamador distingue os
dois casos pelo campo `is_duplicate` de `AppendResult`.
"""

from jarvis.errors import DomainError, InfrastructureError


class InvalidEventError(DomainError):
    """Um `Event` viola uma invariante do contrato de evento."""


class EventStoreError(InfrastructureError):
    """Falha na camada de persistência de eventos."""


class EventAppendError(EventStoreError):
    """Falha ao persistir um evento."""


class EventReadError(EventStoreError):
    """Falha ao recuperar eventos já persistidos."""
