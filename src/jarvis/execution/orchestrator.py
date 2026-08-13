"""`ActionExecutor`: o único caminho entre uma `Decision` e uma Skill executada.

Este é o componente que fecha o triângulo Policy + Skills + Tools, e é o único
autorizado a conhecer os três ao mesmo tempo
([ADR-0016](../../../docs/adr/0016-action-execution-orchestrator.md)). A razão de
ele existir como pacote próprio é negativa: se o Agent Runtime orquestrasse,
quebraria o ADR-0003; se o Skill Registry orquestrasse, `jarvis.skills` passaria
a conhecer `jarvis.policy`, contra o contrato §3.6. Sobrou um lugar, e é aqui.

A sequência, e cada seta é uma barreira testada:

```text
lookup → validação de schema → política → aprovação consumida
       → ToolAccess recortado → handler → tools → auditoria → outcome
```

Duas escolhas que valem explicação:

- **negar não levanta exceção.** `deny`, `require_confirmation`, `expired` e
  `duplicate` voltam como `ExecutionOutcome`, porque o agente precisa relatá-los
  e a auditoria precisa registrá-los (contracts §13);
- **a auditoria do veredito é fail-closed.** Se `policy.evaluated` não consegue
  ser gravado, a execução aborta. Sem trilha, sem ação. Os marcos posteriores são
  best-effort: não existe compensação honesta para "o arquivo já foi escrito".
"""

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from jarvis.audit import AuditEntry, AuditKind, AuditLog
from jarvis.errors import InfrastructureError
from jarvis.events.event import JsonValue
from jarvis.execution.identity import deterministic_execution_id, new_execution_id
from jarvis.execution.model import (
    ActionRequest,
    ExecutionOutcome,
    ExecutionStatus,
    PendingAction,
)
from jarvis.execution.ports import ActionRepository
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.errors import PolicyError
from jarvis.policy.verdict import Confirmation, PolicyDecision, PolicyRequest, PolicyVerdict
from jarvis.policy.vocabulary import ConfirmationRequirement, Idempotency, RiskLevel
from jarvis.skills.errors import SkillError
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation
from jarvis.tools.access import ToolAccess
from jarvis.tools.errors import ToolError, ToolInvalidInputError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from jarvis.tools.schema import parameters_fingerprint

logger = logging.getLogger(__name__)

DEFAULT_CONFIRMATION_TTL_SECONDS = 900.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ActionExecutor:
    """Serviço de aplicação do Core. Não é port: implementação única."""

    def __init__(
        self,
        *,
        skills: SkillRegistry,
        tools: ToolRegistry,
        router: ToolRouter,
        policy: PolicyEngine,
        repository: ActionRepository,
        audit: AuditLog,
        confirmation_ttl_seconds: float = DEFAULT_CONFIRMATION_TTL_SECONDS,
        tool_timeout_seconds: float | None = None,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._skills = skills
        self._tools = tools
        self._router = router
        self._policy = policy
        self._repository = repository
        self._audit = audit
        self._confirmation_ttl = timedelta(seconds=confirmation_ttl_seconds)
        self._tool_timeout = tool_timeout_seconds
        self._clock = clock
        self._monotonic = monotonic

    # ------------------------------------------------------------------ API

    def submit(self, request: ActionRequest) -> ExecutionOutcome:
        now = self._clock()
        skill = self._skills.find(request.skill)
        descriptor = skill.descriptor if skill is not None else None

        if descriptor is not None:
            try:
                parameters = descriptor.parameters.validate(request.parameters)
            except ToolInvalidInputError as error:
                return self._invalid_parameters(request, error, now=now)
        else:
            parameters = request.parameters

        fingerprint = parameters_fingerprint(parameters)
        execution_id = self._identify(request, fingerprint)

        existing = self._repository.get(execution_id)
        if existing is not None and existing.status.blocks_reexecution:
            logger.info(
                "action.duplicate",
                extra={
                    "execution_id": execution_id,
                    "skill": request.skill,
                    "previous_status": existing.status.value,
                },
            )
            return ExecutionOutcome(
                execution_id=execution_id,
                status=ExecutionStatus.DUPLICATE,
                skill=request.skill,
                correlation_id=request.correlation_id,
                reason="already_executed",
                detail=f"execução já registrada como {existing.status.value}",
                summary="Esta ação já foi executada antes; nada foi repetido.",
            )

        pending = PendingAction(
            execution_id=execution_id,
            skill=request.skill,
            parameters=parameters,
            parameters_fingerprint=fingerprint,
            actor=request.actor,
            correlation_id=request.correlation_id,
            status=ExecutionStatus.RUNNING,
            requested_at=now,
            updated_at=now,
            decision_id=request.decision_id,
            causation_id=request.causation_id,
        )
        self._record(
            AuditKind.ACTION_REQUESTED,
            pending,
            detail={
                "skill": request.skill,
                "actor": request.actor.value,
                "decision_id": request.decision_id,
                "parameters_fingerprint": fingerprint,
            },
        )

        verdict = self._evaluate(pending, descriptor, confirmation=None, now=now)
        return self._apply(pending, verdict, skill=skill, now=now, existing=existing is not None)

    def resume(self, execution_id: str) -> ExecutionOutcome:
        """Retoma uma execução que estava esperando confirmação.

        Reavalia a política do zero — não confia no veredito anterior. Uma
        denylist acrescentada entre o pedido e a confirmação ainda nega, e a
        aprovação é sempre nova (o ledger não sobrevive ao processo).
        """
        now = self._clock()
        pending = self._repository.get(execution_id)
        if pending is None:
            return ExecutionOutcome(
                execution_id=execution_id,
                status=ExecutionStatus.FAILED,
                skill="",
                correlation_id=execution_id,
                reason="unknown_execution",
                detail="nenhuma execução registrada com esse identificador",
            )

        if pending.status is not ExecutionStatus.AWAITING_CONFIRMATION:
            return self._already_settled(pending)

        if pending.is_expired_at(now):
            settled = self._repository.mark(
                execution_id, status=ExecutionStatus.EXPIRED, moment=now, reason="expired"
            )
            self._record(
                AuditKind.ACTION_FAILED,
                settled,
                detail={"skill": settled.skill, "status": ExecutionStatus.EXPIRED.value},
                discriminator=ExecutionStatus.EXPIRED.value,
            )
            return self._outcome(
                settled,
                status=ExecutionStatus.EXPIRED,
                reason="confirmation_expired",
                detail="a confirmação venceu antes de ser respondida",
                summary="A confirmação expirou; nada foi executado.",
            )

        skill = self._skills.find(pending.skill)
        descriptor = skill.descriptor if skill is not None else None
        confirmation = (
            Confirmation(
                execution_id=pending.execution_id,
                parameters_fingerprint=pending.parameters_fingerprint,
                granted=True,
                responded_at=pending.confirmed_at,
                expires_at=pending.expires_at if pending.expires_at is not None else now,
            )
            if pending.confirmed_at is not None
            else None
        )

        verdict = self._evaluate(pending, descriptor, confirmation=confirmation, now=now)
        return self._apply(pending, verdict, skill=skill, now=now, existing=True)

    def pending(self, *, limit: int | None = None) -> Sequence[PendingAction]:
        return self._repository.list_by_status(ExecutionStatus.AWAITING_CONFIRMATION, limit=limit)

    def get(self, execution_id: str) -> PendingAction | None:
        return self._repository.get(execution_id)

    def expire(self, *, moment: datetime | None = None) -> int:
        """Marca as pendências vencidas. Devolve quantas mudaram."""
        now = moment if moment is not None else self._clock()
        expired = self._repository.expire_pending(moment=now)
        for action in expired:
            self._record(
                AuditKind.ACTION_FAILED,
                action,
                detail={"skill": action.skill, "status": ExecutionStatus.EXPIRED.value},
                discriminator=ExecutionStatus.EXPIRED.value,
            )
        return len(expired)

    # ------------------------------------------------------- passos internos

    def _identify(self, request: ActionRequest, fingerprint: str) -> str:
        if request.decision_id is None:
            # Ação pedida à mão duas vezes é intenção, não duplicata.
            return new_execution_id()
        return deterministic_execution_id(
            decision_id=request.decision_id,
            skill=request.skill,
            parameters_fingerprint=fingerprint,
        )

    def _evaluate(
        self,
        pending: PendingAction,
        descriptor: SkillDescriptor | None,
        *,
        confirmation: Confirmation | None,
        now: datetime,
    ) -> PolicyVerdict:
        """Monta o `PolicyRequest` e grava o veredito — este é o passo fail-closed.

        O Policy Engine não consulta registries (contracts §3.5 proíbe conhecer
        Skills e Tools); é aqui que "skill inexistente" e "ferramenta ausente"
        viram campos do pedido, para que virem vereditos auditados como qualquer
        outro em vez de um caminho de erro paralelo.
        """
        request = PolicyRequest(
            execution_id=pending.execution_id,
            correlation_id=pending.correlation_id,
            skill=pending.skill,
            parameters_fingerprint=pending.parameters_fingerprint,
            requested_at=now,
            actor=pending.actor.value,
            # Sem descritor não há autodeclaração para usar; os valores abaixo
            # nem chegam a pesar, porque `skill_not_registered` já nega.
            risk=descriptor.risk if descriptor is not None else RiskLevel.LOW,
            effects=descriptor.effects if descriptor is not None else frozenset(),
            confirmation_requirement=(
                descriptor.confirmation_requirement
                if descriptor is not None
                else ConfirmationRequirement.ALWAYS
            ),
            capabilities=descriptor.capabilities if descriptor is not None else frozenset(),
            decision_id=pending.decision_id,
            skill_known=descriptor is not None,
            missing_tools=(
                self._tools.missing(descriptor.required_tools) if descriptor is not None else ()
            ),
            confirmation=confirmation,
        )
        verdict = self._policy.evaluate(request)
        self._audit.record(
            AuditEntry(
                kind=AuditKind.POLICY_EVALUATED,
                execution_id=pending.execution_id,
                correlation_id=pending.correlation_id,
                occurred_at=now,
                causation_id=pending.causation_id,
                # Uma execução confirmada é avaliada duas vezes, e o segundo
                # veredito é o que autoriza. Sem discriminar por decisão, ele
                # colidiria com o primeiro e sumiria da trilha.
                discriminator=verdict.decision.value,
                detail={
                    "skill": pending.skill,
                    "decision": verdict.decision.value,
                    "reason": verdict.reason,
                    "rule_id": verdict.rule_id,
                    "policy_version": verdict.policy_version,
                    "risk": request.risk.value,
                    "effects": sorted(request.effects),
                },
            )
        )
        return verdict

    def _apply(
        self,
        pending: PendingAction,
        verdict: PolicyVerdict,
        *,
        skill: Skill | None,
        now: datetime,
        existing: bool,
    ) -> ExecutionOutcome:
        if verdict.decision is PolicyDecision.DENY:
            return self._deny(pending, verdict, now=now, existing=existing)
        if verdict.decision is PolicyDecision.REQUIRE_CONFIRMATION:
            return self._ask_confirmation(pending, verdict, now=now, existing=existing)
        if skill is None:  # pragma: no cover - `skill_not_registered` já negou acima
            return self._deny(pending, verdict, now=now, existing=existing)
        return self._run(pending, verdict, skill=skill, now=now, existing=existing)

    def _deny(
        self, pending: PendingAction, verdict: PolicyVerdict, *, now: datetime, existing: bool
    ) -> ExecutionOutcome:
        settled = self._settle(
            pending, ExecutionStatus.DENIED, now=now, reason=verdict.reason, existing=existing
        )
        self._record(
            AuditKind.ACTION_FAILED,
            settled,
            detail={
                "skill": settled.skill,
                "status": ExecutionStatus.DENIED.value,
                "reason": verdict.reason,
                "rule_id": verdict.rule_id,
            },
            discriminator=f"{ExecutionStatus.DENIED.value}:{verdict.reason}",
        )
        return self._outcome(
            settled,
            status=ExecutionStatus.DENIED,
            reason=verdict.reason,
            detail=verdict.detail,
            summary=f"Ação bloqueada pela política ({verdict.reason}).",
            verdict=verdict,
        )

    def _ask_confirmation(
        self, pending: PendingAction, verdict: PolicyVerdict, *, now: datetime, existing: bool
    ) -> ExecutionOutcome:
        expires_at = pending.expires_at if existing else now + self._confirmation_ttl
        waiting = PendingAction(
            execution_id=pending.execution_id,
            skill=pending.skill,
            parameters=pending.parameters,
            parameters_fingerprint=pending.parameters_fingerprint,
            actor=pending.actor,
            correlation_id=pending.correlation_id,
            status=ExecutionStatus.AWAITING_CONFIRMATION,
            requested_at=pending.requested_at,
            updated_at=now,
            decision_id=pending.decision_id,
            causation_id=pending.causation_id,
            reason=verdict.reason,
            expires_at=expires_at if expires_at is not None else now + self._confirmation_ttl,
            confirmed_at=pending.confirmed_at,
        )
        if existing:
            # Reavaliação não estende o prazo: o relógio da confirmação começou a
            # correr no primeiro pedido, e renová-lo a cada consulta faria uma
            # pendência esquecida durar para sempre.
            waiting = self._repository.mark(
                waiting.execution_id,
                status=ExecutionStatus.AWAITING_CONFIRMATION,
                moment=now,
                reason=verdict.reason,
            )
        else:
            self._repository.put(waiting)

        self._record(
            AuditKind.CONFIRMATION_REQUESTED,
            waiting,
            detail={
                "skill": waiting.skill,
                "reason": verdict.reason,
                "rule_id": verdict.rule_id,
                "expires_at": waiting.expires_at.isoformat() if waiting.expires_at else None,
            },
        )
        return self._outcome(
            waiting,
            status=ExecutionStatus.AWAITING_CONFIRMATION,
            reason=verdict.reason,
            detail=verdict.detail,
            summary=(
                "Esta ação precisa da sua confirmação. "
                f"Use `jarvis action confirm {waiting.execution_id}`."
            ),
            verdict=verdict,
        )

    def _run(
        self,
        pending: PendingAction,
        verdict: PolicyVerdict,
        *,
        skill: Skill,
        now: datetime,
        existing: bool,
    ) -> ExecutionOutcome:
        approval = verdict.approval
        if approval is None:  # pragma: no cover - `PolicyVerdict` garante a invariante
            raise PolicyError("veredito allow sem aprovação")

        try:
            self._policy.consume(approval, moment=now)
        except PolicyError as error:
            settled = self._settle(
                pending,
                ExecutionStatus.DENIED,
                now=now,
                reason="approval_rejected",
                existing=existing,
            )
            logger.warning(
                "action.approval_rejected",
                extra={
                    "execution_id": pending.execution_id,
                    "skill": pending.skill,
                    "error_type": type(error).__name__,
                },
            )
            self._record(
                AuditKind.ACTION_FAILED,
                settled,
                detail={
                    "skill": settled.skill,
                    "status": ExecutionStatus.DENIED.value,
                    "reason": "approval_rejected",
                },
                discriminator=f"{ExecutionStatus.DENIED.value}:approval_rejected",
            )
            return self._outcome(
                settled,
                status=ExecutionStatus.DENIED,
                reason="approval_rejected",
                detail=str(error),
                summary="A autorização desta execução não pôde ser usada.",
                verdict=verdict,
            )

        running = self._settle(
            pending, ExecutionStatus.RUNNING, now=now, reason="", existing=existing
        )
        descriptor = skill.descriptor
        access = ToolAccess(
            router=self._router,
            execution_id=running.execution_id,
            correlation_id=running.correlation_id,
            allowed=descriptor.allowed_tools,
            idempotent=descriptor.idempotency is Idempotency.SAFE,
            timeout_seconds=self._tool_timeout,
        )
        started = self._monotonic()

        try:
            output = skill.handler.execute(
                SkillInvocation(
                    execution_id=running.execution_id,
                    correlation_id=running.correlation_id,
                    parameters=running.parameters,
                    tools=access,
                    now=now,
                )
            )
        except (SkillError, ToolError) as error:
            duration_ms = (self._monotonic() - started) * 1000
            settled = self._repository.mark(
                running.execution_id,
                status=ExecutionStatus.FAILED,
                moment=self._clock(),
                reason=type(error).__name__,
            )
            logger.warning(
                "action.failed",
                extra={
                    "execution_id": settled.execution_id,
                    "skill": settled.skill,
                    "error_type": type(error).__name__,
                    "duration_ms": round(duration_ms, 1),
                    "tools_used": list(access.used),
                },
            )
            self._record(
                AuditKind.ACTION_FAILED,
                settled,
                detail={
                    "skill": settled.skill,
                    "status": ExecutionStatus.FAILED.value,
                    "reason": type(error).__name__,
                    "tools_used": list(access.used),
                    "duration_ms": round(duration_ms, 1),
                },
                discriminator=f"{ExecutionStatus.FAILED.value}:{type(error).__name__}",
            )
            return self._outcome(
                settled,
                status=ExecutionStatus.FAILED,
                reason=type(error).__name__,
                detail=str(error),
                summary=f"A ação falhou: {error}",
                tools_used=access.used,
                duration_ms=duration_ms,
                verdict=verdict,
            )

        duration_ms = (self._monotonic() - started) * 1000
        settled = self._repository.mark(
            running.execution_id,
            status=ExecutionStatus.COMPLETED,
            moment=self._clock(),
            reason="",
        )
        logger.info(
            "action.completed",
            extra={
                "execution_id": settled.execution_id,
                "skill": settled.skill,
                "duration_ms": round(duration_ms, 1),
                "tools_used": list(access.used),
            },
        )
        self._record(
            AuditKind.ACTION_COMPLETED,
            settled,
            detail={
                "skill": settled.skill,
                "tools_used": list(access.used),
                "duration_ms": round(duration_ms, 1),
            },
        )
        return self._outcome(
            settled,
            status=ExecutionStatus.COMPLETED,
            reason="ok",
            detail="",
            summary=output.summary,
            data=output.data,
            tools_used=access.used,
            duration_ms=duration_ms,
            verdict=verdict,
        )

    # ------------------------------------------------------------ auxiliares

    def _settle(
        self,
        pending: PendingAction,
        status: ExecutionStatus,
        *,
        now: datetime,
        reason: str,
        existing: bool,
    ) -> PendingAction:
        if existing:
            return self._repository.mark(
                pending.execution_id, status=status, moment=now, reason=reason
            )
        stored = PendingAction(
            execution_id=pending.execution_id,
            skill=pending.skill,
            parameters=pending.parameters,
            parameters_fingerprint=pending.parameters_fingerprint,
            actor=pending.actor,
            correlation_id=pending.correlation_id,
            status=status,
            requested_at=pending.requested_at,
            updated_at=now,
            decision_id=pending.decision_id,
            causation_id=pending.causation_id,
            reason=reason,
            expires_at=pending.expires_at,
            confirmed_at=pending.confirmed_at,
        )
        self._repository.put(stored)
        return stored

    def _already_settled(self, pending: PendingAction) -> ExecutionOutcome:
        return self._outcome(
            pending,
            status=pending.status,
            reason=pending.reason or "already_settled",
            detail=f"a execução já está em {pending.status.value}",
            summary=f"Nada a retomar: a ação está em {pending.status.value}.",
        )

    def _invalid_parameters(
        self, request: ActionRequest, error: ToolInvalidInputError, *, now: datetime
    ) -> ExecutionOutcome:
        """Parâmetros fora do schema nem chegam à política.

        Não é negação — é pedido malformado. Não gasta veredito, não gera
        aprovação e não deixa registro de execução: nada existiu.
        """
        logger.info(
            "action.invalid_parameters",
            extra={"skill": request.skill, "correlation_id": request.correlation_id},
        )
        return ExecutionOutcome(
            execution_id=new_execution_id(),
            status=ExecutionStatus.FAILED,
            skill=request.skill,
            correlation_id=request.correlation_id,
            reason="invalid_parameters",
            detail=str(error),
            summary=f"Parâmetros inválidos para {request.skill}: {error}",
        )

    def _outcome(
        self,
        pending: PendingAction,
        *,
        status: ExecutionStatus,
        reason: str,
        detail: str,
        summary: str = "",
        data: Mapping[str, JsonValue] | None = None,
        tools_used: tuple[str, ...] = (),
        duration_ms: float | None = None,
        verdict: PolicyVerdict | None = None,
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            execution_id=pending.execution_id,
            status=status,
            skill=pending.skill,
            correlation_id=pending.correlation_id,
            reason=reason,
            detail=detail,
            summary=summary,
            data=data if data is not None else {},
            tools_used=tools_used,
            duration_ms=duration_ms,
            verdict=verdict,
            expires_at=pending.expires_at,
        )

    def _record(
        self,
        kind: AuditKind,
        pending: PendingAction,
        *,
        detail: Mapping[str, JsonValue],
        discriminator: str = "",
    ) -> None:
        """Marco best-effort: falhar aqui não desfaz o que já aconteceu.

        O fail-closed é só o `POLICY_EVALUATED`, gravado direto em `_evaluate`.
        """
        try:
            self._audit.record(
                AuditEntry(
                    kind=kind,
                    execution_id=pending.execution_id,
                    correlation_id=pending.correlation_id,
                    occurred_at=self._clock(),
                    causation_id=pending.causation_id,
                    discriminator=discriminator,
                    detail=detail,
                )
            )
        except InfrastructureError as error:
            logger.error(
                "action.audit_failed",
                extra={
                    "execution_id": pending.execution_id,
                    "kind": kind.value,
                    "error_type": type(error).__name__,
                },
                exc_info=error,
            )
