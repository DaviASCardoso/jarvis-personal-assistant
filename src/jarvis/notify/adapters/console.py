"""Canal "desktop": uma linha estruturada em stdout/stderr, não um toast do SO.

Decisão explícita, não lacuna — ver ADR-0028. Um toast nativo (via
`subprocess`/PowerShell no Windows) exigiria interpolar conteúdo de terceiros
num comando de shell (risco de injeção — `security-review` deste mesmo
projeto rejeitaria) ou uma dependência nova sem necessidade concreta hoje. O
console é a superfície visual que este agente pessoal, hoje, já tem: o
terminal onde `jarvis run` roda e o painel de observabilidade (Fase 6). O
mesmo `NotificationChannel` port permite trocar por um adapter de toast nativo
sem tocar `NotificationManager`, quando isso vier a valer a pena.
"""

import sys
from collections.abc import Callable
from typing import TextIO

from jarvis.notify.notification import Notification
from jarvis.notify.ports import DeliveryResult, DeliveryStatus


class ConsoleNotificationChannel:
    def __init__(
        self, *, stream: TextIO = sys.stderr, write: Callable[[str], None] | None = None
    ) -> None:
        self._write = write if write is not None else lambda line: print(line, file=stream)

    @property
    def channel_id(self) -> str:
        return "console"

    def send(self, notification: Notification) -> DeliveryResult:
        self._write(
            f"[jarvis] {notification.priority.value.upper():<6} "
            f"{notification.title}: {notification.body}"
        )
        return DeliveryResult(channel=self.channel_id, status=DeliveryStatus.SENT)
