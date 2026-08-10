"""Modelo do contexto: os sete subcontextos, a projeção e a moeda de atualização.

`CurrentContext` **não é fonte de verdade** — é uma projeção derivada de eventos e
providers, reconstruível a partir deles
([contracts §6](../../../docs/architecture-contracts.md#6-context-contract)).
Events e Memory são a fonte de verdade.

Os sete subcontextos são exigidos por [ROADMAP 2.1](../../../ROADMAP.md); cada um
tem exatamente um campo nesta fase. `ConversationContext` e `TaskContext` ainda não
têm produtor — o Voice Interface (Fase 6) e o Background Task Manager (Fase 7) são
quem os alimentará. Ficar permanentemente ausente é a semântica correta, e não um
convite para inventar valor.

Valores são rótulos fechados, identificadores opacos e datetimes — **nunca** texto
livre. Um modelo que não pode conter dado pessoal é mais seguro do que um que
promete não logá-lo, e snapshots vão para disco.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from jarvis.context.observation import Observation


class ContextField(StrEnum):
    """Identidade tipada de cada campo do contexto.

    É a chave única usada pela política de TTL, pelos logs de conflito, pela
    listagem de campos vencidos e pela serialização de snapshot — sem ela esses
    quatro lugares voltariam a repetir strings soltas.
    """

    AVAILABILITY = "availability"
    LOCAL_TIME = "local_time"
    PLACE = "place"
    DEVICE_ID = "device_id"
    ACTIVITY = "activity"
    NEXT_ENTRY_AT = "next_entry_at"
    CONVERSATION = "conversation"
    TASK = "task"


@dataclass(frozen=True, slots=True, kw_only=True)
class UserContext:
    availability: Observation[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvironmentContext:
    local_time: Observation[datetime] | None = None
    place: Observation[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceContext:
    device_id: Observation[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityContext:
    # `str | None`: o único caso concreto de ausência observada nesta fase é
    # `user.activity_ended`, que afirma que não há atividade corrente.
    current: Observation[str | None] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduleContext:
    next_entry_at: Observation[datetime] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationContext:
    active_id: Observation[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskContext:
    active_id: Observation[str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentContext:
    """O que o sistema sabe agora, com `as_of` sendo o instante da leitura."""

    as_of: datetime
    user: UserContext = UserContext()
    environment: EnvironmentContext = EnvironmentContext()
    device: DeviceContext = DeviceContext()
    activity: ActivityContext = ActivityContext()
    schedule: ScheduleContext = ScheduleContext()
    conversation: ConversationContext = ConversationContext()
    task: TaskContext = TaskContext()


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextUpdate:
    """O que uma fonte tem a dizer, em uma passada.

    Plano e totalmente tipado, com um campo por `ContextField` — é o que substitui
    um `dict[str, Any]` sem tornar o modelo abstrato. Campo `None` significa "esta
    fonte não fala disso", e não "esta fonte afirma que não há valor".
    """

    availability: Observation[str] | None = None
    local_time: Observation[datetime] | None = None
    place: Observation[str] | None = None
    device_id: Observation[str] | None = None
    activity: Observation[str | None] | None = None
    next_entry_at: Observation[datetime] | None = None
    conversation: Observation[str] | None = None
    task: Observation[str] | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.availability,
                self.local_time,
                self.place,
                self.device_id,
                self.activity,
                self.next_entry_at,
                self.conversation,
                self.task,
            )
        )


def iter_fields(
    context: CurrentContext,
) -> Iterator[tuple[ContextField, Observation[object] | None]]:
    """Percorre os campos na ordem de `ContextField`.

    Enumeração literal em vez de reflexão: `getattr` por nome reintroduziria `Any`
    e faria um rename silencioso passar despercebido.
    """
    yield ContextField.AVAILABILITY, context.user.availability
    yield ContextField.LOCAL_TIME, context.environment.local_time
    yield ContextField.PLACE, context.environment.place
    yield ContextField.DEVICE_ID, context.device.device_id
    yield ContextField.ACTIVITY, context.activity.current
    yield ContextField.NEXT_ENTRY_AT, context.schedule.next_entry_at
    yield ContextField.CONVERSATION, context.conversation.active_id
    yield ContextField.TASK, context.task.active_id
