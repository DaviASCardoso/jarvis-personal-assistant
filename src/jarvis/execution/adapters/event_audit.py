"""`AuditLog` implementado sobre o Event System.

[ADR-0017](../../../../docs/adr/0017-audit-trail-as-events.md): a trilha de
auditoria **é** o log de eventos. Não há `audit.db`. O Event Store já é durável,
imutável, consultável por `correlation_id` e deduplicado por `event_id` — um
segundo banco só acrescentaria um schema a manter e uma fonte a divergir.

Este adapter é fino de propósito: traduz `AuditEntry` em `Event` e publica. A
decisão sobre o que é fail-closed e o que é best-effort **não** mora aqui — mora
em quem chama, porque só o chamador sabe se o efeito já aconteceu.
"""

import logging

from jarvis.audit import AuditEntry
from jarvis.events.publisher import EventPublisher
from jarvis.execution.events import ACTION_SOURCE, audit_event

logger = logging.getLogger(__name__)


class EventAuditLog:
    """Publica cada marco de auditoria como um evento imutável."""

    def __init__(self, publisher: EventPublisher, *, source: str = ACTION_SOURCE) -> None:
        self._publisher = publisher
        self._source = source

    def record(self, entry: AuditEntry) -> None:
        result = self._publisher.publish(audit_event(entry, source=self._source))
        if result.is_duplicate:
            # Republicar o mesmo marco é esperado num retry; o store trata como
            # no-op e a trilha não ganha duplicata.
            logger.debug(
                "audit.duplicate_marker",
                extra={"execution_id": entry.execution_id, "marker": entry.marker},
            )
