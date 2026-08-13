"""Ports da camada de execução.

`ActionRepository` é o único port aqui. `ActionExecutor` e `ActionEventConsumer`
não são ports: implementação única, nenhum substituto real — mesma assimetria dos
componentes anteriores.

O que este repositório guarda é **estado operacional**, na acepção de
`architecture-contracts.md §12`: mutável, apagável, pertencente ao componente
dono. Não é fato histórico — fato histórico é evento, e a trilha de auditoria vai
para o Event Store.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from jarvis.execution.model import ExecutionStatus, PendingAction


class ActionRepository(Protocol):
    """Registro durável das execuções e do seu estado.

    Sem `update` genérico, de propósito: cada método nomeia exatamente a
    transição que autoriza. Os parâmetros de uma ação **nunca** são alterados
    depois de gravados — mudá-los invalidaria o `parameters_fingerprint` que a
    confirmação e a aprovação usam para se amarrar a esta execução.
    """

    def put(self, pending: PendingAction) -> None:
        """Grava a ação. Reescrever um `execution_id` existente é erro, não upsert."""
        ...

    def get(self, execution_id: str) -> PendingAction | None: ...

    def list_by_status(
        self, status: ExecutionStatus, *, limit: int | None = None
    ) -> Sequence[PendingAction]: ...

    def mark(
        self, execution_id: str, *, status: ExecutionStatus, moment: datetime, reason: str = ""
    ) -> PendingAction: ...

    def confirm(self, execution_id: str, *, moment: datetime) -> PendingAction:
        """Registra que o usuário confirmou. Não muda o status.

        A separação é o ponto: confirmar é um fato sobre o usuário; executar é
        uma decisão que ainda passa pelo Policy Engine depois.
        """
        ...

    def expire_pending(self, *, moment: datetime) -> Sequence[PendingAction]:
        """Marca como `expired` toda pendência vencida. Devolve as que mudaram."""
        ...
