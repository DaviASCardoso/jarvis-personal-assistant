"""O Tool Router é o ponto de estrangulamento: valida, cronometra, normaliza, audita."""

import pytest

from jarvis.audit import AuditKind
from jarvis.tools.errors import (
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolTimeoutError,
    ToolUnavailableError,
)
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRetryPolicy, ToolRouter
from jarvis.tools.tool import ToolCall
from tests.action_doubles import (
    ExplodingToolBackend,
    FakeToolBackend,
    RecordingAuditLog,
    counting_monotonic,
)


def build(
    backend: FakeToolBackend | ExplodingToolBackend, **changes: object
) -> tuple[ToolRouter, RecordingAuditLog]:
    registry = ToolRegistry()
    registry.register_backend(backend)
    registry.refresh()
    audit = RecordingAuditLog()
    options: dict[str, object] = {
        "registry": registry,
        "audit": audit,
        "monotonic": counting_monotonic(),
        "sleep": lambda _: None,
    }
    options.update(changes)
    return ToolRouter(**options), audit  # type: ignore[arg-type]


def make_call(**changes: object) -> ToolCall:
    fields: dict[str, object] = {
        "tool_id": "fake:echo",
        "parameters": {"text": "oi"},
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
    }
    fields.update(changes)
    return ToolCall(**fields)  # type: ignore[arg-type]


class TestResolution:
    def test_a_known_tool_is_dispatched_to_its_backend(self) -> None:
        backend = FakeToolBackend(message="feito")
        router, _ = build(backend)

        result = router.call(make_call())

        assert result.message == "feito"
        assert backend.called_tools == ("fake:echo",)

    def test_an_unknown_tool_never_reaches_a_backend(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend)

        with pytest.raises(ToolNotFoundError):
            router.call(make_call(tool_id="fake:inexistente"))

        assert backend.invocations == []


class TestSchemaValidation:
    def test_parameters_are_validated_before_dispatch(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend)

        with pytest.raises(ToolInvalidInputError):
            router.call(make_call(parameters={}))

        assert backend.invocations == []

    def test_the_backend_receives_the_validated_parameters(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend)

        router.call(make_call(parameters={"text": "oi"}))

        assert dict(backend.invocations[0].call.parameters) == {"text": "oi"}


class TestTimeout:
    def test_the_default_budget_is_applied(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend, default_timeout_seconds=7.5)

        router.call(make_call())

        assert backend.invocations[0].timeout_seconds == 7.5

    def test_the_call_can_override_the_budget(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend, default_timeout_seconds=7.5)

        router.call(make_call(timeout_seconds=1.0))

        assert backend.invocations[0].timeout_seconds == 1.0


class TestRetry:
    def test_a_retryable_failure_is_repeated_when_the_execution_is_idempotent(self) -> None:
        backend = FakeToolBackend(failures=[ToolTimeoutError("demorou")])
        router, _ = build(backend, retry=ToolRetryPolicy(max_attempts=2, base_delay=0))

        result = router.call(make_call(), idempotent=True)

        assert result.message == "ok"
        assert len(backend.invocations) == 2

    def test_a_retryable_failure_is_not_repeated_when_the_execution_is_not_idempotent(
        self,
    ) -> None:
        """Timeout não prova que a operação não aconteceu do outro lado."""
        backend = FakeToolBackend(failures=[ToolTimeoutError("demorou")])
        router, _ = build(backend, retry=ToolRetryPolicy(max_attempts=3, base_delay=0))

        with pytest.raises(ToolTimeoutError):
            router.call(make_call(), idempotent=False)

        assert len(backend.invocations) == 1

    def test_a_permanent_failure_is_never_repeated(self) -> None:
        backend = FakeToolBackend(failures=[ToolExecutionError("recusou")])
        router, _ = build(backend, retry=ToolRetryPolicy(max_attempts=3, base_delay=0))

        with pytest.raises(ToolExecutionError):
            router.call(make_call(), idempotent=True)

        assert len(backend.invocations) == 1

    def test_exhausting_the_attempts_raises_the_last_error(self) -> None:
        backend = FakeToolBackend(
            failures=[ToolUnavailableError("caiu"), ToolUnavailableError("caiu de novo")]
        )
        router, _ = build(backend, retry=ToolRetryPolicy(max_attempts=2, base_delay=0))

        with pytest.raises(ToolUnavailableError):
            router.call(make_call(), idempotent=True)

        assert len(backend.invocations) == 2


class TestErrorNormalization:
    def test_a_native_exception_from_an_adapter_never_reaches_the_caller(self) -> None:
        """Um adapter que não traduz tem bug; o router não deixa o bug atravessar."""
        router, _ = build(ExplodingToolBackend())

        with pytest.raises(ToolExecutionError) as error:
            router.call(make_call(tool_id="exploding:boom", parameters={}))

        assert isinstance(error.value.__cause__, RuntimeError)


class TestAudit:
    def test_a_successful_call_is_recorded_once(self) -> None:
        router, audit = build(FakeToolBackend())

        router.call(make_call())

        entries = audit.of(AuditKind.TOOL_COMPLETED)
        assert len(entries) == 1
        assert entries[0].detail["tool_id"] == "fake:echo"
        assert entries[0].execution_id == "exec-1"
        assert entries[0].correlation_id == "corr-1"

    def test_a_failed_call_is_recorded_once_even_with_retries(self) -> None:
        backend = FakeToolBackend(failures=[ToolTimeoutError("um"), ToolTimeoutError("dois")])
        router, audit = build(backend, retry=ToolRetryPolicy(max_attempts=2, base_delay=0))

        with pytest.raises(ToolTimeoutError):
            router.call(make_call(), idempotent=True)

        entries = audit.of(AuditKind.TOOL_FAILED)
        assert len(entries) == 1
        assert entries[0].detail["attempts"] == 2
        assert entries[0].detail["error_type"] == "ToolTimeoutError"

    def test_the_audit_never_carries_the_parameters(self) -> None:
        router, audit = build(FakeToolBackend())

        router.call(make_call(parameters={"text": "segredo-do-usuario"}))

        assert "segredo-do-usuario" not in str(audit.entries[0].detail)

    def test_the_ordinal_separates_calls_of_the_same_execution(self) -> None:
        router, audit = build(FakeToolBackend())

        router.call(make_call(), ordinal=0)
        router.call(make_call(), ordinal=1)

        assert [entry.ordinal for entry in audit.of(AuditKind.TOOL_COMPLETED)] == [0, 1]

    def test_the_router_works_without_an_audit_log(self) -> None:
        registry = ToolRegistry()
        registry.register_backend(FakeToolBackend())
        registry.refresh()

        router = ToolRouter(registry=registry, monotonic=counting_monotonic())

        assert router.call(make_call()).message == "ok"


class TestIdempotencyKey:
    def test_the_key_is_dropped_when_the_backend_does_not_support_it(self) -> None:
        backend = FakeToolBackend()
        router, _ = build(backend)

        router.call(make_call(idempotency_key="exec-1:0"))

        assert backend.invocations[0].call.idempotency_key is None
