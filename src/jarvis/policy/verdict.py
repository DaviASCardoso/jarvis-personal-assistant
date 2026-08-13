"""Os objetos de domínio da autorização: pedido, veredito, aprovação, confirmação.

Nenhum deles carrega os parâmetros da ação — só o `parameters_fingerprint`. É
essa escolha que permite logar e auditar cada veredito sem que caminho de
arquivo, corpo de mensagem ou destinatário circulem por camadas que não têm nada
que vê-los, e ao mesmo tempo provar que a execução autorizada é exatamente a que
foi pedida.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from jarvis.policy.errors import PolicyError
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, RiskLevel
from jarvis.tools.tool import ToolId

MAX_DETAIL_LENGTH: Final = 300


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"

    @property
    def strength(self) -> int:
        """Ordem de força usada para compor regras.

        Todas as regras são avaliadas e a **mais forte** vence. Não é
        "primeira que casa": assim nenhuma regra consegue rebaixar a decisão de
        outra, e acrescentar uma regra nova nunca afrouxa a política por
        acidente de ordenação.
        """
        return _STRENGTH[self]


_STRENGTH: Final[dict[PolicyDecision, int]] = {
    PolicyDecision.ALLOW: 0,
    PolicyDecision.REQUIRE_CONFIRMATION: 1,
    PolicyDecision.DENY: 2,
}


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise PolicyError(f"{field_name} precisa ser timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class Confirmation:
    """A resposta do usuário a um pedido de confirmação.

    Ligada a `execution_id` **e** ao fingerprint dos parâmetros: confirmar uma
    ação nunca autoriza outra, e editar os parâmetros entre o pedido e a resposta
    invalida a confirmação.
    """

    execution_id: str
    parameters_fingerprint: str
    granted: bool
    responded_at: datetime
    expires_at: datetime
    reason: str = ""

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(
            self, "responded_at", _require_aware(self.responded_at, field_name="responded_at")
        )
        overwrite(self, "expires_at", _require_aware(self.expires_at, field_name="expires_at"))

    def satisfies(self, request: "PolicyRequest", *, moment: datetime) -> bool:
        return (
            self.granted
            and self.execution_id == request.execution_id
            and self.parameters_fingerprint == request.parameters_fingerprint
            and moment < self.expires_at
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRequest:
    """Tudo que o Policy Engine precisa saber — e nada além.

    `skill_known` e `missing_tools` chegam prontos do executor em vez de o engine
    consultar registries: `architecture-contracts.md §3.5` proíbe o Policy Engine
    de conhecer Skills e Tools. A consequência boa é que "skill inexistente" vira
    um veredito auditado como qualquer outro, em vez de um caminho de erro
    paralelo que escapa da trilha.
    """

    execution_id: str
    correlation_id: str
    skill: str
    parameters_fingerprint: str
    requested_at: datetime
    actor: str = "user"
    risk: RiskLevel = RiskLevel.LOW
    effects: frozenset[Effect] = frozenset()
    confirmation_requirement: ConfirmationRequirement = ConfirmationRequirement.CONDITIONAL
    capabilities: frozenset[str] = frozenset()
    decision_id: str | None = None
    skill_known: bool = True
    missing_tools: tuple[ToolId, ...] = ()
    confirmation: Confirmation | None = None

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise PolicyError("execution_id não pode ser vazio")
        if not self.correlation_id.strip():
            raise PolicyError("correlation_id não pode ser vazio")
        if not self.parameters_fingerprint.strip():
            raise PolicyError("parameters_fingerprint não pode ser vazio")
        object.__setattr__(
            self, "requested_at", _require_aware(self.requested_at, field_name="requested_at")
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyApproval:
    """Autorização para **uma** execução específica.

    Não é confirmação do usuário, não é decisão do LLM, não é metadado de Skill e
    não é permissão permanente (`PHASE-5.md §9`). Construir esta dataclass fora do
    `PolicyEngine` produz um objeto sem valor: quem valida é o ledger de quem
    emitiu, e um objeto forjado não está lá
    ([ADR-0013](../../../docs/adr/0013-single-use-policy-approval.md)).
    """

    approval_id: str
    execution_id: str
    skill: str
    parameters_fingerprint: str
    policy_version: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(self, "issued_at", _require_aware(self.issued_at, field_name="issued_at"))
        overwrite(self, "expires_at", _require_aware(self.expires_at, field_name="expires_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyVerdict:
    """O que o Policy Engine decidiu, e sob qual regra.

    `reason` é um slug estável (`capability_not_granted`), pensado para teste e
    auditoria; `detail` é a frase humana. Nenhum dos dois contém parâmetros.
    """

    decision: PolicyDecision
    reason: str
    rule_id: str
    policy_version: int
    evaluated_at: datetime
    execution_id: str
    skill: str
    detail: str = ""
    approval: PolicyApproval | None = None
    considered: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        overwrite = object.__setattr__
        overwrite(
            self, "evaluated_at", _require_aware(self.evaluated_at, field_name="evaluated_at")
        )
        if len(self.detail) > MAX_DETAIL_LENGTH:
            overwrite(self, "detail", f"{self.detail[:MAX_DETAIL_LENGTH]}…")
        if self.decision is not PolicyDecision.ALLOW and self.approval is not None:
            raise PolicyError("só um veredito allow pode carregar aprovação")

    @property
    def allowed(self) -> bool:
        return self.decision is PolicyDecision.ALLOW
