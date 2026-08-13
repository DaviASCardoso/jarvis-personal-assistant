"""As regras determinísticas de autorização.

Cada regra é uma função pura de `(PolicyRequest, PolicyRuleSet)` para
`RuleOutcome | None`, com um `rule_id` estável que aparece na auditoria. Isso é o que torna possível
responder "por que essa ação foi negada?" com um identificador, e não com uma
paráfrase que muda quando alguém reescreve uma mensagem.

Nenhuma regra chama LLM, lê banco, consulta rede ou olha relógio além do
`requested_at` que veio no pedido. É essa ausência de I/O que faz do Policy
Engine uma autoridade *determinística*
([ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md)).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.policy.verdict import PolicyDecision, PolicyRequest
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, RiskLevel

EVENT_ACTOR: Final = "event"

DEFAULT_CONFIRM_EFFECTS: Final[frozenset[Effect]] = frozenset(
    {
        Effect.DESTRUCTIVE,
        Effect.PHYSICAL,
        Effect.EXTERNAL_COMMUNICATION,
        Effect.SPEND,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyRuleSet:
    """A política configurada. Dado imutável, montado pelo composition root.

    Defaults restritivos de propósito: `granted_capabilities` vazio nega tudo. Um
    default permissivo transformaria "esqueci de configurar" em "tudo liberado",
    que é a forma mais barata de perder a fase inteira.
    """

    granted_capabilities: frozenset[str] = frozenset()
    denied_skills: frozenset[str] = frozenset()
    denied_effects: frozenset[Effect] = frozenset()
    confirm_effects: frozenset[Effect] = DEFAULT_CONFIRM_EFFECTS
    confirm_risk_at_or_above: RiskLevel = RiskLevel.HIGH
    deny_risk_at_or_above: RiskLevel = RiskLevel.CRITICAL
    version: int = 1

    def describe(self) -> str:
        """Resumo legível para `jarvis info` — política efetiva não deve ser adivinhada."""
        return (
            f"v{self.version} "
            f"granted={','.join(sorted(self.granted_capabilities)) or '(nenhuma)'} "
            f"denied_skills={','.join(sorted(self.denied_skills)) or '(nenhuma)'} "
            f"denied_effects={','.join(sorted(self.denied_effects)) or '(nenhum)'} "
            f"confirm_effects={','.join(sorted(self.confirm_effects)) or '(nenhum)'} "
            f"confirm_risk>={self.confirm_risk_at_or_above.value} "
            f"deny_risk>={self.deny_risk_at_or_above.value}"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleOutcome:
    rule_id: str
    decision: PolicyDecision
    reason: str
    detail: str


type Rule = Callable[[PolicyRequest, PolicyRuleSet], RuleOutcome | None]


def _skill_not_registered(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    if request.skill_known:
        return None
    return RuleOutcome(
        rule_id="skill_not_registered",
        decision=PolicyDecision.DENY,
        reason="skill_not_registered",
        detail=f"nenhuma skill registrada com o nome {request.skill!r}",
    )


def _required_tool_unavailable(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    if not request.missing_tools:
        return None
    return RuleOutcome(
        rule_id="required_tool_unavailable",
        decision=PolicyDecision.DENY,
        reason="required_tool_unavailable",
        detail=f"ferramentas indisponíveis: {', '.join(sorted(request.missing_tools))}",
    )


def _skill_denylisted(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    if request.skill not in rules.denied_skills:
        return None
    return RuleOutcome(
        rule_id="skill_denylisted",
        decision=PolicyDecision.DENY,
        reason="skill_denylisted",
        detail="a skill está na denylist estática",
    )


def _effect_denylisted(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    blocked = request.effects & rules.denied_effects
    if not blocked:
        return None
    return RuleOutcome(
        rule_id="effect_denylisted",
        decision=PolicyDecision.DENY,
        reason="effect_denylisted",
        detail=f"efeitos na denylist: {', '.join(sorted(blocked))}",
    )


def _risk_above_ceiling(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    if not request.risk.at_least(rules.deny_risk_at_or_above):
        return None
    return RuleOutcome(
        rule_id="risk_above_ceiling",
        decision=PolicyDecision.DENY,
        reason="risk_above_ceiling",
        detail=f"risco {request.risk.value} >= teto {rules.deny_risk_at_or_above.value}",
    )


def _capability_not_granted(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    missing = request.capabilities - rules.granted_capabilities
    if not missing:
        return None
    return RuleOutcome(
        rule_id="capability_not_granted",
        decision=PolicyDecision.DENY,
        reason="capability_not_granted",
        detail=f"capacidades não concedidas: {', '.join(sorted(missing))}",
    )


def _risk_requires_confirmation(request: PolicyRequest, rules: PolicyRuleSet) -> RuleOutcome | None:
    if not request.risk.at_least(rules.confirm_risk_at_or_above):
        return None
    return RuleOutcome(
        rule_id="risk_requires_confirmation",
        decision=PolicyDecision.REQUIRE_CONFIRMATION,
        reason="risk_requires_confirmation",
        detail=f"risco {request.risk.value} >= {rules.confirm_risk_at_or_above.value}",
    )


def _effect_requires_confirmation(
    request: PolicyRequest, rules: PolicyRuleSet
) -> RuleOutcome | None:
    flagged = request.effects & rules.confirm_effects
    if not flagged:
        return None
    return RuleOutcome(
        rule_id="effect_requires_confirmation",
        decision=PolicyDecision.REQUIRE_CONFIRMATION,
        reason="effect_requires_confirmation",
        detail=f"efeitos que exigem confirmação: {', '.join(sorted(flagged))}",
    )


def _skill_requires_confirmation(
    request: PolicyRequest, rules: PolicyRuleSet
) -> RuleOutcome | None:
    if request.confirmation_requirement is not ConfirmationRequirement.ALWAYS:
        return None
    return RuleOutcome(
        rule_id="skill_requires_confirmation",
        decision=PolicyDecision.REQUIRE_CONFIRMATION,
        reason="skill_requires_confirmation",
        detail="a skill declara confirmação sempre",
    )


def _proactive_action_requires_confirmation(
    request: PolicyRequest, rules: PolicyRuleSet
) -> RuleOutcome | None:
    """Ação proativa é mais cara de errar que ação pedida.

    Uma Skill `conditional` executa direto quando o usuário pediu, e pede
    confirmação quando quem disparou foi um evento: ninguém está olhando, e o
    gatilho pode ter vindo de conteúdo não confiável.
    """
    if request.confirmation_requirement is not ConfirmationRequirement.CONDITIONAL:
        return None
    if request.actor != EVENT_ACTOR:
        return None
    return RuleOutcome(
        rule_id="proactive_action_requires_confirmation",
        decision=PolicyDecision.REQUIRE_CONFIRMATION,
        reason="proactive_action_requires_confirmation",
        detail="ação disparada por evento, não pedida pelo usuário",
    )


ALL_RULES: Final[tuple[Rule, ...]] = (
    _skill_not_registered,
    _required_tool_unavailable,
    _skill_denylisted,
    _effect_denylisted,
    _risk_above_ceiling,
    _capability_not_granted,
    _risk_requires_confirmation,
    _effect_requires_confirmation,
    _skill_requires_confirmation,
    _proactive_action_requires_confirmation,
)


def evaluate_rules(
    request: PolicyRequest, rules: PolicyRuleSet, *, catalog: Sequence[Rule] = ALL_RULES
) -> tuple[RuleOutcome, ...]:
    """Aplica **todas** as regras e devolve as que casaram, na ordem do catálogo."""
    return tuple(outcome for rule in catalog if (outcome := rule(request, rules)) is not None)
