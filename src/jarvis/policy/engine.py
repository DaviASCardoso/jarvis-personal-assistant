"""`PolicyEngine`: a única autoridade sobre `allow` / `deny` / `require_confirmation`.

Determinístico por construção: sem chamada de LLM, sem I/O, sem consulta a
registry. Tudo que ele sabe chega no `PolicyRequest`
([ADR-0003](../../../docs/adr/0003-policy-engine-safety-authority.md)).

Duas responsabilidades, e a segunda é o que dá dentes à primeira:

1. **avaliar** — compor as regras de `rules.py` pela força maior e produzir um
   `PolicyVerdict`;
2. **emitir e consumir aprovações** — `evaluate()` é o único lugar do sistema que
   cria uma `PolicyApproval` *válida*, porque registrá-la no ledger interno faz
   parte da criação. Uma `PolicyApproval` construída em qualquer outro lugar tem
   todos os campos e nenhum valor: `consume()` não a encontra e recusa
   ([ADR-0013](../../../docs/adr/0013-single-use-policy-approval.md)).

O ledger é **em memória, por processo**, e isso é a decisão, não uma limitação:
uma confirmação respondida noutra invocação do CLI força reavaliação completa da
política. Restaurar autorização de um processo morto seria guardar poder; refazer
a avaliação é mais barato e mais seguro.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from jarvis.policy.errors import (
    ApprovalAlreadyUsedError,
    ApprovalExpiredError,
    ApprovalMismatchError,
    UnknownApprovalError,
)
from jarvis.policy.rules import PolicyRuleSet, evaluate_rules
from jarvis.policy.verdict import PolicyApproval, PolicyDecision, PolicyRequest, PolicyVerdict

logger = logging.getLogger(__name__)

DEFAULT_APPROVAL_TTL_SECONDS = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_approval_id() -> str:
    return str(uuid.uuid4())


@dataclass(slots=True)
class _Issued:
    approval: PolicyApproval
    consumed_at: datetime | None = field(default=None)


class PolicyEngine:
    """Serviço do Core. Não é port: uma autoridade substituível não seria autoridade."""

    def __init__(
        self,
        *,
        rules: PolicyRuleSet | None = None,
        approval_ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        new_id: Callable[[], str] = _new_approval_id,
    ) -> None:
        self._rules = rules if rules is not None else PolicyRuleSet()
        self._ttl = timedelta(seconds=approval_ttl_seconds)
        self._clock = clock
        self._new_id = new_id
        self._ledger: dict[str, _Issued] = {}

    @property
    def rules(self) -> PolicyRuleSet:
        return self._rules

    @property
    def version(self) -> int:
        return self._rules.version

    def evaluate(self, request: PolicyRequest) -> PolicyVerdict:
        """Decide, e — só quando permite — emite a aprovação correspondente."""
        now = self._clock()
        outcomes = evaluate_rules(request, self._rules)
        considered = tuple(outcome.rule_id for outcome in outcomes)

        if not outcomes:
            return self._allow(
                request,
                now=now,
                rule_id="default_allow",
                reason="default_allow",
                detail="nenhuma regra restringiu esta execução",
                considered=considered,
            )

        strongest = max(outcomes, key=lambda outcome: outcome.decision.strength)

        if strongest.decision is PolicyDecision.REQUIRE_CONFIRMATION:
            confirmation = request.confirmation
            if confirmation is not None and confirmation.satisfies(request, moment=now):
                # Rebaixamento só a partir de `require_confirmation`, nunca sobre
                # um `deny`: como `deny` tem força maior, ele jamais chega aqui.
                return self._allow(
                    request,
                    now=now,
                    rule_id="confirmation_satisfied",
                    reason="confirmation_satisfied",
                    detail=f"confirmação do usuário atende {strongest.rule_id}",
                    considered=considered,
                )

        verdict = PolicyVerdict(
            decision=strongest.decision,
            reason=strongest.reason,
            rule_id=strongest.rule_id,
            policy_version=self._rules.version,
            evaluated_at=now,
            execution_id=request.execution_id,
            skill=request.skill,
            detail=strongest.detail,
            considered=considered,
        )
        self._log(verdict)
        return verdict

    def _allow(
        self,
        request: PolicyRequest,
        *,
        now: datetime,
        rule_id: str,
        reason: str,
        detail: str,
        considered: tuple[str, ...],
    ) -> PolicyVerdict:
        approval = PolicyApproval(
            approval_id=self._new_id(),
            execution_id=request.execution_id,
            skill=request.skill,
            parameters_fingerprint=request.parameters_fingerprint,
            policy_version=self._rules.version,
            issued_at=now,
            expires_at=now + self._ttl,
        )
        self._ledger[approval.approval_id] = _Issued(approval=approval)
        verdict = PolicyVerdict(
            decision=PolicyDecision.ALLOW,
            reason=reason,
            rule_id=rule_id,
            policy_version=self._rules.version,
            evaluated_at=now,
            execution_id=request.execution_id,
            skill=request.skill,
            detail=detail,
            approval=approval,
            considered=considered,
        )
        self._log(verdict)
        return verdict

    def consume(self, approval: PolicyApproval, *, moment: datetime | None = None) -> None:
        """Gasta a aprovação. Chamada uma vez, imediatamente antes de executar.

        A ordem das checagens é a ordem em que elas ficam interessantes de
        diagnosticar: existe? já foi usada? venceu? é para isto mesmo?
        """
        now = moment if moment is not None else self._clock()
        issued = self._ledger.get(approval.approval_id)
        if issued is None:
            raise UnknownApprovalError("aprovação desconhecida por este Policy Engine")
        if issued.consumed_at is not None:
            raise ApprovalAlreadyUsedError("aprovação já foi utilizada")
        if now >= issued.approval.expires_at:
            raise ApprovalExpiredError("aprovação expirada")
        if (
            issued.approval.execution_id != approval.execution_id
            or issued.approval.skill != approval.skill
            or issued.approval.parameters_fingerprint != approval.parameters_fingerprint
        ):
            raise ApprovalMismatchError("aprovação não corresponde a esta execução")

        issued.consumed_at = now
        logger.info(
            "policy.approval_consumed",
            extra={
                "execution_id": issued.approval.execution_id,
                "skill": issued.approval.skill,
                "approval_id": issued.approval.approval_id,
            },
        )

    def _log(self, verdict: PolicyVerdict) -> None:
        logger.info(
            "policy.evaluated",
            extra={
                "execution_id": verdict.execution_id,
                "skill": verdict.skill,
                "decision": verdict.decision.value,
                "reason": verdict.reason,
                "rule_id": verdict.rule_id,
                "policy_version": verdict.policy_version,
            },
        )
