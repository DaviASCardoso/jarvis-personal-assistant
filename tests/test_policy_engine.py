"""O Policy Engine decide, e é a única coisa que decide.

Os testes aqui cobrem as regras uma a uma e, sobretudo, a **composição**: a
propriedade que sustenta a fase inteira é que nenhuma regra consegue rebaixar a
decisão de outra.
"""

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import DEFAULT_CONFIRM_EFFECTS, PolicyRuleSet, evaluate_rules
from jarvis.policy.verdict import Confirmation, PolicyDecision, PolicyRequest
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, RiskLevel

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

ALL_CAPABILITIES = frozenset({"file:read", "file:write", "system:read", "message:send"})


def make_request(**changes: object) -> PolicyRequest:
    fields: dict[str, object] = {
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
        "skill": "file.read",
        "parameters_fingerprint": "f" * 64,
        "requested_at": NOON,
        "actor": "user",
        "risk": RiskLevel.LOW,
        "effects": frozenset({Effect.READ}),
        "confirmation_requirement": ConfirmationRequirement.NEVER,
        "capabilities": frozenset({"file:read"}),
    }
    fields.update(changes)
    return PolicyRequest(**fields)  # type: ignore[arg-type]


def make_engine(**changes: object) -> PolicyEngine:
    fields: dict[str, object] = {"granted_capabilities": ALL_CAPABILITIES}
    fields.update(changes)
    return PolicyEngine(rules=PolicyRuleSet(**fields), clock=lambda: NOON)  # type: ignore[arg-type]


class TestAllow:
    def test_a_harmless_request_is_allowed_and_gets_an_approval(self) -> None:
        verdict = make_engine().evaluate(make_request())

        assert verdict.decision is PolicyDecision.ALLOW
        assert verdict.rule_id == "default_allow"
        assert verdict.approval is not None
        assert verdict.approval.execution_id == "exec-1"

    def test_the_approval_is_bound_to_the_parameters(self) -> None:
        request = make_request(parameters_fingerprint="a" * 64)
        verdict = make_engine().evaluate(request)

        assert verdict.approval is not None
        assert verdict.approval.parameters_fingerprint == "a" * 64

    def test_a_denied_verdict_never_carries_an_approval(self) -> None:
        verdict = make_engine(granted_capabilities=frozenset()).evaluate(make_request())

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.approval is None


class TestDeny:
    def test_an_unregistered_skill_is_denied(self) -> None:
        verdict = make_engine().evaluate(make_request(skill_known=False))

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "skill_not_registered"

    def test_a_missing_tool_is_denied_before_execution(self) -> None:
        verdict = make_engine().evaluate(make_request(missing_tools=("mcp:absent",)))

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "required_tool_unavailable"
        assert "mcp:absent" in verdict.detail

    def test_a_denylisted_skill_is_denied(self) -> None:
        engine = make_engine(denied_skills=frozenset({"file.read"}))

        verdict = engine.evaluate(make_request())

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "skill_denylisted"

    def test_the_denylist_beats_a_low_self_declared_risk(self) -> None:
        """Cinto e suspensório: a autodeclaração da Skill não a protege."""
        engine = make_engine(denied_skills=frozenset({"file.read"}))

        verdict = engine.evaluate(
            make_request(
                risk=RiskLevel.NONE, confirmation_requirement=ConfirmationRequirement.NEVER
            )
        )

        assert verdict.decision is PolicyDecision.DENY

    def test_a_denylisted_effect_is_denied(self) -> None:
        engine = make_engine(denied_effects=frozenset({Effect.DESTRUCTIVE}))

        verdict = engine.evaluate(make_request(effects=frozenset({Effect.DESTRUCTIVE})))

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "effect_denylisted"

    def test_risk_above_the_ceiling_is_denied(self) -> None:
        verdict = make_engine().evaluate(make_request(risk=RiskLevel.CRITICAL))

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "risk_above_ceiling"

    def test_an_ungranted_capability_is_denied(self) -> None:
        engine = make_engine(granted_capabilities=frozenset({"system:read"}))

        verdict = engine.evaluate(make_request(capabilities=frozenset({"file:write"})))

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.reason == "capability_not_granted"
        assert "file:write" in verdict.detail

    def test_an_empty_allowlist_denies_everything(self) -> None:
        """Default restritivo: 'esqueci de configurar' falha fechado."""
        engine = PolicyEngine(rules=PolicyRuleSet(), clock=lambda: NOON)

        assert engine.evaluate(make_request()).decision is PolicyDecision.DENY


class TestConfirmation:
    def test_high_risk_requires_confirmation(self) -> None:
        verdict = make_engine().evaluate(make_request(risk=RiskLevel.HIGH))

        assert verdict.decision is PolicyDecision.REQUIRE_CONFIRMATION
        assert verdict.reason == "risk_requires_confirmation"

    @pytest.mark.parametrize("effect", sorted(DEFAULT_CONFIRM_EFFECTS))
    def test_dangerous_effects_require_confirmation(self, effect: Effect) -> None:
        verdict = make_engine().evaluate(make_request(effects=frozenset({effect})))

        assert verdict.decision is PolicyDecision.REQUIRE_CONFIRMATION

    def test_a_skill_that_always_asks_requires_confirmation(self) -> None:
        verdict = make_engine().evaluate(
            make_request(confirmation_requirement=ConfirmationRequirement.ALWAYS)
        )

        assert verdict.reason == "skill_requires_confirmation"

    def test_a_conditional_skill_executes_when_the_user_asked(self) -> None:
        verdict = make_engine().evaluate(
            make_request(confirmation_requirement=ConfirmationRequirement.CONDITIONAL, actor="user")
        )

        assert verdict.decision is PolicyDecision.ALLOW

    def test_a_conditional_skill_asks_when_an_event_triggered_it(self) -> None:
        """Ninguém está olhando quando o gatilho é um evento."""
        verdict = make_engine().evaluate(
            make_request(
                confirmation_requirement=ConfirmationRequirement.CONDITIONAL, actor="event"
            )
        )

        assert verdict.decision is PolicyDecision.REQUIRE_CONFIRMATION
        assert verdict.reason == "proactive_action_requires_confirmation"

    def test_a_valid_confirmation_downgrades_to_allow(self) -> None:
        request = make_request(
            risk=RiskLevel.HIGH,
            confirmation=Confirmation(
                execution_id="exec-1",
                parameters_fingerprint="f" * 64,
                granted=True,
                responded_at=NOON,
                expires_at=NOON + timedelta(minutes=5),
            ),
        )

        verdict = make_engine().evaluate(request)

        assert verdict.decision is PolicyDecision.ALLOW
        assert verdict.rule_id == "confirmation_satisfied"
        assert verdict.approval is not None

    def test_a_confirmation_for_other_parameters_does_not_count(self) -> None:
        request = make_request(
            risk=RiskLevel.HIGH,
            confirmation=Confirmation(
                execution_id="exec-1",
                parameters_fingerprint="b" * 64,
                granted=True,
                responded_at=NOON,
                expires_at=NOON + timedelta(minutes=5),
            ),
        )

        assert make_engine().evaluate(request).decision is PolicyDecision.REQUIRE_CONFIRMATION

    def test_an_expired_confirmation_does_not_count(self) -> None:
        request = make_request(
            risk=RiskLevel.HIGH,
            confirmation=Confirmation(
                execution_id="exec-1",
                parameters_fingerprint="f" * 64,
                granted=True,
                responded_at=NOON - timedelta(hours=2),
                expires_at=NOON - timedelta(hours=1),
            ),
        )

        assert make_engine().evaluate(request).decision is PolicyDecision.REQUIRE_CONFIRMATION

    def test_a_refused_confirmation_does_not_count(self) -> None:
        request = make_request(
            risk=RiskLevel.HIGH,
            confirmation=Confirmation(
                execution_id="exec-1",
                parameters_fingerprint="f" * 64,
                granted=False,
                responded_at=NOON,
                expires_at=NOON + timedelta(minutes=5),
            ),
        )

        assert make_engine().evaluate(request).decision is PolicyDecision.REQUIRE_CONFIRMATION


class TestComposition:
    def test_the_strongest_rule_wins(self) -> None:
        """Denylist (deny) e risco alto (confirmation) juntos: vence o deny."""
        engine = make_engine(denied_skills=frozenset({"file.read"}))

        verdict = engine.evaluate(make_request(risk=RiskLevel.HIGH))

        assert verdict.decision is PolicyDecision.DENY

    def test_confirmation_never_overrides_a_deny(self) -> None:
        """A propriedade que impede o pior bug possível desta camada."""
        engine = make_engine(denied_skills=frozenset({"file.read"}))
        request = make_request(
            risk=RiskLevel.HIGH,
            confirmation=Confirmation(
                execution_id="exec-1",
                parameters_fingerprint="f" * 64,
                granted=True,
                responded_at=NOON,
                expires_at=NOON + timedelta(minutes=5),
            ),
        )

        verdict = engine.evaluate(request)

        assert verdict.decision is PolicyDecision.DENY
        assert verdict.approval is None

    def test_every_matching_rule_is_recorded(self) -> None:
        engine = make_engine(denied_skills=frozenset({"file.read"}))

        verdict = engine.evaluate(make_request(risk=RiskLevel.HIGH))

        assert "skill_denylisted" in verdict.considered
        assert "risk_requires_confirmation" in verdict.considered

    def test_rule_ids_are_unique(self) -> None:
        outcomes = evaluate_rules(
            make_request(skill_known=False, missing_tools=("x:y",), risk=RiskLevel.CRITICAL),
            PolicyRuleSet(granted_capabilities=ALL_CAPABILITIES),
        )

        rule_ids = [outcome.rule_id for outcome in outcomes]
        assert len(rule_ids) == len(set(rule_ids))


class TestRiskOrdering:
    def test_risk_compares_by_severity_not_alphabetically(self) -> None:
        # `critical` < `low` como texto; a política precisa do oposto.
        assert RiskLevel.CRITICAL.at_least(RiskLevel.LOW)
        assert not RiskLevel.LOW.at_least(RiskLevel.CRITICAL)
        assert RiskLevel.HIGH.at_least(RiskLevel.HIGH)


class TestDeterminism:
    def test_the_same_request_always_gets_the_same_decision(self) -> None:
        engine = make_engine()
        request = make_request(risk=RiskLevel.HIGH)

        first = engine.evaluate(request)
        second = engine.evaluate(request)

        assert first.decision is second.decision
        assert first.rule_id == second.rule_id
