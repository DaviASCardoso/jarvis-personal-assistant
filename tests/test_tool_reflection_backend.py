"""`ReflectionToolBackend` (Fase 11.3): acesso a memória, tarefas e decisões.

Cada operação é injetada como função — mesmo desenho de `ComputerToolBackend`
— então os testes seguem o mesmo espírito: repositórios reais em SQLite
`:memory:`, abertos uma vez por teste (`cli.py` é quem decide abrir/fechar
por chamada em produção; aqui a fixture só precisa que os dados escritos no
arranjo sobrevivam até a Tool ser invocada).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import pytest

from jarvis.decisions.events import DECISION_RECORDED, decision_event
from jarvis.decisions.query import project_decisions
from jarvis.decisions.record import DecisionRecord
from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE as EVENTS_IN_MEMORY
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE as MEMORY_IN_MEMORY
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance, StoredMemory
from jarvis.tasks.adapters.sqlite_tasks import SqliteTaskRepository
from jarvis.tasks.model import BackgroundTask, TaskStatus
from jarvis.tools.adapters.reflection_backend import (
    FORGET_MEMORY,
    LIST_PENDING_TASKS,
    RECENT_DECISIONS,
    ReflectionToolBackend,
)
from jarvis.tools.errors import ToolExecutionError, ToolNotFoundError
from jarvis.tools.tool import ToolCall, ToolResult
from tests.tasks_doubles import make_request

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
USER_ASSERTION = Provenance(origin=MemoryOrigin.USER)


def call(tool_id: str, parameters: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_id=tool_id,
        parameters=parameters or {},  # type: ignore[arg-type]
        execution_id="exec-1",
        correlation_id="corr-1",
    )


def invoke(
    backend: ReflectionToolBackend, tool_id: str, parameters: dict[str, object] | None = None
) -> ToolResult:
    return backend.invoke(call(tool_id, parameters), timeout_seconds=5.0)


@pytest.fixture
def memory_repo() -> SqliteMemoryRepository:
    return SqliteMemoryRepository.open(MEMORY_IN_MEMORY)


@pytest.fixture
def task_repo() -> SqliteTaskRepository:
    return SqliteTaskRepository.open(":memory:")


@pytest.fixture
def event_store() -> SqliteEventStore:
    return SqliteEventStore.open(EVENTS_IN_MEMORY)


@pytest.fixture
def backend(
    memory_repo: SqliteMemoryRepository,
    task_repo: SqliteTaskRepository,
    event_store: SqliteEventStore,
) -> ReflectionToolBackend:
    def forget_memory(memory_id: str, reason: str) -> StoredMemory:
        return MemoryManager(repository=memory_repo).forget(memory_id, reason=reason)

    def list_pending_tasks() -> Sequence[BackgroundTask]:
        return [
            task
            for status in (TaskStatus.PENDING, TaskStatus.RETRYING, TaskStatus.RUNNING)
            for task in task_repo.list_by_status(status)
        ]

    def recent_decisions(limit: int) -> Sequence[DecisionRecord]:
        events = event_store.read_by_type(DECISION_RECORDED, limit=limit)
        return project_decisions(events)

    return ReflectionToolBackend(
        forget_memory=forget_memory,
        list_pending_tasks=list_pending_tasks,
        recent_decisions=recent_decisions,
    )


class TestDiscovery:
    def test_it_exposes_the_three_expected_tools(self, backend: ReflectionToolBackend) -> None:
        found = {item.tool_id for item in backend.discover()}

        assert found == {FORGET_MEMORY, LIST_PENDING_TASKS, RECENT_DECISIONS}

    def test_an_unknown_tool_is_refused(self, backend: ReflectionToolBackend) -> None:
        with pytest.raises(ToolNotFoundError):
            invoke(backend, "reflection:inexistente")


class TestForgetMemory:
    def test_it_invalidates_an_existing_memory(
        self, backend: ReflectionToolBackend, memory_repo: SqliteMemoryRepository
    ) -> None:
        stored = MemoryManager(repository=memory_repo).remember(
            type=MemoryType.PREFERENCE,
            content="prefere reuniões pela manhã",
            provenance=USER_ASSERTION,
            subject="reuniao.horario",
        )
        memory_id = stored.memory.memory_id

        result = invoke(
            backend, FORGET_MEMORY, {"memory_id": memory_id, "reason": "não é mais verdade"}
        )

        assert result.data["memory_id"] == memory_id
        assert result.data["invalidated"] is True
        reloaded = memory_repo.get(memory_id)
        assert reloaded is not None
        assert reloaded.invalidated_at is not None

    def test_an_unknown_memory_id_is_a_structured_error(
        self, backend: ReflectionToolBackend
    ) -> None:
        with pytest.raises(ToolExecutionError, match="não encontrada"):
            invoke(backend, FORGET_MEMORY, {"memory_id": "m-inexistente", "reason": "qualquer"})


class TestListPendingTasks:
    def _task(self, task_id: str, status: TaskStatus) -> BackgroundTask:
        return BackgroundTask(
            task_id=task_id,
            request=make_request(),
            status=status,
            attempts=0,
            max_attempts=3,
            next_attempt_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )

    def test_it_lists_only_unfinished_statuses(
        self, backend: ReflectionToolBackend, task_repo: SqliteTaskRepository
    ) -> None:
        task_repo.put(self._task("t-pending", TaskStatus.PENDING))
        task_repo.put(self._task("t-retrying", TaskStatus.RETRYING))
        task_repo.put(self._task("t-running", TaskStatus.RUNNING))
        task_repo.put(self._task("t-done", TaskStatus.SUCCEEDED))

        result = invoke(backend, LIST_PENDING_TASKS)

        tasks = cast("list[dict[str, object]]", result.data["tasks"])
        found_ids = {task["task_id"] for task in tasks}
        assert found_ids == {"t-pending", "t-retrying", "t-running"}
        assert result.data["count"] == 3

    def test_no_pending_tasks_is_reported_as_an_empty_list(
        self, backend: ReflectionToolBackend
    ) -> None:
        result = invoke(backend, LIST_PENDING_TASKS)

        assert result.data["tasks"] == []
        assert result.data["count"] == 0


class TestRecentDecisions:
    def _publish(self, event_store: SqliteEventStore, decision_id: str) -> None:
        event = decision_event(
            decision_id=decision_id,
            decision_type="notify",
            reason="r",
            message="oi",
            decided_at=NOW,
            correlation_id="corr-1",
            consulted_llm=False,
            source="jarvis-agent",
        )
        event_store.append(event)

    def test_it_lists_the_most_recent_decisions(
        self, backend: ReflectionToolBackend, event_store: SqliteEventStore
    ) -> None:
        self._publish(event_store, "d1")
        self._publish(event_store, "d2")

        result = invoke(backend, RECENT_DECISIONS)

        assert result.data["count"] == 2
        decisions = cast("list[dict[str, object]]", result.data["decisions"])
        decision_ids = {item["decision_id"] for item in decisions}
        assert decision_ids == {"d1", "d2"}

    def test_the_limit_caps_how_many_are_returned(
        self, backend: ReflectionToolBackend, event_store: SqliteEventStore
    ) -> None:
        for index in range(3):
            self._publish(event_store, f"d{index}")

        result = invoke(backend, RECENT_DECISIONS, {"limit": 1})

        assert result.data["count"] == 1

    def test_no_decisions_is_reported_as_an_empty_list(
        self, backend: ReflectionToolBackend
    ) -> None:
        result = invoke(backend, RECENT_DECISIONS)

        assert result.data["decisions"] == []
        assert result.data["count"] == 0
