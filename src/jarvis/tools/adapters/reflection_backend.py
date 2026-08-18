"""Backend de Tools sobre o próprio estado operacional do Jarvis (Fase 11.3).

Três Tools que dão a uma Skill acesso a memória, tarefas em segundo plano e
decisões — dado que `SkillInvocation` só recebe `ToolAccess` como injeção
(nenhum outro canal), e `MemoryManager`/`TaskRepository`/`EventStore` não
estão disponíveis em `build_skill_registry()`. Mesmo padrão de
`ComputerToolBackend`: backend próprio, tema coerente, `backend_id`
dedicado, registrado em `build_tool_registry(settings)`.

Cada operação é **injetada** como função, mesmo desenho de
`ComputerToolBackend` (`list_process_names`, `focus_window`, ...): quem
monta o backend (`cli.py`, único lugar autorizado a conhecer
`jarvis.memory.adapters`/`jarvis.tasks.adapters`/`jarvis.events.adapters` —
`test_only_the_composition_root_wires_*_adapters`) decide como abrir e
fechar a conexão SQLite; este módulo só conhece tipos de domínio
(`StoredMemory`, `BackgroundTask`, `DecisionRecord`), nunca um adapter
concreto.
"""

from collections.abc import Callable, Sequence
from typing import Final

from jarvis.decisions.record import DecisionRecord
from jarvis.events.event import JsonValue
from jarvis.memory.errors import MemoryWriteError
from jarvis.memory.memory import StoredMemory
from jarvis.tasks.model import BackgroundTask
from jarvis.tools.errors import ToolExecutionError, ToolInvalidInputError, ToolNotFoundError
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolResult, make_tool_id

BACKEND_ID: Final = "reflection"

FORGET_MEMORY: Final = make_tool_id(backend_id=BACKEND_ID, name="forget_memory")
LIST_PENDING_TASKS: Final = make_tool_id(backend_id=BACKEND_ID, name="list_pending_tasks")
RECENT_DECISIONS: Final = make_tool_id(backend_id=BACKEND_ID, name="recent_decisions")

MAX_ID_LENGTH: Final = 100
MAX_REASON_LENGTH: Final = 500
DEFAULT_DECISIONS_LIMIT: Final = 10
MAX_DECISIONS_LIMIT: Final = 50

_MEMORY_ID_FIELD: Final = FieldSpec(
    type=FieldType.STRING,
    required=True,
    max_length=MAX_ID_LENGTH,
    description="Identificador da memória a esquecer.",
)
_REASON_FIELD: Final = FieldSpec(
    type=FieldType.STRING,
    required=True,
    max_length=MAX_REASON_LENGTH,
    description="Motivo do esquecimento.",
)
_LIMIT_FIELD: Final = FieldSpec(
    type=FieldType.INTEGER,
    required=False,
    minimum=1,
    maximum=MAX_DECISIONS_LIMIT,
    default=DEFAULT_DECISIONS_LIMIT,
    description="Quantidade máxima de decisões a listar.",
)


def _descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_id=FORGET_MEMORY,
            backend_id=BACKEND_ID,
            name="forget_memory",
            summary="Invalida uma memória pelo id — some do retrieval, sem apagar a evidência.",
            parameters=ParameterSchema(
                fields={"memory_id": _MEMORY_ID_FIELD, "reason": _REASON_FIELD}
            ),
        ),
        ToolDescriptor(
            tool_id=LIST_PENDING_TASKS,
            backend_id=BACKEND_ID,
            name="list_pending_tasks",
            summary="Lista tarefas em segundo plano pendentes, em repetição ou em execução.",
            parameters=ParameterSchema(),
        ),
        ToolDescriptor(
            tool_id=RECENT_DECISIONS,
            backend_id=BACKEND_ID,
            name="recent_decisions",
            summary="Lista as decisões mais recentes registradas como evento.",
            parameters=ParameterSchema(fields={"limit": _LIMIT_FIELD}),
        ),
    )


class ReflectionToolBackend:
    """Implementação de `ToolBackend` sobre memória, tarefas e decisões locais."""

    def __init__(
        self,
        *,
        forget_memory: Callable[[str, str], StoredMemory],
        list_pending_tasks: Callable[[], Sequence[BackgroundTask]],
        recent_decisions: Callable[[int], Sequence[DecisionRecord]],
    ) -> None:
        self._forget_memory_op = forget_memory
        self._list_pending_tasks_op = list_pending_tasks
        self._recent_decisions_op = recent_decisions

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    def discover(self) -> Sequence[ToolDescriptor]:
        return _descriptors()

    def close(self) -> None:
        """Nada a encerrar: cada operação injetada abre e fecha sua própria conexão."""

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        match call.tool_id:
            case _ if call.tool_id == FORGET_MEMORY:
                data, message = self._forget_memory(call)
            case _ if call.tool_id == LIST_PENDING_TASKS:
                data, message = self._list_pending_tasks()
            case _ if call.tool_id == RECENT_DECISIONS:
                data, message = self._recent_decisions(call)
            case _:
                raise ToolNotFoundError(f"{call.tool_id} não é uma tool deste backend")

        return ToolResult(
            tool_id=call.tool_id,
            backend_id=BACKEND_ID,
            execution_id=call.execution_id,
            data=data,
            message=message,
        )

    # ------------------------------------------------------------ operações

    def _forget_memory(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        memory_id = _text(call, "memory_id")
        reason = _text(call, "reason")
        try:
            forgotten = self._forget_memory_op(memory_id, reason)
        except MemoryWriteError as error:
            raise ToolExecutionError(str(error)) from error
        return (
            {"memory_id": forgotten.memory.memory_id, "invalidated": True},
            f"memória {forgotten.memory.memory_id} esquecida",
        )

    def _list_pending_tasks(self) -> tuple[dict[str, JsonValue], str]:
        found = self._list_pending_tasks_op()
        tasks: list[JsonValue] = [
            {
                "task_id": task.task_id,
                "skill": task.request.skill,
                "status": task.status.value,
                "attempts": task.attempts,
                "max_attempts": task.max_attempts,
                "next_attempt_at": task.next_attempt_at.isoformat(),
            }
            for task in found
        ]
        return {"tasks": tasks, "count": len(tasks)}, f"{len(tasks)} tarefa(s) pendente(s)"

    def _recent_decisions(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        limit = call.parameters.get("limit", DEFAULT_DECISIONS_LIMIT)
        assert isinstance(limit, int)  # `ParameterSchema` já validou o tipo
        records = self._recent_decisions_op(limit)
        decisions: list[JsonValue] = [
            {
                "decision_id": record.decision_id,
                "decision_type": record.decision_type,
                "reason": record.reason,
                "message": record.message,
                "decided_at": record.decided_at.isoformat(),
                "action_skill": record.action_skill,
            }
            for record in records
        ]
        return {"decisions": decisions, "count": len(decisions)}, f"{len(decisions)} decisão(ões)"


def _text(call: ToolCall, name: str) -> str:
    value = call.parameters.get(name)
    if not isinstance(value, str):
        raise ToolInvalidInputError(f"{name} precisa ser texto")
    return value
