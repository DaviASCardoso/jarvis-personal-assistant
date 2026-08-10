"""A projeção: como observações de fontes distintas viram um estado por campo.

Regra de conflito, direta de
[contracts §6](../../../docs/architecture-contracts.md#6-context-contract):
**o `observed_at` mais recente vence, por campo**. O contrato não define o empate,
e a menor regra determinística possível é a adotada aqui — em empate o incumbente
permanece. Isso basta para tornar a reaplicação da *mesma* observação um no-op, que
é a idempotência exigida do consumer.

`confidence` **não** participa da resolução: o contrato o descreve como metadado de
proveniência, e promovê-lo a critério de autoridade seria criar regra nova sem caso
de uso que a pressione.

Um conflito (mesmo campo, valores diferentes) é sempre devolvido **e** logado —
nunca descartado em silêncio. O log carrega campo, origens e tempos; jamais os
valores, que podem ser dado pessoal.

A merge é escrita campo a campo, de propósito: `getattr` por nome economizaria
linhas e devolveria `Any`, e um rename passaria despercebido.
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime

from jarvis.context.freshness import DEFAULT_TTL_POLICY, TtlPolicy
from jarvis.context.model import (
    ActivityContext,
    ContextField,
    ContextUpdate,
    ConversationContext,
    CurrentContext,
    DeviceContext,
    EnvironmentContext,
    ScheduleContext,
    TaskContext,
    UserContext,
)
from jarvis.context.observation import Observation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextConflict:
    """Duas fontes discordaram sobre um campo, e uma delas perdeu.

    Existe como dado, e não apenas como linha de log, para que quem chamou possa
    reagir ao conflito sem depender de inspecionar logs.
    """

    field: ContextField
    winner_source: str
    loser_source: str
    winner_observed_at: datetime
    loser_observed_at: datetime


def _resolve[T](
    field: ContextField,
    current: Observation[T] | None,
    incoming: Observation[T] | None,
    *,
    policy: TtlPolicy,
) -> tuple[Observation[T] | None, ContextConflict | None]:
    if incoming is None:
        return current, None

    stamped = replace(incoming, ttl=policy.ttl_for(field))
    if current is None:
        return stamped, None

    # Empate mantém o incumbente: reaplicar a mesma observação não muda nada.
    if stamped.observed_at > current.observed_at:
        winner, loser = stamped, current
    else:
        winner, loser = current, stamped

    if winner.value == loser.value:
        return winner, None

    return winner, ContextConflict(
        field=field,
        winner_source=winner.source,
        loser_source=loser.source,
        winner_observed_at=winner.observed_at,
        loser_observed_at=loser.observed_at,
    )


class ContextProjection:
    """O estado corrente por campo, e a única porta para alterá-lo.

    Não é um port: implementação única, nenhum substituto real (contrato §1).
    """

    def __init__(self, *, policy: TtlPolicy = DEFAULT_TTL_POLICY) -> None:
        self._policy = policy
        self._user = UserContext()
        self._environment = EnvironmentContext()
        self._device = DeviceContext()
        self._activity = ActivityContext()
        self._schedule = ScheduleContext()
        self._conversation = ConversationContext()
        self._task = TaskContext()

    def apply(self, update: ContextUpdate) -> tuple[ContextConflict, ...]:
        conflicts: list[ContextConflict] = []

        def take[T](
            field: ContextField,
            current: Observation[T] | None,
            incoming: Observation[T] | None,
        ) -> Observation[T] | None:
            merged, conflict = _resolve(field, current, incoming, policy=self._policy)
            if conflict is not None:
                conflicts.append(conflict)
                logger.info(
                    "context.conflict",
                    extra={
                        "field": conflict.field.value,
                        "winner_source": conflict.winner_source,
                        "loser_source": conflict.loser_source,
                        "winner_observed_at": conflict.winner_observed_at.isoformat(),
                        "loser_observed_at": conflict.loser_observed_at.isoformat(),
                    },
                )
            if merged is not current and merged is not None:
                logger.debug(
                    "context.field_updated",
                    extra={
                        "field": field.value,
                        "source": merged.source,
                        "observed_at": merged.observed_at.isoformat(),
                    },
                )
            return merged

        self._user = UserContext(
            availability=take(
                ContextField.AVAILABILITY, self._user.availability, update.availability
            )
        )
        self._environment = EnvironmentContext(
            utc_offset=take(
                ContextField.UTC_OFFSET, self._environment.utc_offset, update.utc_offset
            ),
            place=take(ContextField.PLACE, self._environment.place, update.place),
        )
        self._device = DeviceContext(
            device_id=take(ContextField.DEVICE_ID, self._device.device_id, update.device_id)
        )
        self._activity = ActivityContext(
            current=take(ContextField.ACTIVITY, self._activity.current, update.activity)
        )
        self._schedule = ScheduleContext(
            next_entry_at=take(
                ContextField.NEXT_ENTRY_AT, self._schedule.next_entry_at, update.next_entry_at
            )
        )
        self._conversation = ConversationContext(
            active_id=take(
                ContextField.CONVERSATION, self._conversation.active_id, update.conversation
            )
        )
        self._task = TaskContext(
            active_id=take(ContextField.TASK, self._task.active_id, update.task)
        )

        return tuple(conflicts)

    def snapshot_of(self, *, as_of: datetime) -> CurrentContext:
        return CurrentContext(
            as_of=as_of,
            user=self._user,
            environment=self._environment,
            device=self._device,
            activity=self._activity,
            schedule=self._schedule,
            conversation=self._conversation,
            task=self._task,
        )
