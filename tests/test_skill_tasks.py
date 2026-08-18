"""A Skill `tasks.list_pending`, contra um `ReflectionToolBackend` de verdade
(com a operação `list_pending_tasks` injetada sobre `SqliteTaskRepository`
real — mesmo desenho de `tests/test_tool_reflection_backend.py`).

Mesma estrutura de `test_skill_builtin.py`/`test_skill_computer.py`: Skill é
Core puro, compõe chamadas de Tool e valida a regra de negócio dela; o I/O
mora no backend.
"""

from datetime import UTC, datetime

import pytest

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.builtin.tasks import list_pending_tasks_skill
from jarvis.skills.skill import Skill, SkillInvocation, SkillOutput
from jarvis.tasks.adapters.sqlite_tasks import SqliteTaskRepository
from jarvis.tasks.model import BackgroundTask, TaskStatus
from jarvis.tools.access import ToolAccess
from jarvis.tools.adapters.reflection_backend import ReflectionToolBackend
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import counting_monotonic
from tests.tasks_doubles import make_request

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def task_repo() -> SqliteTaskRepository:
    return SqliteTaskRepository.open(":memory:")


def _task(task_id: str, status: TaskStatus) -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        request=make_request(),
        status=status,
        attempts=0,
        max_attempts=3,
        next_attempt_at=NOON,
        created_at=NOON,
        updated_at=NOON,
    )


def _unused_forget_memory(memory_id: str, reason: str) -> None:
    raise AssertionError("não usado neste teste")


def run(skill: Skill, task_repo: SqliteTaskRepository, **parameters: object) -> SkillOutput:
    backend = ReflectionToolBackend(
        forget_memory=_unused_forget_memory,  # type: ignore[arg-type]
        list_pending_tasks=lambda: [
            task
            for status in (TaskStatus.PENDING, TaskStatus.RETRYING, TaskStatus.RUNNING)
            for task in task_repo.list_by_status(status)
        ],
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
    def test_it_is_no_risk_and_never_asks(self) -> None:
        descriptor = list_pending_tasks_skill().descriptor

        assert descriptor.risk is RiskLevel.NONE
        assert descriptor.effects == frozenset({Effect.READ})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.NEVER
        assert descriptor.idempotency is Idempotency.SAFE
        assert descriptor.capabilities == frozenset({"tasks:read"})


class TestListPendingTasks:
    def test_it_lists_only_unfinished_statuses(self, task_repo: SqliteTaskRepository) -> None:
        task_repo.put(_task("t-pending", TaskStatus.PENDING))
        task_repo.put(_task("t-done", TaskStatus.SUCCEEDED))

        output = run(list_pending_tasks_skill(), task_repo)

        tasks = output.data["tasks"]
        assert isinstance(tasks, list)
        assert {task["task_id"] for task in tasks} == {"t-pending"}
        assert output.data["count"] == 1

    def test_no_pending_tasks_is_reported_as_an_empty_list(
        self, task_repo: SqliteTaskRepository
    ) -> None:
        output = run(list_pending_tasks_skill(), task_repo)

        assert output.data["tasks"] == []
        assert output.data["count"] == 0
