"""O `ActionExecutor` de ponta a ponta, com doubles.

Cada teste aqui responde a uma pergunta do critério de conclusão da fase: allow
executa, deny impede, confirmação bloqueia, resultado volta, duplicata não
repete.
"""

from datetime import datetime, timedelta

import pytest

from jarvis.execution.model import ActionRequest, Actor, ExecutionOutcome, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.errors import SkillExecutionError
from jarvis.skills.registry import SkillRegistry
from jarvis.tools.errors import ToolTimeoutError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import (
    NOON,
    EchoSkillHandler,
    FailingSkillHandler,
    FakeToolBackend,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
    make_descriptor,
    make_skill,
)


class Harness:
    """Tudo montado como o composition root monta, mas em memória.

    `rebuild` existe para os testes que precisam trocar política ou relógio no
    meio do fluxo — reconstruir o executor sobre o **mesmo** repositório é o que
    simula honestamente "outra invocação do CLI, com outra configuração".
    """

    def __init__(
        self,
        *,
        audit: RecordingAuditLog | None = None,
        now: datetime | None = None,
        **rules: object,
    ) -> None:
        self.backend = FakeToolBackend()
        self.tools = ToolRegistry()
        self.tools.register_backend(self.backend)
        self.tools.refresh()
        self.audit = audit if audit is not None else RecordingAuditLog()
        self.repository = InMemoryActionRepository()
        self.skills = SkillRegistry()
        self.handler = EchoSkillHandler()
        self.skills.register(make_skill(handler=self.handler))
        self.executor = self._build(rules, now if now is not None else NOON)

    def rebuild(self, *, now: datetime | None = None, **rules: object) -> None:
        self.executor = self._build(rules, now if now is not None else NOON)

    def _build(self, rules: dict[str, object], now: datetime) -> ActionExecutor:
        return ActionExecutor(
            skills=self.skills,
            tools=self.tools,
            router=ToolRouter(
                registry=self.tools, audit=self.audit, monotonic=counting_monotonic()
            ),
            policy=PolicyEngine(
                rules=PolicyRuleSet(
                    granted_capabilities=frozenset({"test:run"}),
                    **rules,  # type: ignore[arg-type]
                ),
                clock=frozen_clock(now),
            ),
            repository=self.repository,
            audit=self.audit,
            clock=frozen_clock(now),
            monotonic=counting_monotonic(),
        )

    def submit(self, **changes: object) -> ExecutionOutcome:
        fields: dict[str, object] = {
            "skill": "test.skill",
            "parameters": {"text": "oi"},
            "correlation_id": "corr-1",
            "actor": Actor.USER,
        }
        fields.update(changes)
        return self.executor.submit(ActionRequest(**fields))  # type: ignore[arg-type]


class TestAllow:
    def test_the_happy_path_reaches_the_tool_and_completes(self) -> None:
        harness = Harness()

        outcome = harness.submit()

        assert outcome.status is ExecutionStatus.COMPLETED
        assert outcome.tools_used == ("fake:echo",)
        assert harness.backend.called_tools == ("fake:echo",)
        assert outcome.summary == "feito"

    def test_the_skill_receives_the_validated_parameters(self) -> None:
        harness = Harness()

        harness.submit(parameters={"text": "oi"})

        assert dict(harness.handler.invocations[0].parameters) == {"text": "oi"}

    def test_the_execution_is_recorded_as_completed(self) -> None:
        harness = Harness()

        outcome = harness.submit()

        stored = harness.repository.get(outcome.execution_id)
        assert stored is not None
        assert stored.status is ExecutionStatus.COMPLETED

    def test_the_correlation_travels_to_the_tool(self) -> None:
        harness = Harness()

        harness.submit(correlation_id="corr-42")

        assert harness.backend.invocations[0].call.correlation_id == "corr-42"


class TestDeny:
    def test_a_denied_action_never_reaches_the_tool(self) -> None:
        harness = Harness(denied_skills=frozenset({"test.skill"}))

        outcome = harness.submit()

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "skill_denylisted"
        assert harness.backend.invocations == []
        assert harness.handler.invocations == []

    def test_an_unknown_skill_is_denied_not_crashed(self) -> None:
        harness = Harness()

        outcome = harness.submit(skill="inventada.pelo.modelo")

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "skill_not_registered"
        assert harness.backend.invocations == []

    def test_a_skill_whose_tool_is_missing_is_denied_before_running(self) -> None:
        harness = Harness()
        harness.skills.register(
            make_skill(
                descriptor=make_descriptor(name="sem.tool", required_tools=("fake:ausente",))
            )
        )

        outcome = harness.submit(skill="sem.tool")

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "required_tool_unavailable"

    def test_the_denial_carries_the_verdict_for_the_agent_to_report(self) -> None:
        harness = Harness(denied_skills=frozenset({"test.skill"}))

        outcome = harness.submit()

        assert outcome.verdict is not None
        assert outcome.verdict.rule_id == "skill_denylisted"


class TestInvalidParameters:
    def test_bad_parameters_never_reach_the_policy_engine(self) -> None:
        harness = Harness()

        outcome = harness.submit(parameters={"text": 42})

        assert outcome.status is ExecutionStatus.FAILED
        assert outcome.reason == "invalid_parameters"
        assert harness.audit.entries == []

    def test_unknown_parameters_are_refused(self) -> None:
        harness = Harness()

        outcome = harness.submit(parameters={"text": "oi", "extra": 1})

        assert outcome.reason == "invalid_parameters"


class TestConfirmation:
    def _harness(self) -> Harness:
        harness = Harness()
        harness.skills.register(
            make_skill(
                descriptor=make_descriptor(
                    name="risky.skill",
                    risk=RiskLevel.HIGH,
                    effects=frozenset({Effect.WRITE}),
                    confirmation_requirement=ConfirmationRequirement.ALWAYS,
                    idempotency=Idempotency.UNSAFE,
                ),
                handler=harness.handler,
            )
        )
        return harness

    def test_a_confirmation_requirement_never_reaches_the_tool(self) -> None:
        harness = self._harness()

        outcome = harness.submit(skill="risky.skill")

        assert outcome.status is ExecutionStatus.AWAITING_CONFIRMATION
        assert harness.backend.invocations == []
        assert outcome.expires_at is not None

    def test_resuming_without_a_confirmation_still_waits(self) -> None:
        harness = self._harness()
        pending = harness.submit(skill="risky.skill")

        resumed = harness.executor.resume(pending.execution_id)

        assert resumed.status is ExecutionStatus.AWAITING_CONFIRMATION
        assert harness.backend.invocations == []

    def test_resuming_after_a_confirmation_executes(self) -> None:
        harness = self._harness()
        pending = harness.submit(skill="risky.skill")
        harness.repository.confirm(pending.execution_id, moment=NOON)

        resumed = harness.executor.resume(pending.execution_id)

        assert resumed.status is ExecutionStatus.COMPLETED
        assert harness.backend.called_tools == ("fake:echo",)

    def test_a_denylist_added_after_the_request_still_denies_on_resume(self) -> None:
        """A política é reavaliada do zero; o veredito anterior não vale nada."""
        harness = self._harness()
        pending = harness.submit(skill="risky.skill")
        harness.repository.confirm(pending.execution_id, moment=NOON)
        harness.rebuild(denied_skills=frozenset({"risky.skill"}))

        resumed = harness.executor.resume(pending.execution_id)

        assert resumed.status is ExecutionStatus.DENIED
        assert harness.backend.invocations == []

    def test_an_expired_confirmation_never_executes(self) -> None:
        harness = self._harness()
        pending = harness.submit(skill="risky.skill")
        harness.repository.confirm(pending.execution_id, moment=NOON)
        harness.rebuild(now=NOON + timedelta(hours=2))

        resumed = harness.executor.resume(pending.execution_id)

        assert resumed.status is ExecutionStatus.EXPIRED
        assert harness.backend.invocations == []

    def test_resuming_an_unknown_execution_is_reported_not_crashed(self) -> None:
        harness = Harness()

        outcome = harness.executor.resume("nao-existe")

        assert outcome.reason == "unknown_execution"

    def test_resuming_a_settled_execution_does_nothing(self) -> None:
        harness = Harness()
        done = harness.submit()

        resumed = harness.executor.resume(done.execution_id)

        assert resumed.status is ExecutionStatus.COMPLETED
        assert len(harness.backend.invocations) == 1

    def test_pending_lists_what_is_waiting(self) -> None:
        harness = self._harness()
        harness.submit(skill="risky.skill")

        assert [item.skill for item in harness.executor.pending()] == ["risky.skill"]

    def test_expire_marks_the_overdue_ones(self) -> None:
        harness = self._harness()
        harness.submit(skill="risky.skill")

        assert harness.executor.expire(moment=NOON + timedelta(hours=2)) == 1
        assert harness.executor.pending() == []


class TestFailure:
    def test_a_skill_failure_is_reported_not_raised(self) -> None:
        harness = Harness()
        harness.skills.register(
            make_skill(
                descriptor=make_descriptor(name="quebra"),
                handler=FailingSkillHandler(SkillExecutionError("não deu")),
            )
        )

        outcome = harness.submit(skill="quebra")

        assert outcome.status is ExecutionStatus.FAILED
        assert outcome.reason == "SkillExecutionError"

    def test_a_tool_failure_is_reported_not_raised(self) -> None:
        # Duas falhas: a skill padrão é idempotente, então o router tem direito a
        # uma repetição antes de desistir.
        harness = Harness()
        harness.backend.fail_next(ToolTimeoutError("demorou"))
        harness.backend.fail_next(ToolTimeoutError("de novo"))

        outcome = harness.submit()

        assert outcome.status is ExecutionStatus.FAILED
        assert outcome.reason == "ToolTimeoutError"

    def test_the_failure_is_recorded_in_the_repository(self) -> None:
        harness = Harness()
        harness.backend.fail_next(ToolTimeoutError("demorou"))
        harness.backend.fail_next(ToolTimeoutError("de novo"))

        outcome = harness.submit()

        stored = harness.repository.get(outcome.execution_id)
        assert stored is not None
        assert stored.status is ExecutionStatus.FAILED


class TestIdempotency:
    def test_the_same_decision_produces_the_same_execution_id(self) -> None:
        first = Harness().submit(decision_id="dec-1")
        second = Harness().submit(decision_id="dec-1")

        assert first.execution_id == second.execution_id

    def test_different_parameters_produce_different_executions(self) -> None:
        harness = Harness()

        first = harness.submit(decision_id="dec-1", parameters={"text": "um"})
        second = harness.submit(decision_id="dec-1", parameters={"text": "dois"})

        assert first.execution_id != second.execution_id

    def test_resubmitting_an_executed_decision_does_nothing(self) -> None:
        harness = Harness()
        harness.submit(decision_id="dec-1")

        repeated = harness.submit(decision_id="dec-1")

        assert repeated.status is ExecutionStatus.DUPLICATE
        assert len(harness.backend.invocations) == 1

    def test_resubmitting_a_failed_decision_does_not_repeat_the_effect(self) -> None:
        """Timeout não prova que a operação não aconteceu do outro lado."""
        harness = Harness()
        harness.backend.fail_next(ToolTimeoutError("demorou"))
        harness.backend.fail_next(ToolTimeoutError("de novo"))
        first = harness.submit(decision_id="dec-1")

        repeated = harness.submit(decision_id="dec-1")

        assert first.status is ExecutionStatus.FAILED
        assert repeated.status is ExecutionStatus.DUPLICATE

    def test_a_denied_decision_can_be_resubmitted(self) -> None:
        """Negar não é executar; a política pode ter mudado."""
        harness = Harness(denied_skills=frozenset({"test.skill"}))
        first = harness.submit(decision_id="dec-1")

        second = harness.submit(decision_id="dec-1")

        assert first.status is ExecutionStatus.DENIED
        assert second.status is ExecutionStatus.DENIED

    def test_a_manual_action_twice_is_two_executions(self) -> None:
        """Pedir duas vezes à mão é intenção, não duplicata."""
        harness = Harness()

        first = harness.submit()
        second = harness.submit()

        assert first.execution_id != second.execution_id
        assert len(harness.backend.invocations) == 2


class TestIdempotentRetry:
    def test_a_safe_skill_lets_the_router_retry(self) -> None:
        harness = Harness()
        harness.backend.fail_next(ToolTimeoutError("demorou"))

        outcome = harness.submit()

        # A skill padrão é `SAFE`, mas o router default tem `max_attempts=2`.
        assert outcome.status is ExecutionStatus.COMPLETED
        assert len(harness.backend.invocations) == 2

    def test_an_unsafe_skill_does_not(self) -> None:
        harness = Harness()
        harness.skills.register(
            make_skill(
                descriptor=make_descriptor(name="unsafe.skill", idempotency=Idempotency.UNSAFE),
                handler=harness.handler,
            )
        )
        harness.backend.fail_next(ToolTimeoutError("demorou"))

        outcome = harness.submit(skill="unsafe.skill")

        assert outcome.status is ExecutionStatus.FAILED
        assert len(harness.backend.invocations) == 1


class TestLeastPrivilege:
    def test_a_skill_cannot_call_a_tool_it_did_not_declare(self) -> None:
        harness = Harness()
        harness.skills.register(
            make_skill(
                descriptor=make_descriptor(name="gulosa", required_tools=("fake:echo",)),
                handler=EchoSkillHandler(extra_tool="fake:noop"),
            )
        )

        outcome = harness.submit(skill="gulosa")

        assert outcome.status is ExecutionStatus.FAILED
        assert outcome.reason == "ToolNotPermittedError"
        assert harness.backend.called_tools == ("fake:echo",)


class TestAuditFailure:
    def test_a_broken_audit_aborts_before_executing(self) -> None:
        """Fail-closed: sem trilha do veredito, sem ação."""
        from jarvis.audit import AuditKind

        harness = Harness(audit=RecordingAuditLog(fail_on=AuditKind.POLICY_EVALUATED))

        with pytest.raises(RuntimeError):
            harness.submit()

        assert harness.backend.invocations == []

    def test_a_broken_audit_after_the_effect_does_not_undo_it(self) -> None:
        from jarvis.audit import AuditKind
        from jarvis.errors import InfrastructureError

        class LateFailure(InfrastructureError):
            pass

        harness = Harness(
            audit=RecordingAuditLog(
                fail_on=AuditKind.ACTION_COMPLETED, error=LateFailure("store fora do ar")
            )
        )

        outcome = harness.submit()

        assert outcome.status is ExecutionStatus.COMPLETED
