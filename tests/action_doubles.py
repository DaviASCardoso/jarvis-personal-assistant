"""Doubles da camada de ação: tools, skills, política, execução e transporte MCP.

Tudo determinístico e em memória. Nenhum teste da Fase 5 depende de rede,
credencial ou serviço externo — a única exceção é `tests/mcp_fake_server.py`, que
sobe um subprocesso **local** falando o protocolo de verdade.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from jarvis.audit import AuditEntry, AuditKind
from jarvis.events.event import JsonValue
from jarvis.execution.model import ExecutionStatus, PendingAction
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.skill import Skill, SkillDescriptor, SkillInvocation, SkillOutput
from jarvis.tools.errors import ToolError, ToolNotFoundError
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolId, ToolResult

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(minutes=30)


def frozen_clock(*moments: datetime) -> Callable[[], datetime]:
    """Relógio que percorre os instantes dados e depois repete o último."""
    remaining = list(moments) or [NOON]

    def clock() -> datetime:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return clock


def counting_monotonic(step: float = 0.001) -> Callable[[], float]:
    ticks = [0.0]

    def monotonic() -> float:
        ticks[0] += step
        return ticks[0]

    return monotonic


# --------------------------------------------------------------------- tools


@dataclass(slots=True)
class RecordedInvocation:
    call: ToolCall
    timeout_seconds: float


class FakeToolBackend:
    """Backend programável: registra tudo que recebe e devolve o que mandarem.

    `failures` é consumida por chamada — é o que permite testar "falha uma vez,
    depois funciona" sem relógio nem sorte.
    """

    def __init__(
        self,
        *,
        backend_id: str = "fake",
        descriptors: Sequence[ToolDescriptor] | None = None,
        data: Mapping[str, JsonValue] | None = None,
        message: str = "ok",
        failures: Sequence[ToolError] = (),
        discovery_error: ToolError | None = None,
    ) -> None:
        self._backend_id = backend_id
        self._descriptors = (
            tuple(descriptors) if descriptors is not None else _default_tools(backend_id)
        )
        self._data = dict(data) if data is not None else {}
        self._message = message
        self._failures = list(failures)
        self._discovery_error = discovery_error
        self.invocations: list[RecordedInvocation] = []
        self.discoveries = 0
        self.closed = 0

    @property
    def backend_id(self) -> str:
        return self._backend_id

    def discover(self) -> Sequence[ToolDescriptor]:
        self.discoveries += 1
        if self._discovery_error is not None:
            raise self._discovery_error
        return self._descriptors

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        self.invocations.append(RecordedInvocation(call=call, timeout_seconds=timeout_seconds))
        if self._failures:
            raise self._failures.pop(0)
        known = {descriptor.tool_id for descriptor in self._descriptors}
        if call.tool_id not in known:
            raise ToolNotFoundError(f"{call.tool_id} não existe neste backend")
        return ToolResult(
            tool_id=call.tool_id,
            backend_id=self._backend_id,
            execution_id=call.execution_id,
            data=self._data,
            message=self._message,
        )

    def close(self) -> None:
        self.closed += 1

    def fail_next(self, error: ToolError) -> None:
        """Programa uma falha para a próxima chamada, e só para ela."""
        self._failures.append(error)

    @property
    def called_tools(self) -> tuple[ToolId, ...]:
        return tuple(item.call.tool_id for item in self.invocations)


class ExplodingToolBackend:
    """Backend que deixa escapar exceção nativa — o bug que o router precisa conter."""

    backend_id = "exploding"

    def __init__(self, *, tool_id: ToolId = "exploding:boom") -> None:
        self._tool_id = tool_id

    def discover(self) -> Sequence[ToolDescriptor]:
        return (
            ToolDescriptor(
                tool_id=self._tool_id,
                backend_id=self.backend_id,
                name=self._tool_id.split(":", 1)[1],
                summary="explode",
            ),
        )

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        raise RuntimeError("erro nativo que nunca deveria vazar")

    def close(self) -> None:
        return None


def _default_tools(backend_id: str) -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_id=f"{backend_id}:echo",
            backend_id=backend_id,
            name="echo",
            summary="Devolve o que recebeu.",
            parameters=ParameterSchema(
                fields={"text": FieldSpec(type=FieldType.STRING, required=True)}
            ),
        ),
        ToolDescriptor(
            tool_id=f"{backend_id}:noop",
            backend_id=backend_id,
            name="noop",
            summary="Não faz nada.",
        ),
    )


# -------------------------------------------------------------------- skills


def make_descriptor(
    *,
    name: str = "test.skill",
    summary: str = "Uma skill de teste.",
    parameters: ParameterSchema | None = None,
    capabilities: frozenset[str] = frozenset({"test:run"}),
    required_tools: tuple[ToolId, ...] = ("fake:echo",),
    risk: RiskLevel = RiskLevel.LOW,
    effects: frozenset[Effect] = frozenset({Effect.READ}),
    confirmation_requirement: ConfirmationRequirement = ConfirmationRequirement.NEVER,
    idempotency: Idempotency = Idempotency.SAFE,
) -> SkillDescriptor:
    return SkillDescriptor(
        name=name,
        summary=summary,
        parameters=parameters
        if parameters is not None
        else ParameterSchema(fields={"text": FieldSpec(type=FieldType.STRING, required=True)}),
        capabilities=capabilities,
        required_tools=required_tools,
        risk=risk,
        effects=effects,
        confirmation_requirement=confirmation_requirement,
        idempotency=idempotency,
    )


class EchoSkillHandler:
    """Handler que chama a tool declarada e devolve um resumo sem conteúdo."""

    def __init__(self, *, tool_id: ToolId = "fake:echo", extra_tool: ToolId | None = None) -> None:
        self._tool_id = tool_id
        self._extra_tool = extra_tool
        self.invocations: list[SkillInvocation] = []

    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        self.invocations.append(invocation)
        result = invocation.tools.call(self._tool_id, dict(invocation.parameters))
        if self._extra_tool is not None:
            # Usada só pelo teste de menor privilégio: pedir uma tool fora do
            # conjunto declarado precisa ser recusado.
            invocation.tools.call(self._extra_tool, {})
        return SkillOutput(data={"echo": result.message}, summary="feito")


class FailingSkillHandler:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def execute(self, invocation: SkillInvocation) -> SkillOutput:
        raise self._error


def make_skill(
    *, descriptor: SkillDescriptor | None = None, handler: object | None = None
) -> Skill:
    resolved = descriptor if descriptor is not None else make_descriptor()
    return Skill(
        descriptor=resolved,
        handler=handler if handler is not None else EchoSkillHandler(),  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ auditoria


class RecordingAuditLog:
    def __init__(self, *, fail_on: AuditKind | None = None, error: Exception | None = None) -> None:
        self.entries: list[AuditEntry] = []
        self._fail_on = fail_on
        self._error = error

    def record(self, entry: AuditEntry) -> None:
        if self._fail_on is not None and entry.kind is self._fail_on:
            raise self._error if self._error is not None else RuntimeError("audit indisponível")
        self.entries.append(entry)

    @property
    def kinds(self) -> tuple[AuditKind, ...]:
        return tuple(entry.kind for entry in self.entries)

    def of(self, kind: AuditKind) -> list[AuditEntry]:
        return [entry for entry in self.entries if entry.kind is kind]


# ------------------------------------------------------------------ execução


@dataclass(slots=True)
class InMemoryActionRepository:
    """Implementação em memória de `ActionRepository`."""

    rows: dict[str, PendingAction] = field(default_factory=dict)

    def put(self, pending: PendingAction) -> None:
        if pending.execution_id in self.rows:
            raise AssertionError(f"execução já registrada: {pending.execution_id}")
        self.rows[pending.execution_id] = pending

    def get(self, execution_id: str) -> PendingAction | None:
        return self.rows.get(execution_id)

    def list_by_status(
        self, status: ExecutionStatus, *, limit: int | None = None
    ) -> Sequence[PendingAction]:
        found = [row for row in self.rows.values() if row.status is status]
        found.sort(key=lambda row: row.requested_at)
        return found if limit is None else found[:limit]

    def mark(
        self, execution_id: str, *, status: ExecutionStatus, moment: datetime, reason: str = ""
    ) -> PendingAction:
        current = self.rows[execution_id]
        updated = _replace(current, status=status, updated_at=moment, reason=reason)
        self.rows[execution_id] = updated
        return updated

    def confirm(self, execution_id: str, *, moment: datetime) -> PendingAction:
        current = self.rows[execution_id]
        updated = _replace(current, confirmed_at=moment, updated_at=moment)
        self.rows[execution_id] = updated
        return updated

    def expire_pending(self, *, moment: datetime) -> Sequence[PendingAction]:
        expired: list[PendingAction] = []
        for execution_id, row in list(self.rows.items()):
            if row.status is ExecutionStatus.AWAITING_CONFIRMATION and row.is_expired_at(moment):
                self.rows[execution_id] = _replace(
                    row,
                    status=ExecutionStatus.EXPIRED,
                    updated_at=moment,
                    reason="confirmation_expired",
                )
                expired.append(self.rows[execution_id])
        return expired


def _replace(pending: PendingAction, **changes: object) -> PendingAction:
    fields = {
        "execution_id": pending.execution_id,
        "skill": pending.skill,
        "parameters": pending.parameters,
        "parameters_fingerprint": pending.parameters_fingerprint,
        "actor": pending.actor,
        "correlation_id": pending.correlation_id,
        "status": pending.status,
        "requested_at": pending.requested_at,
        "updated_at": pending.updated_at,
        "decision_id": pending.decision_id,
        "causation_id": pending.causation_id,
        "reason": pending.reason,
        "expires_at": pending.expires_at,
        "confirmed_at": pending.confirmed_at,
    }
    fields.update(changes)
    return PendingAction(**fields)  # type: ignore[arg-type]


# ----------------------------------------------------------------- transporte


class FakeTransport:
    """Transporte MCP em memória: uma fila de linhas de resposta.

    É o que permite testar handshake, `id` trocado, corpo malformado e servidor
    que morre — sem `subprocess`, sem espera real e sem depender do sistema
    operacional.
    """

    def __init__(self, responses: Sequence[str | Exception] = ()) -> None:
        self.responses: list[str | Exception] = list(responses)
        self.sent: list[str] = []
        self.started = 0
        self.closed = 0
        self.running = False

    def start(self) -> None:
        self.started += 1
        self.running = True

    def send(self, line: str) -> None:
        self.sent.append(line)

    def receive(self, *, timeout_seconds: float) -> str:
        if not self.responses:
            raise AssertionError("o teste não programou resposta suficiente")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed += 1
        self.running = False

    @property
    def is_running(self) -> bool:
        return self.running
