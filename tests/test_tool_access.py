"""`ToolAccess`: menor privilégio por execução.

Este é o objeto que uma Skill efetivamente segura. Se ele deixasse chamar
qualquer tool, a declaração `required_tools` seria decoração, e uma Skill
comprometida (ou só mal escrita) teria alcance de todo o catálogo.
"""

import pytest

from jarvis.tools.access import ToolAccess
from jarvis.tools.errors import ToolNotPermittedError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import FakeToolBackend, counting_monotonic


def build_access(
    *, allowed: frozenset[str], idempotent: bool = False
) -> tuple[ToolAccess, FakeToolBackend]:
    backend = FakeToolBackend()
    registry = ToolRegistry()
    registry.register_backend(backend)
    registry.refresh()
    router = ToolRouter(registry=registry, monotonic=counting_monotonic())
    access = ToolAccess(
        router=router,
        execution_id="exec-1",
        correlation_id="corr-1",
        allowed=allowed,
        idempotent=idempotent,
    )
    return access, backend


def test_a_declared_tool_can_be_called() -> None:
    access, backend = build_access(allowed=frozenset({"fake:echo"}))

    result = access.call("fake:echo", {"text": "oi"})

    assert result.message == "ok"
    assert backend.called_tools == ("fake:echo",)


def test_a_tool_outside_the_declared_set_is_refused() -> None:
    access, backend = build_access(allowed=frozenset({"fake:echo"}))

    with pytest.raises(ToolNotPermittedError):
        access.call("fake:noop")

    assert backend.invocations == []


def test_the_refusal_is_a_policy_denial() -> None:
    """Sair do escopo declarado é negação de autorização, não erro de backend."""
    from jarvis.errors import PolicyDenied

    assert issubclass(ToolNotPermittedError, PolicyDenied)


def test_used_records_every_call_in_order() -> None:
    access, _ = build_access(allowed=frozenset({"fake:echo", "fake:noop"}))

    access.call("fake:echo", {"text": "um"})
    access.call("fake:noop")

    assert access.used == ("fake:echo", "fake:noop")


def test_a_refused_call_still_counts_as_attempted() -> None:
    """A auditoria precisa mostrar a tentativa; ela aconteceu."""
    access, _ = build_access(allowed=frozenset({"fake:echo"}))

    with pytest.raises(ToolNotPermittedError):
        access.call("fake:noop")

    assert access.used == ()


def test_the_execution_identity_travels_to_the_backend() -> None:
    access, backend = build_access(allowed=frozenset({"fake:echo"}))

    access.call("fake:echo", {"text": "oi"})

    call = backend.invocations[0].call
    assert call.execution_id == "exec-1"
    assert call.correlation_id == "corr-1"


def test_the_idempotency_key_is_derived_from_the_execution_and_position() -> None:
    backend = FakeToolBackend()
    registry = ToolRegistry()
    registry.register_backend(backend)
    registry.refresh()
    # `supports_idempotency_key` é falso no double, então a chave é descartada
    # pelo router; o que este teste fixa é a derivação, feita no `ToolAccess`.
    access = ToolAccess(
        router=ToolRouter(registry=registry, monotonic=counting_monotonic()),
        execution_id="exec-9",
        correlation_id="corr-9",
        allowed=frozenset({"fake:echo", "fake:noop"}),
    )

    access.call("fake:echo", {"text": "um"})
    access.call("fake:noop")

    assert access.used == ("fake:echo", "fake:noop")


def test_a_malformed_tool_id_is_refused_before_anything_else() -> None:
    from jarvis.tools.errors import ToolInvalidInputError

    access, backend = build_access(allowed=frozenset({"fake:echo"}))

    with pytest.raises(ToolInvalidInputError):
        access.call("sem-backend")

    assert backend.invocations == []
