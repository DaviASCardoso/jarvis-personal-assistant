"""O registry de tools é o catálogo do ambiente, e ele degrada em vez de derrubar."""

import pytest

from jarvis.tools.errors import ToolError, ToolNotFoundError, ToolUnavailableError
from jarvis.tools.registry import ToolRegistry
from tests.action_doubles import FakeToolBackend


def test_discovery_populates_the_catalog() -> None:
    registry = ToolRegistry()
    registry.register_backend(FakeToolBackend())

    statuses = registry.refresh()

    assert [item.tool_id for item in registry.list()] == ["fake:echo", "fake:noop"]
    assert statuses[0].available is True
    assert statuses[0].tool_count == 2


def test_two_backends_can_expose_the_same_tool_name() -> None:
    """A qualificação por backend resolve colisão por construção."""
    registry = ToolRegistry()
    registry.register_backend(FakeToolBackend(backend_id="um"))
    registry.register_backend(FakeToolBackend(backend_id="dois"))

    registry.refresh()

    assert registry.has("um:echo")
    assert registry.has("dois:echo")


def test_registering_the_same_backend_twice_is_refused() -> None:
    registry = ToolRegistry()
    registry.register_backend(FakeToolBackend())

    with pytest.raises(ToolError):
        registry.register_backend(FakeToolBackend())


def test_a_backend_that_fails_discovery_is_marked_degraded() -> None:
    registry = ToolRegistry()
    registry.register_backend(FakeToolBackend(backend_id="ok"))
    registry.register_backend(
        FakeToolBackend(backend_id="quebrado", discovery_error=ToolUnavailableError("caiu"))
    )

    statuses = {status.backend_id: status for status in registry.refresh()}

    assert statuses["ok"].available is True
    assert statuses["quebrado"].available is False
    assert statuses["quebrado"].detail == "ToolUnavailableError"
    # O backend saudável continua utilizável.
    assert registry.has("ok:echo")


def test_an_unknown_tool_raises_on_lookup() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError):
        registry.get("fake:echo")
    with pytest.raises(ToolNotFoundError):
        registry.backend_for("fake:echo")


def test_missing_reports_exactly_what_is_absent() -> None:
    """É o que o executor entrega ao Policy Engine para negar antes de executar."""
    registry = ToolRegistry()
    registry.register_backend(FakeToolBackend())
    registry.refresh()

    assert registry.missing(("fake:echo", "fake:ausente")) == ("fake:ausente",)
    assert registry.missing(("fake:echo",)) == ()


def test_refresh_replaces_the_whole_catalog() -> None:
    backend = FakeToolBackend()
    registry = ToolRegistry()
    registry.register_backend(backend)

    registry.refresh()
    registry.refresh()

    assert backend.discoveries == 2
    assert len(registry.list()) == 2


def test_close_reaches_every_backend() -> None:
    first = FakeToolBackend(backend_id="um")
    second = FakeToolBackend(backend_id="dois")
    registry = ToolRegistry()
    registry.register_backend(first)
    registry.register_backend(second)

    registry.close()

    assert first.closed == 1
    assert second.closed == 1


def test_a_backend_that_fails_to_close_does_not_stop_the_others() -> None:
    class RudeBackend(FakeToolBackend):
        def close(self) -> None:
            raise RuntimeError("recusou encerrar")

    rude = RudeBackend(backend_id="rude")
    polite = FakeToolBackend(backend_id="educado")
    registry = ToolRegistry()
    registry.register_backend(rude)
    registry.register_backend(polite)

    registry.close()

    assert polite.closed == 1
