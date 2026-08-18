"""A Skill `memory.forget`, contra um `ReflectionToolBackend` de verdade
(com a operação `forget_memory` injetada sobre `SqliteMemoryRepository`
real — mesmo desenho de `tests/test_tool_reflection_backend.py`).

Mesma estrutura de `test_skill_builtin.py`/`test_skill_computer.py`: Skill é
Core puro, compõe chamadas de Tool e valida a regra de negócio dela; o I/O
mora no backend.
"""

from datetime import UTC, datetime

import pytest

from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.builtin.memory import forget_memory_skill
from jarvis.skills.errors import SkillInputError
from jarvis.skills.skill import Skill, SkillInvocation, SkillOutput
from jarvis.tools.access import ToolAccess
from jarvis.tools.adapters.reflection_backend import ReflectionToolBackend
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import counting_monotonic

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
USER_ASSERTION = Provenance(origin=MemoryOrigin.USER)


@pytest.fixture
def memory_repo() -> SqliteMemoryRepository:
    return SqliteMemoryRepository.open(IN_MEMORY_DATABASE)


def run(skill: Skill, memory_repo: SqliteMemoryRepository, **parameters: object) -> SkillOutput:
    backend = ReflectionToolBackend(
        forget_memory=lambda memory_id, reason: MemoryManager(repository=memory_repo).forget(
            memory_id, reason=reason
        ),
        list_pending_tasks=lambda: (),
        recent_decisions=lambda limit: (),
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
    def test_it_is_medium_risk_and_asks_when_proactive(self) -> None:
        descriptor = forget_memory_skill().descriptor

        assert descriptor.risk is RiskLevel.MEDIUM
        assert descriptor.effects == frozenset({Effect.WRITE})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.CONDITIONAL
        assert descriptor.idempotency is Idempotency.SAFE
        assert descriptor.capabilities == frozenset({"memory:forget"})


class TestForgetMemory:
    def test_it_invalidates_an_existing_memory(self, memory_repo: SqliteMemoryRepository) -> None:
        stored = MemoryManager(repository=memory_repo).remember(
            type=MemoryType.PREFERENCE,
            content="prefere reuniões pela manhã",
            provenance=USER_ASSERTION,
            subject="reuniao.horario",
        )
        memory_id = stored.memory.memory_id

        output = run(
            forget_memory_skill(),
            memory_repo,
            memory_id=memory_id,
            reason="não é mais verdade",
        )

        assert output.data["memory_id"] == memory_id
        assert memory_id in output.summary
        reloaded = memory_repo.get(memory_id)
        assert reloaded is not None
        assert reloaded.invalidated_at is not None

    def test_an_empty_memory_id_is_refused_before_touching_the_tool(
        self, memory_repo: SqliteMemoryRepository
    ) -> None:
        with pytest.raises(SkillInputError):
            run(forget_memory_skill(), memory_repo, memory_id="   ", reason="qualquer")

    def test_an_empty_reason_is_refused_before_touching_the_tool(
        self, memory_repo: SqliteMemoryRepository
    ) -> None:
        with pytest.raises(SkillInputError):
            run(forget_memory_skill(), memory_repo, memory_id="m1", reason="")
