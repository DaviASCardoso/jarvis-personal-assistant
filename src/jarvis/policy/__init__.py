"""Policy Engine: a fronteira determinística entre "o modelo quis" e "o Jarvis fez".

API pública do componente. Este pacote **não importa** `jarvis.skills`,
`jarvis.tools` nem `jarvis.agent` — uma autoridade de autorização que dependesse
de quem ela autoriza não seria independente. Tudo que ela precisa saber chega no
`PolicyRequest`, montado pelo executor.

`vocabulary.py` é a única porta de entrada permitida a `jarvis.skills`: Skills
declaram risco e efeito usando esse vocabulário, e nada além dele — ver §10 de
[`architecture-contracts.md`](../../../docs/architecture-contracts.md).

Documentação: [`docs/security.md`](../../../docs/security.md).
"""

from jarvis.policy.engine import DEFAULT_APPROVAL_TTL_SECONDS, PolicyEngine
from jarvis.policy.errors import (
    ApprovalAlreadyUsedError,
    ApprovalError,
    ApprovalExpiredError,
    ApprovalMismatchError,
    PolicyError,
    UnknownApprovalError,
)
from jarvis.policy.rules import DEFAULT_CONFIRM_EFFECTS, PolicyRuleSet, RuleOutcome, evaluate_rules
from jarvis.policy.verdict import (
    Confirmation,
    PolicyApproval,
    PolicyDecision,
    PolicyRequest,
    PolicyVerdict,
)
from jarvis.policy.vocabulary import (
    ConfirmationRequirement,
    Effect,
    Idempotency,
    InvalidPolicyVocabularyError,
    RiskLevel,
    parse_capabilities,
    parse_effects,
    parse_names,
    parse_risk,
    require_capability,
)

__all__ = [
    "DEFAULT_APPROVAL_TTL_SECONDS",
    "DEFAULT_CONFIRM_EFFECTS",
    "ApprovalAlreadyUsedError",
    "ApprovalError",
    "ApprovalExpiredError",
    "ApprovalMismatchError",
    "Confirmation",
    "ConfirmationRequirement",
    "Effect",
    "Idempotency",
    "InvalidPolicyVocabularyError",
    "PolicyApproval",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyError",
    "PolicyRequest",
    "PolicyRuleSet",
    "PolicyVerdict",
    "RiskLevel",
    "RuleOutcome",
    "UnknownApprovalError",
    "evaluate_rules",
    "parse_capabilities",
    "parse_effects",
    "parse_names",
    "parse_risk",
    "require_capability",
]
