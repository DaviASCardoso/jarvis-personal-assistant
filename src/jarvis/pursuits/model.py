"""`PursuitState`: o checkpoint de um `agent pursue` em andamento (Fase 10.5).

Estado operacional, apagável — mesma cautela de privacidade do `PendingAction`
([ADR-0014](../../../docs/adr/0014-confirmation-state-and-event-answers.md)):
o Decision Log e a trilha de auditoria não guardam parâmetros de ação de
propósito, então retomar um `agent pursue` interrompido não pode depender do
Event Store. `PursuitState` vive fora dele, como `BackgroundTask` (7.5).

Não é o mesmo conceito que `BackgroundTask`: uma tarefa em background espera
**tempo** passar; um `PursuitState` guarda o ponto exato de uma sequência de
turnos de raciocínio que só o próprio `agent pursue` sabe conduzir — não há
retry nem backoff aqui, só "onde eu parei".
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from jarvis.events.event import JsonValue
from jarvis.pursuits.errors import PursuitError


class PursuitStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DENIED = "denied"
    STOPPED_REPEATED_PROPOSAL = "stopped_repeated_proposal"
    STOPPED_MAX_STEPS = "stopped_max_steps"

    @property
    def is_resumable(self) -> bool:
        """Só `completed` fecha a porta — todos os outros são um ponto onde
        `--resume` faz sentido, inclusive um teto de passos atingido: o
        usuário pode querer continuar com um orçamento novo."""
        return self is not PursuitStatus.COMPLETED


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise PursuitError(f"{field_name} precisa ser timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class PursuitState:
    """`last_action_result`/`previous_proposal` viajam como documentos JSON
    soltos, não tipados aqui — quem sabe o formato exato
    (`ActionResultSummary`, `(skill, parameters)`) é `cli._agent_pursue`, o
    único lugar que os produz e consome. Modelar esse acoplamento aqui
    duplicaria uma forma que já existe em `jarvis.agent`."""

    pursuit_id: str
    goal: str
    conversation_id: str
    max_steps: int
    step: int
    status: PursuitStatus
    last_action_result: Mapping[str, JsonValue] | None
    previous_proposal: Mapping[str, JsonValue] | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        if not self.pursuit_id.strip():
            raise PursuitError("pursuit_id não pode ser vazio")
        if not self.goal.strip():
            raise PursuitError("goal não pode ser vazio")
        if not self.conversation_id.strip():
            raise PursuitError("conversation_id não pode ser vazio")
        if self.max_steps < 1:
            raise PursuitError(f"max_steps precisa ser >= 1, recebido {self.max_steps}")
        if self.step < 0:
            raise PursuitError(f"step não pode ser negativo, recebido {self.step}")
        overwrite(self, "created_at", _require_aware(self.created_at, field_name="created_at"))
        overwrite(self, "updated_at", _require_aware(self.updated_at, field_name="updated_at"))
        if self.last_action_result is not None:
            overwrite(self, "last_action_result", MappingProxyType(dict(self.last_action_result)))
        if self.previous_proposal is not None:
            overwrite(self, "previous_proposal", MappingProxyType(dict(self.previous_proposal)))
