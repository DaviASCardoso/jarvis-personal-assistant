"""Port de canal de notificação.

`NotificationChannel` é o único port deste componente — mesma assimetria de
`ActionRepository`/`ActionExecutor`: canais têm implementações concretas
substituíveis (console, voz, e no futuro um toast nativo do SO), o
`NotificationManager` não.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.notify.notification import Notification


class DeliveryStatus(StrEnum):
    SENT = "sent"
    #: O canal recusou por não poder entregar agora (ex. voz ocupada falando) —
    #: não é falha, é o canal dizendo "tente outro". `NotificationManager`
    #: cai para o próximo canal configurado.
    REFUSED = "refused"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryResult:
    channel: str
    status: DeliveryStatus
    detail: str = ""


class NotificationChannel(Protocol):
    @property
    def channel_id(self) -> str: ...

    def send(self, notification: Notification) -> DeliveryResult: ...
