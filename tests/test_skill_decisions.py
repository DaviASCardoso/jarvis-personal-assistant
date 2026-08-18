"""A Skill `decisions.recent`, contra um `ReflectionToolBackend` de verdade
(com a operação `recent_decisions` injetada — devolve `DecisionRecord`
diretamente, sem precisar de um Event Store real: `project_decisions` já
tem cobertura própria em `tests/test_decisions_query.py`).

Mesma estrutura de `test_skill_builtin.py`/`test_skill_computer.py`: Skill é
Core puro, compõe chamadas de Tool e valida a regra de negócio dela; o I/O
mora no backend.
"""

from datetime import UTC, datetime

from jarvis.decisions.record import DecisionRecord
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.builtin.decisions import recent_decisions_skill
from jarvis.skills.skill import Skill, SkillInvocation, SkillOutput
from jarvis.tools.access import ToolAccess
from jarvis.tools.adapters.reflection_backend import ReflectionToolBackend
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import counting_monotonic

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _record(decision_id: str) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        decision_type="notify",
        reason="r",
        message="oi",
        decided_at=NOON,
        correlation_id="corr-1",
        consulted_llm=False,
    )


def _unused_forget_memory(memory_id: str, reason: str) -> None:
    raise AssertionError("não usado neste teste")


def run(skill: Skill, records: tuple[DecisionRecord, ...], **parameters: object) -> SkillOutput:
    backend = ReflectionToolBackend(
        forget_memory=_unused_forget_memory,  # type: ignore[arg-type]
        list_pending_tasks=lambda: (),
        recent_decisions=lambda limit: records[:limit],
    )
    registry = ToolRegistry()
    registry.register_backend(backend)
    registry.refresh()
    router = ToolRouter(registry=registry, monotonic=counting_monotonic())
    access = ToolAccess(
        router=router,
        execution_id="exec-1",
        correlation_id="corr-1",
        allowed=skill.descriptor.allowed_tools,
        idempotent=skill.descriptor.idempotency is Idempotency.SAFE,
    )
    validated = skill.descriptor.parameters.validate(parameters)  # type: ignore[arg-type]
    return skill.handler.execute(
        SkillInvocation(
            execution_id="exec-1",
            correlation_id="corr-1",
            parameters=validated,
            tools=access,
            now=NOON,
        )
    )


class TestCatalog:
    def test_it_is_no_risk_and_never_asks(self) -> None:
        descriptor = recent_decisions_skill().descriptor

        assert descriptor.risk is RiskLevel.NONE
        assert descriptor.effects == frozenset({Effect.READ})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.NEVER
        assert descriptor.idempotency is Idempotency.SAFE
        assert descriptor.capabilities == frozenset({"decisions:read"})


class TestRecentDecisions:
    def test_it_lists_the_records_the_tool_returns(self) -> None:
        records = (_record("d1"), _record("d2"))

        output = run(recent_decisions_skill(), records)

        decisions = output.data["decisions"]
        assert isinstance(decisions, list)
        assert {item["decision_id"] for item in decisions} == {"d1", "d2"}
        assert output.data["count"] == 2

    def test_the_default_limit_is_applied_when_omitted(self) -> None:
        records = tuple(_record(f"d{index}") for index in range(3))

        output = run(recent_decisions_skill(), records, limit=1)

        assert output.data["count"] == 1

    def test_no_decisions_is_reported_as_an_empty_list(self) -> None:
        output = run(recent_decisions_skill(), ())

        assert output.data["decisions"] == []
        assert output.data["count"] == 0
