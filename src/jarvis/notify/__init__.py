"""Notification Manager (Fase 7.3): entrega uma `Notification` já formada por
um canal (console, voz, silencioso), com prioridade e deduplicação.

`architecture-contracts.md §3.10`. Depende de `jarvis.proactivity` para a
Interruption Policy (a pergunta "quando" é resolvida lá, não duplicada aqui) e
não depende de `jarvis.agent`, `jarvis.execution` nem `jarvis.events`.
"""

from jarvis.notify.errors import InvalidNotificationError, NotifyError
from jarvis.notify.manager import DEFAULT_HISTORY_LIMIT, DeliveryOutcome, NotificationManager
from jarvis.notify.notification import Notification, NotificationPriority
from jarvis.notify.ports import DeliveryResult, DeliveryStatus, NotificationChannel

__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "DeliveryOutcome",
    "DeliveryResult",
    "DeliveryStatus",
    "InvalidNotificationError",
    "Notification",
    "NotificationChannel",
    "NotificationManager",
    "NotificationPriority",
    "NotifyError",
]
