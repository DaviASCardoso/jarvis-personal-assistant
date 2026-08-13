"""Os objetos de domínio da execução: pedido, ação pendente, desfecho.

`PHASE-5.md §28` pede que "quero fazer X" e "X foi executado" nunca se misturem.
Aqui isso é a diferença entre `ActionRequest` (intenção), `PendingAction`
(intenção registrada, com estado) e `ExecutionOutcome` (o que de fato aconteceu).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

from jarvis.events.event import JsonValue
from jarvis.execution.errors import InvalidActionRequestError
from jarvis.policy.verdict import PolicyVerdict
from jarvis.tools.tool import ToolId

MAX_SUMMARY_LENGTH = 500


class Actor(StrEnum):
    """Quem pediu a ação.

    Não é decorativo: `EVENT` é o que faz uma Skill `conditional` exigir
    confirmação. Uma ação que ninguém pediu merece mais cautela que uma que o
    usuário acabou de digitar.
    """

    USER = "user"
    EVENT = "event"
    SYSTEM = "system"


class ExecutionStatus(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    REJECTED = "rejected"
    EXPIRED = "expired"
    DUPLICATE = "duplicate"

    @property
    def is_terminal(self) -> bool:
        return self not in (ExecutionStatus.AWAITING_CONFIRMATION, ExecutionStatus.RUNNING)

    @property
    def blocks_reexecution(self) -> bool:
        """Se reapresentar a mesma execução deve virar no-op.

        `completed`, `failed` e `running` bloqueiam — nos três casos a Skill
        chegou a ser chamada, e nem timeout nem processo morto no meio provam que
        o efeito não aconteceu do outro lado. `running` que ficou preso é
        visível em `jarvis action show`, e bloquear é o default seguro.

        `denied`, `rejected` e `expired` **não** bloqueiam: a política pode ter
        mudado, e reapresentar é justamente como se descobre isso.
        """
        return self in (
            ExecutionStatus.RUNNING,
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
        )


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise InvalidActionRequestError(f"{field_name} precisa ser timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionRequest:
    """A intenção de executar uma Skill. Ainda não é uma execução."""

    skill: str
    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    correlation_id: str
    actor: Actor = Actor.USER
    decision_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.skill.strip():
            raise InvalidActionRequestError("skill não pode ser vazia")
        if not self.correlation_id.strip():
            raise InvalidActionRequestError("correlation_id não pode ser vazio")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingAction:
    """Uma execução registrada, com seu estado atual.

    É a única estrutura do sistema que guarda os **parâmetros** de uma ação, e
    isso é deliberado: para executar depois de uma confirmação é preciso tê-los.
    Ela vive num store operacional, apagável, e não no Event Store — enterrar
    caminho de arquivo ou corpo de mensagem num log imutável e perpétuo seria um
    custo de privacidade que não precisamos pagar
    ([ADR-0014](../../../docs/adr/0014-confirmation-state-and-event-answers.md)).
    """

    execution_id: str
    skill: str
    parameters: Mapping[str, JsonValue]
    parameters_fingerprint: str
    actor: Actor
    correlation_id: str
    status: ExecutionStatus
    requested_at: datetime
    updated_at: datetime
    decision_id: str | None = None
    causation_id: str | None = None
    reason: str = ""
    expires_at: datetime | None = None
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(self, "parameters", MappingProxyType(dict(self.parameters)))
        overwrite(
            self, "requested_at", _require_aware(self.requested_at, field_name="requested_at")
        )
        overwrite(self, "updated_at", _require_aware(self.updated_at, field_name="updated_at"))
        if self.expires_at is not None:
            overwrite(self, "expires_at", _require_aware(self.expires_at, field_name="expires_at"))
        if self.confirmed_at is not None:
            overwrite(
                self, "confirmed_at", _require_aware(self.confirmed_at, field_name="confirmed_at")
            )

    def is_expired_at(self, moment: datetime) -> bool:
        return self.expires_at is not None and moment >= self.expires_at

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionOutcome:
    """O que aconteceu — o que o CLI imprime e o que o agente relata.

    `summary` é seguro para o usuário; `data` é o resultado estruturado e não vai
    para log nem evento.
    """

    execution_id: str
    status: ExecutionStatus
    skill: str
    correlation_id: str
    reason: str = ""
    detail: str = ""
    summary: str = ""
    data: Mapping[str, JsonValue] = field(default_factory=dict)
    tools_used: tuple[ToolId, ...] = ()
    duration_ms: float | None = None
    verdict: PolicyVerdict | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        if len(self.summary) > MAX_SUMMARY_LENGTH:
            object.__setattr__(self, "summary", f"{self.summary[:MAX_SUMMARY_LENGTH]}…")

    @property
    def executed(self) -> bool:
        return self.status is ExecutionStatus.COMPLETED
