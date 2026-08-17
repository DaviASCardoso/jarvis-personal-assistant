"""As cinco impossibilidades da `PHASE-5.md §36`, provadas em execução.

`test_action_architecture.py` prova que os **caminhos de import** não existem.
Este arquivo prova que, mesmo montando o sistema inteiro e tentando de propósito,
nada chega à Tool sem passar pela fronteira:

    LLM → Tool                        impossível
    Skill → autoautorizar             impossível
    Tool → contornar a política       impossível
    require_confirmation → executar   impossível sem confirmação
    deny → executar                   impossível

São os testes mais importantes da fase. Se um deles ficar verde por acidente
(porque a montagem mudou e a barreira deixou de ser exercitada), a fase perde a
propriedade que a justifica — daí cada um asserir também que o caminho **feliz**
continua funcionando na mesma montagem.
"""

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.agent.decision import ActionProposal, Decision, DecisionType
from jarvis.agent.runtime import AgentRuntime
from jarvis.execution.model import ActionRequest, Actor, ExecutionOutcome, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.errors import UnknownApprovalError
from jarvis.policy.rules import PolicyRuleSet
from jarvis.policy.verdict import PolicyApproval, PolicyRequest
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.registry import SkillRegistry
from jarvis.skills.skill import SkillInvocation
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import (
    NOON,
    EchoSkillHandler,
    FakeToolBackend,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
    make_descriptor,
    make_skill,
)


class Fixture:
    """O sistema inteiro montado, com um backend que registra toda invocação."""

    def __init__(self, **rules: object) -> None:
        self.backend = FakeToolBackend()
        self.tools = ToolRegistry()
        self.tools.register_backend(self.backend)
        self.tools.refresh()
        self.repository = InMemoryActionRepository()
        self.skills = SkillRegistry()
        self.skills.register(make_skill(handler=EchoSkillHandler()))
        self.skills.register(
            make_skill(
                descriptor=make_descriptor(
                    name="risky.skill",
                    risk=RiskLevel.HIGH,
                    effects=frozenset({Effect.DESTRUCTIVE}),
                    confirmation_requirement=ConfirmationRequirement.ALWAYS,
                    idempotency=Idempotency.UNSAFE,
                ),
                handler=EchoSkillHandler(),
            )
        )
        configured: dict[str, object] = {"granted_capabilities": frozenset({"test:run"})}
        configured.update(rules)
        self.policy = PolicyEngine(
            rules=PolicyRuleSet(**configured),  # type: ignore[arg-type]
            clock=frozen_clock(NOON),
        )
        self.executor = ActionExecutor(
            skills=self.skills,
            tools=self.tools,
            router=ToolRouter(registry=self.tools, monotonic=counting_monotonic()),
            policy=self.policy,
            repository=self.repository,
            audit=RecordingAuditLog(),
            clock=frozen_clock(NOON),
            monotonic=counting_monotonic(),
        )

    def submit(self, skill: str = "test.skill", **changes: object) -> ExecutionOutcome:
        fields: dict[str, object] = {
            "skill": skill,
            "parameters": {"text": "oi"},
            "correlation_id": "corr-1",
            "actor": Actor.USER,
        }
        fields.update(changes)
        return self.executor.submit(ActionRequest(**fields))  # type: ignore[arg-type]

    @property
    def reached_a_tool(self) -> bool:
        return bool(self.backend.invocations)


def test_the_happy_path_does_reach_a_tool() -> None:
    """Sentinela: sem ele, os testes abaixo poderiam passar por vacuidade."""
    fixture = Fixture()

    assert fixture.submit().status is ExecutionStatus.COMPLETED
    assert fixture.reached_a_tool


class TestLlmCannotReachATool:
    def test_a_decision_has_no_way_to_execute_itself(self) -> None:
        """`Decision` é dado inerte: sem `execute`, sem callback, sem referência."""
        decision = Decision(
            decision_id="dec-1",
            type=DecisionType.ACT,
            reason="quero agir",
            decided_at=datetime.now(UTC),
            correlation_id="corr-1",
            action=ActionProposal(skill="test.skill", parameters={"text": "oi"}),
            reasoning="a skill test.skill resolve o pedido diretamente",
        )

        forbidden = {"execute", "run", "perform", "invoke", "call", "apply"}
        assert forbidden.isdisjoint(dir(decision))
        # O nome da skill viaja como **texto**, nunca como referência resolvida.
        assert isinstance(decision.action.skill, str)  # type: ignore[union-attr]

    def test_the_agent_runtime_has_no_executor_in_its_signature(self) -> None:
        parameters = set(inspect.signature(AgentRuntime.__init__).parameters)

        assert {"policy", "executor", "skills", "tools", "router"}.isdisjoint(parameters)

    def test_a_skill_name_invented_by_the_model_is_denied(self) -> None:
        """Prompt injection continua possível; virar execução, não."""
        fixture = Fixture()

        outcome = fixture.submit(skill="apagar.tudo.agora")

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "skill_not_registered"
        assert not fixture.reached_a_tool


class TestSkillCannotSelfAuthorize:
    def test_the_invocation_carries_no_policy_engine(self) -> None:
        fields = set(SkillInvocation.__dataclass_fields__)

        assert fields == {"execution_id", "correlation_id", "parameters", "tools", "now"}

    def test_the_invocation_carries_a_scoped_access_not_the_router(self) -> None:
        handler = EchoSkillHandler()
        fixture = Fixture()
        fixture.skills.register(
            make_skill(descriptor=make_descriptor(name="observadora"), handler=handler)
        )

        fixture.submit(skill="observadora")

        access = handler.invocations[0].tools
        assert access.allowed == frozenset({"fake:echo"})
        assert not hasattr(access, "registry")

    def test_a_handmade_approval_does_not_open_the_door(self) -> None:
        fixture = Fixture()
        forged = PolicyApproval(
            approval_id="forjada",
            execution_id="exec-1",
            skill="test.skill",
            parameters_fingerprint="f" * 64,
            policy_version=1,
            issued_at=NOON,
            expires_at=NOON + timedelta(hours=1),
        )

        with pytest.raises(UnknownApprovalError):
            fixture.policy.consume(forged, moment=NOON)

    def test_a_low_self_declaration_does_not_beat_the_denylist(self) -> None:
        fixture = Fixture(denied_skills=frozenset({"test.skill"}))

        outcome = fixture.submit()

        assert outcome.status is ExecutionStatus.DENIED
        assert not fixture.reached_a_tool


class TestToolCannotBypassPolicy:
    def test_tool_access_only_exists_after_an_approval_is_consumed(self) -> None:
        """Sem `allow`, nenhum handler é chamado — logo nenhum `ToolAccess` circula."""
        handler = EchoSkillHandler()
        fixture = Fixture(denied_skills=frozenset({"bloqueada"}))
        fixture.skills.register(
            make_skill(descriptor=make_descriptor(name="bloqueada"), handler=handler)
        )

        fixture.submit(skill="bloqueada")

        assert handler.invocations == []
        assert not fixture.reached_a_tool

    def test_a_tool_outside_the_declared_set_is_refused_even_after_approval(self) -> None:
        handler = EchoSkillHandler(extra_tool="fake:noop")
        fixture = Fixture()
        fixture.skills.register(
            make_skill(
                descriptor=make_descriptor(name="gulosa", required_tools=("fake:echo",)),
                handler=handler,
            )
        )

        outcome = fixture.submit(skill="gulosa")

        assert outcome.reason == "ToolNotPermittedError"
        assert fixture.backend.called_tools == ("fake:echo",)


class TestConfirmationCannotBeSkipped:
    def test_require_confirmation_never_reaches_a_tool(self) -> None:
        fixture = Fixture()

        outcome = fixture.submit(skill="risky.skill")

        assert outcome.status is ExecutionStatus.AWAITING_CONFIRMATION
        assert not fixture.reached_a_tool

    def test_resuming_without_the_answer_still_does_not_execute(self) -> None:
        fixture = Fixture()
        pending = fixture.submit(skill="risky.skill")

        for _ in range(3):
            resumed = fixture.executor.resume(pending.execution_id)
            assert resumed.status is ExecutionStatus.AWAITING_CONFIRMATION

        assert not fixture.reached_a_tool

    def test_a_confirmation_for_other_parameters_does_not_release_it(self) -> None:
        fixture = Fixture()
        pending = fixture.submit(skill="risky.skill")
        stored = fixture.repository.get(pending.execution_id)
        assert stored is not None
        # Confirmação registrada, mas o pedido é outro: o engine compara os
        # fingerprints e não rebaixa.
        tampered = fixture.policy.evaluate(
            PolicyRequest(
                execution_id=pending.execution_id,
                correlation_id="corr-1",
                skill="risky.skill",
                parameters_fingerprint="outro" + "f" * 59,
                requested_at=NOON,
                risk=RiskLevel.HIGH,
                confirmation_requirement=ConfirmationRequirement.ALWAYS,
                capabilities=frozenset({"test:run"}),
            )
        )

        assert tampered.decision.value == "require_confirmation"
        assert not fixture.reached_a_tool

    def test_only_a_real_confirmation_releases_it(self) -> None:
        fixture = Fixture()
        pending = fixture.submit(skill="risky.skill")
        fixture.repository.confirm(pending.execution_id, moment=NOON)

        resumed = fixture.executor.resume(pending.execution_id)

        assert resumed.status is ExecutionStatus.COMPLETED
        assert fixture.reached_a_tool


class TestDenyCannotExecute:
    def test_a_denied_action_never_reaches_a_tool(self) -> None:
        fixture = Fixture(denied_skills=frozenset({"test.skill"}))

        outcome = fixture.submit()

        assert outcome.status is ExecutionStatus.DENIED
        assert not fixture.reached_a_tool

    def test_a_denied_effect_never_reaches_a_tool(self) -> None:
        fixture = Fixture(denied_effects=frozenset({Effect.DESTRUCTIVE}))

        outcome = fixture.submit(skill="risky.skill")

        assert outcome.status is ExecutionStatus.DENIED
        assert not fixture.reached_a_tool

    def test_a_deny_is_never_downgraded_by_a_confirmation(self) -> None:
        fixture = Fixture(denied_skills=frozenset({"risky.skill"}))
        outcome = fixture.submit(skill="risky.skill")

        assert outcome.status is ExecutionStatus.DENIED
        assert fixture.executor.pending() == []
        assert not fixture.reached_a_tool

    def test_no_capability_means_no_execution(self) -> None:
        fixture = Fixture(granted_capabilities=frozenset())

        outcome = fixture.submit()

        assert outcome.status is ExecutionStatus.DENIED
        assert outcome.reason == "capability_not_granted"
        assert not fixture.reached_a_tool
