"""`NotificationManager`: aplica a Interruption Policy e entrega por um canal.

Fluxo: `InterruptionPolicy.evaluate` decide **se** interrompe agora; se sim, os
canais são tentados em ordem de preferência até um aceitar (`SENT`) ou a lista
acabar. Silent mode força supressão de tudo abaixo de `URGENT` — registrado
como decisão, nunca como entrega perdida em silêncio de verdade (o
`DeliveryOutcome` sempre existe, mesmo quando `delivered=False`).

Publicar `notification.sent`/`notification.suppressed` como evento **não** é
responsabilidade deste módulo: `architecture-contracts.md §3.10` não lista o
Event System entre as dependências permitidas da Notification System. Quem
publica é o composition root, mesmo padrão de `voice_session_event` em
`cli.py`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from jarvis.context.model import CurrentContext
from jarvis.notify.notification import Notification, NotificationPriority
from jarvis.notify.ports import DeliveryResult, DeliveryStatus, NotificationChannel
from jarvis.proactivity.interruption import (
    DEFAULT_INTERRUPTION_SETTINGS,
    InterruptionDecision,
    InterruptionPolicy,
    RecentNotification,
)

DEFAULT_HISTORY_LIMIT = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryOutcome:
    notification: Notification
    delivered: bool
    decision: InterruptionDecision
    result: DeliveryResult | None = None


class NotificationManager:
    def __init__(
        self,
        *,
        channels: Sequence[NotificationChannel] = (),
        interruption_policy: InterruptionPolicy | None = None,
        silent_mode: bool = False,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._channels = tuple(channels)
        self._policy = (
            interruption_policy
            if interruption_policy is not None
            else InterruptionPolicy(DEFAULT_INTERRUPTION_SETTINGS)
        )
        self._silent_mode = silent_mode
        self._history_limit = history_limit
        self._history: list[RecentNotification] = []
        self._clock = clock

    @property
    def history(self) -> tuple[RecentNotification, ...]:
        return tuple(self._history)

    def notify(
        self, notification: Notification, *, importance: float, context: CurrentContext
    ) -> DeliveryOutcome:
        now = self._clock()
        decision = self._policy.evaluate(
            importance=importance,
            context=context,
            subject=notification.subject,
            recent=tuple(self._history),
            now=now,
        )
        if not decision.should_interrupt:
            return DeliveryOutcome(notification=notification, delivered=False, decision=decision)

        if self._silent_mode and notification.priority is not NotificationPriority.URGENT:
            silenced = replace(
                decision,
                should_interrupt=False,
                reason="silent_mode",
                suppressed_by="silent_mode",
            )
            return DeliveryOutcome(notification=notification, delivered=False, decision=silenced)

        result = self._deliver(notification)
        delivered = result.status is DeliveryStatus.SENT
        if delivered:
            self._remember(notification, now=now)
        return DeliveryOutcome(
            notification=notification, delivered=delivered, decision=decision, result=result
        )

    def _deliver(self, notification: Notification) -> DeliveryResult:
        last: DeliveryResult | None = None
        for channel in self._channels:
            result = channel.send(notification)
            last = result
            if result.status is DeliveryStatus.SENT:
                return result
        if last is not None:
            return last
        return DeliveryResult(
            channel="none", status=DeliveryStatus.FAILED, detail="nenhum canal configurado"
        )

    def _remember(self, notification: Notification, *, now: datetime) -> None:
        self._history.append(RecentNotification(subject=notification.subject, sent_at=now))
        if len(self._history) > self._history_limit:
            del self._history[: len(self._history) - self._history_limit]
