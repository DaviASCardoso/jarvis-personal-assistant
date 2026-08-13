"""Projeta as respostas de confirmação do usuário no estado da ação.

Segue exatamente o padrão de `ContextEventConsumer` e `MemoryEventConsumer`:
**um consumer projeta, nunca executa**. Aqui isso deixa de ser estilo e vira
segurança — um consumer que disparasse a execução ao receber a confirmação seria
um caminho lateral até a Tool, acionado por um evento, sem passar de novo pelo
Policy Engine. A retomada é um passo separado, feito pelo composition root, e ela
reavalia a política do zero.

Payload malformado levanta `InvalidActionEventError`: o bus manda para
dead-letter sem desfazer o evento já gravado, e a mensagem não repete o payload.
"""

import logging

from jarvis.events.event import RecordedEvent
from jarvis.execution.errors import InvalidActionEventError
from jarvis.execution.events import CONFIRMATION_GRANTED, read_confirmation
from jarvis.execution.model import ExecutionStatus
from jarvis.execution.ports import ActionRepository

logger = logging.getLogger(__name__)


class ActionEventConsumer:
    """Consumer de `action.confirmation_granted` / `action.confirmation_denied`."""

    def __init__(self, repository: ActionRepository) -> None:
        self._repository = repository

    @property
    def name(self) -> str:
        return "action-confirmations"

    def handle(self, event: RecordedEvent) -> None:
        try:
            execution_id, fingerprint, reason = read_confirmation(event.event.payload)
        except ValueError as error:
            raise InvalidActionEventError(
                f"{event.event.event_type}: payload sem os campos exigidos ({error})"
            ) from error

        pending = self._repository.get(execution_id)
        if pending is None:
            raise InvalidActionEventError(
                f"{event.event.event_type}: execução {execution_id} não registrada"
            )

        if pending.status is not ExecutionStatus.AWAITING_CONFIRMATION:
            # Não é erro: uma confirmação que chega depois da expiração ou de uma
            # recusa é um fato tardio, não um payload inválido. Ignorar em
            # silêncio seria pior — daí o log.
            logger.info(
                "action.confirmation_ignored",
                extra={
                    "execution_id": execution_id,
                    "status": pending.status.value,
                    "event_type": event.event.event_type,
                },
            )
            return

        if pending.parameters_fingerprint != fingerprint:
            # Confirmar "apagar A" nunca autoriza "apagar B".
            raise InvalidActionEventError(
                f"{event.event.event_type}: a confirmação não corresponde aos parâmetros "
                f"registrados para {execution_id}"
            )

        moment = event.recorded_at
        if event.event.event_type == CONFIRMATION_GRANTED:
            self._repository.confirm(execution_id, moment=moment)
            logger.info("action.confirmation_granted", extra={"execution_id": execution_id})
            return

        self._repository.mark(
            execution_id,
            status=ExecutionStatus.REJECTED,
            moment=moment,
            reason=reason or "rejected_by_user",
        )
        logger.info("action.confirmation_denied", extra={"execution_id": execution_id})
