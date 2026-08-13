"""`PolicyApproval`: uso único, ligada a uma execução, impossível de forjar.

Estes testes são o que sustenta a afirmação de que o mecanismo não precisa de
criptografia. Uma aprovação vale porque **o emissor a reconhece**, não porque ela
carrega uma assinatura — e quem constrói a dataclass à mão descobre isso na
primeira tentativa de usá-la.
"""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.errors import PolicyDenied
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.errors import (
    ApprovalAlreadyUsedError,
    ApprovalExpiredError,
    ApprovalMismatchError,
    UnknownApprovalError,
)
from jarvis.policy.rules import PolicyRuleSet
from jarvis.policy.verdict import PolicyApproval, PolicyRequest
from jarvis.policy.vocabulary import Effect, RiskLevel

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_engine(*, ttl: float = 60.0) -> PolicyEngine:
    return PolicyEngine(
        rules=PolicyRuleSet(granted_capabilities=frozenset({"file:read"})),
        approval_ttl_seconds=ttl,
        clock=lambda: NOON,
    )


def make_request(**changes: object) -> PolicyRequest:
    fields: dict[str, object] = {
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
        "skill": "file.read",
        "parameters_fingerprint": "f" * 64,
        "requested_at": NOON,
        "risk": RiskLevel.LOW,
        "effects": frozenset({Effect.READ}),
        "capabilities": frozenset({"file:read"}),
    }
    fields.update(changes)
    return PolicyRequest(**fields)  # type: ignore[arg-type]


def issued_approval(engine: PolicyEngine) -> PolicyApproval:
    verdict = engine.evaluate(make_request())
    assert verdict.approval is not None
    return verdict.approval


def test_an_issued_approval_can_be_consumed_once() -> None:
    engine = make_engine()
    approval = issued_approval(engine)

    engine.consume(approval, moment=NOON)

    with pytest.raises(ApprovalAlreadyUsedError):
        engine.consume(approval, moment=NOON)


def test_a_handmade_approval_is_refused() -> None:
    """O ponto central do ADR-0013: construir a dataclass não confere poder."""
    engine = make_engine()
    forged = PolicyApproval(
        approval_id="forjada",
        execution_id="exec-1",
        skill="file.read",
        parameters_fingerprint="f" * 64,
        policy_version=1,
        issued_at=NOON,
        expires_at=NOON + timedelta(hours=1),
    )

    with pytest.raises(UnknownApprovalError):
        engine.consume(forged, moment=NOON)


def test_an_approval_from_another_engine_is_refused() -> None:
    """O ledger é por processo: aprovação não atravessa instância."""
    approval = issued_approval(make_engine())

    with pytest.raises(UnknownApprovalError):
        make_engine().consume(approval, moment=NOON)


def test_an_expired_approval_is_refused() -> None:
    engine = make_engine(ttl=30.0)
    approval = issued_approval(engine)

    with pytest.raises(ApprovalExpiredError):
        engine.consume(approval, moment=NOON + timedelta(seconds=31))


def test_changing_the_parameters_invalidates_the_approval() -> None:
    """Autorizar 'apagar A' nunca autoriza 'apagar B'."""
    engine = make_engine()
    approval = issued_approval(engine)
    tampered = PolicyApproval(
        approval_id=approval.approval_id,
        execution_id=approval.execution_id,
        skill=approval.skill,
        parameters_fingerprint="b" * 64,
        policy_version=approval.policy_version,
        issued_at=approval.issued_at,
        expires_at=approval.expires_at,
    )

    with pytest.raises(ApprovalMismatchError):
        engine.consume(tampered, moment=NOON)


def test_reusing_an_approval_for_another_execution_is_refused() -> None:
    engine = make_engine()
    approval = issued_approval(engine)
    moved = PolicyApproval(
        approval_id=approval.approval_id,
        execution_id="exec-2",
        skill=approval.skill,
        parameters_fingerprint=approval.parameters_fingerprint,
        policy_version=approval.policy_version,
        issued_at=approval.issued_at,
        expires_at=approval.expires_at,
    )

    with pytest.raises(ApprovalMismatchError):
        engine.consume(moved, moment=NOON)


def test_every_approval_failure_is_a_policy_denial() -> None:
    """Quem trata negação em um lugar só continua tratando todas."""
    for error in (
        UnknownApprovalError,
        ApprovalExpiredError,
        ApprovalAlreadyUsedError,
        ApprovalMismatchError,
    ):
        assert issubclass(error, PolicyDenied)
        assert error.retryable is False


def test_two_executions_get_two_approvals() -> None:
    engine = make_engine()

    first = issued_approval(engine)
    second_verdict = engine.evaluate(make_request(execution_id="exec-2"))

    assert second_verdict.approval is not None
    assert second_verdict.approval.approval_id != first.approval_id
