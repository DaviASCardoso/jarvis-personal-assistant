"""Interruption Policy: decide **quando** algo já considerado importante deve
de fato interromper o usuário agora.

Reaproveita o resultado do `ImportanceAssessment` da Fase 4
(`agent/importance.py`) para "importância", "atividade" e "foco" —
`interruption_cost` já combina disponibilidade e atividade (inclusive
`focus`, presente tanto em `_BUSY_LABELS` quanto em `_DEMANDING_ACTIVITIES`).
Duplicar esse cálculo aqui seria a abstração especulativa que
`architecture-contracts.md §1` proíbe. O reaproveitamento é só do **número**
(`assessment.total`), não do tipo: `jarvis.proactivity` não importa
`jarvis.agent` — o composition root extrai o total antes de chamar esta
política, mesma disciplina que mantém `jarvis.decisions` sem depender de
`Decision`/`AgentTurn` (`docs/phase-7-plan.md §1.1`).

O que esta política acrescenta é o que o Importance Engine não vê, porque não é
sobre o evento — é sobre **agora**: uma conversa em andamento, o relógio, e o
que já foi dito recentemente. "Localização" (item do checklist do roadmap) é
considerada e registrada como neutra: o Location Provider nunca foi
implementado (decisão da subfase 2.2), e fingir que pesou algo que o sistema
não sabe seria pior do que admitir a ausência.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from jarvis.context.model import CurrentContext
from jarvis.context.observation import Freshness


@dataclass(frozen=True, slots=True, kw_only=True)
class RecentNotification:
    """O suficiente para deduplicar — nunca o corpo da notificação.

    Definido aqui, e não em `jarvis.notify`, porque a dependência corre na
    direção `notify → proactivity` (notificação usa política de interrupção),
    nunca o contrário. `jarvis.notify.manager` traduz seu próprio histórico
    para este tipo antes de chamar `InterruptionPolicy.evaluate`.
    """

    subject: str
    sent_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class InterruptionSettings:
    importance_threshold: float = 0.6
    # `None` desliga a janela de silêncio — sem hora configurada, não há o que
    # aplicar. Horas locais, 0-23; `start > end` significa "atravessa a
    # meia-noite" (ex. 22 às 7).
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    cooldown_seconds: float = 900.0

    def __post_init__(self) -> None:
        for name, value in (
            ("quiet_hours_start", self.quiet_hours_start),
            ("quiet_hours_end", self.quiet_hours_end),
        ):
            if value is not None and not 0 <= value <= 23:
                raise ValueError(f"{name} precisa estar entre 0 e 23, recebido {value}")
        if self.cooldown_seconds < 0:
            raise ValueError(
                f"cooldown_seconds não pode ser negativo, recebido {self.cooldown_seconds}"
            )


DEFAULT_INTERRUPTION_SETTINGS: InterruptionSettings = InterruptionSettings()


@dataclass(frozen=True, slots=True, kw_only=True)
class InterruptionDecision:
    should_interrupt: bool
    reason: str
    suppressed_by: str | None = None
    considered: tuple[str, ...] = field(default_factory=tuple)


def _local_hour(context: CurrentContext, *, now: datetime) -> int | None:
    """Hora local a partir de `utc_offset`, ou `None` se não observado/vencido.

    `utc_offset` é o formato `+HH:MM`/`-HH:MM` que `EnvironmentContext`
    documenta — não um `datetime`, então a conversão é aritmética de texto,
    não `astimezone`.
    """
    observation = context.environment.utc_offset
    if observation is None or observation.freshness(now) is Freshness.STALE:
        return None
    raw = observation.value
    try:
        sign = 1 if raw[0] == "+" else -1
        hours, minutes = raw[1:].split(":")
        offset = timedelta(hours=int(hours), minutes=int(minutes)) * sign
    except (IndexError, ValueError):
        return None
    return (now.astimezone(UTC) + offset).hour


def _in_quiet_hours(hour: int, *, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class InterruptionPolicy:
    """Função determinística sobre o que recebe — nenhum estado próprio.

    O histórico de notificações recentes é responsabilidade de quem chama
    (`NotificationManager`), não desta classe: a política é a mesma regra
    testável tanto em memória quanto sobre um histórico persistido no futuro.
    """

    def __init__(self, settings: InterruptionSettings = DEFAULT_INTERRUPTION_SETTINGS) -> None:
        self._settings = settings

    def evaluate(
        self,
        *,
        importance: float,
        context: CurrentContext,
        subject: str,
        recent: Sequence[RecentNotification] = (),
        now: datetime,
    ) -> InterruptionDecision:
        considered: list[str] = []

        considered.append(f"importance={importance:.3f}")
        if importance < self._settings.importance_threshold:
            return InterruptionDecision(
                should_interrupt=False,
                reason="below_importance_threshold",
                suppressed_by="importance",
                considered=tuple(considered),
            )

        conversation = context.conversation.active_id
        if (
            conversation is not None
            and conversation.value is not None
            and conversation.freshness(now) is Freshness.FRESH
        ):
            considered.append("conversation=active")
            return InterruptionDecision(
                should_interrupt=False,
                reason="conversation_in_progress",
                suppressed_by="conversation",
                considered=tuple(considered),
            )
        considered.append("conversation=none")

        hour = _local_hour(context, now=now)
        if hour is None:
            considered.append("quiet_hours=unknown_offset")
        else:
            considered.append(f"local_hour={hour}")
            start, end = self._settings.quiet_hours_start, self._settings.quiet_hours_end
            in_quiet_hours = (
                start is not None
                and end is not None
                and _in_quiet_hours(hour, start=start, end=end)
            )
            if in_quiet_hours:
                return InterruptionDecision(
                    should_interrupt=False,
                    reason="quiet_hours",
                    suppressed_by="quiet_hours",
                    considered=tuple(considered),
                )

        place = context.environment.place
        considered.append(f"location={place.value}" if place is not None else "location=unknown")

        cooldown = timedelta(seconds=self._settings.cooldown_seconds)
        for sent in recent:
            if sent.subject == subject and now - sent.sent_at < cooldown:
                considered.append(f"cooldown_subject={subject}")
                return InterruptionDecision(
                    should_interrupt=False,
                    reason="notification_cooldown",
                    suppressed_by="cooldown",
                    considered=tuple(considered),
                )

        return InterruptionDecision(
            should_interrupt=True,
            reason="importance_above_threshold",
            considered=tuple(considered),
        )
