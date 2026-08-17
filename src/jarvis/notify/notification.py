"""`Notification`: uma mensagem já formada, pronta para ser entregue.

Este componente não decide o **motivo** de notificar — recebe uma `Notification`
já pronta, monta a decisão de interrupção (`jarvis.proactivity.InterruptionPolicy`)
e escolhe um canal (`architecture-contracts.md §3.10`: "recebe uma `Notification`
já formada").
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from jarvis.notify.errors import InvalidNotificationError

MAX_TITLE_LENGTH: Final = 120
MAX_BODY_LENGTH: Final = 500


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


def _require_text(value: str, *, field_name: str, max_length: int) -> str:
    if not value.strip():
        raise InvalidNotificationError(f"{field_name} não pode ser vazio")
    if len(value) > max_length:
        raise InvalidNotificationError(f"{field_name} excede {max_length} caracteres")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class Notification:
    """`subject` é a chave de deduplicação/cooldown da Interruption Policy —
    não é o corpo da mensagem, é um rótulo curto e estável (ex. o `event_type`
    ou `trigger_id` que a originou), para que duas notificações sobre o mesmo
    assunto sejam reconhecidas como tal mesmo com `title`/`body` diferentes.
    """

    notification_id: str
    subject: str
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    correlation_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        if not self.notification_id.strip():
            raise InvalidNotificationError("notification_id não pode ser vazio")
        overwrite(self, "subject", _require_text(self.subject, field_name="subject", max_length=64))
        overwrite(
            self,
            "title",
            _require_text(self.title, field_name="title", max_length=MAX_TITLE_LENGTH),
        )
        overwrite(
            self, "body", _require_text(self.body, field_name="body", max_length=MAX_BODY_LENGTH)
        )
        if not self.correlation_id.strip():
            raise InvalidNotificationError("correlation_id não pode ser vazio")
        if self.created_at.utcoffset() is None:
            raise InvalidNotificationError("created_at precisa ser timezone-aware")
        overwrite(self, "created_at", self.created_at.astimezone(UTC))
