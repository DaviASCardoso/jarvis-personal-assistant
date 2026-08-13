"""Nada de sensível pode aparecer em log, evento de auditoria ou mensagem de erro.

A camada de ação move três coisas que não podem circular: **parâmetros** (caminho
de arquivo, corpo de mensagem, destinatário), **conteúdo** lido ou escrito, e
**credenciais** de MCP Servers. Este arquivo planta valores reconhecíveis e
assere a ausência deles em todos os caminhos — permitido, negado, aguardando
confirmação e falho.
"""

import logging
from pathlib import Path

import pytest

from jarvis.execution.model import ActionRequest, Actor, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.registry import SkillRegistry
from jarvis.tools.adapters.local_backend import READ_TEXT, WRITE_TEXT, LocalToolBackend
from jarvis.tools.adapters.mcp_config import McpServerSpec, child_environment
from jarvis.tools.errors import ToolTimeoutError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from jarvis.tools.schema import parameters_fingerprint
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

# Valores que só podem existir na memória do processo — nunca num log ou evento.
SECRET_PARAMETER = "consulta-com-a-dra-marina"
SECRET_CONTENT = "resultado do exame: tudo certo"
SECRET_TOKEN = "token-secretissimo-do-usuario"


@pytest.fixture(autouse=True)
def capture_everything(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="jarvis")
    return caplog


def build(**rules: object) -> tuple[ActionExecutor, RecordingAuditLog, FakeToolBackend]:
    backend = FakeToolBackend()
    tools = ToolRegistry()
    tools.register_backend(backend)
    tools.refresh()
    audit = RecordingAuditLog()
    skills = SkillRegistry()
    skills.register(make_skill(handler=EchoSkillHandler()))
    skills.register(
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
    executor = ActionExecutor(
        skills=skills,
        tools=tools,
        router=ToolRouter(registry=tools, audit=audit, monotonic=counting_monotonic()),
        policy=PolicyEngine(
            rules=PolicyRuleSet(**configured),  # type: ignore[arg-type]
            clock=frozen_clock(NOON),
        ),
        repository=InMemoryActionRepository(),
        audit=audit,
        clock=frozen_clock(NOON),
        monotonic=counting_monotonic(),
    )
    return executor, audit, backend


def request(skill: str = "test.skill") -> ActionRequest:
    return ActionRequest(
        skill=skill,
        parameters={"text": SECRET_PARAMETER},
        correlation_id="corr-1",
        actor=Actor.USER,
    )


def assert_clean(caplog: pytest.LogCaptureFixture, audit: RecordingAuditLog) -> None:
    assert SECRET_PARAMETER not in caplog.text
    assert SECRET_PARAMETER not in str([entry.detail for entry in audit.entries])
    assert SECRET_PARAMETER not in str([entry.execution_id for entry in audit.entries])


class TestParametersNeverLeak:
    def test_on_the_allowed_path(self, caplog: pytest.LogCaptureFixture) -> None:
        executor, audit, _ = build()

        outcome = executor.submit(request())

        assert outcome.status is ExecutionStatus.COMPLETED
        assert audit.entries
        assert_clean(caplog, audit)

    def test_on_the_denied_path(self, caplog: pytest.LogCaptureFixture) -> None:
        executor, audit, _ = build(denied_skills=frozenset({"test.skill"}))

        outcome = executor.submit(request())

        assert outcome.status is ExecutionStatus.DENIED
        assert_clean(caplog, audit)

    def test_on_the_confirmation_path(self, caplog: pytest.LogCaptureFixture) -> None:
        executor, audit, _ = build()

        outcome = executor.submit(request("risky.skill"))

        assert outcome.status is ExecutionStatus.AWAITING_CONFIRMATION
        assert_clean(caplog, audit)

    def test_on_the_failure_path(self, caplog: pytest.LogCaptureFixture) -> None:
        executor, audit, backend = build()
        backend.fail_next(ToolTimeoutError("demorou"))
        backend.fail_next(ToolTimeoutError("de novo"))

        outcome = executor.submit(request())

        assert outcome.status is ExecutionStatus.FAILED
        assert_clean(caplog, audit)

    def test_the_audit_carries_the_fingerprint_instead(self) -> None:
        executor, audit, _ = build()

        executor.submit(request())

        requested = audit.entries[0]
        assert requested.detail["parameters_fingerprint"] == parameters_fingerprint(
            {"text": SECRET_PARAMETER}
        )


class TestFileContentNeverLeaks:
    def test_reading_and_writing_keep_the_content_out_of_the_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        backend = LocalToolBackend(root=tmp_path)
        registry = ToolRegistry()
        registry.register_backend(backend)
        registry.refresh()
        audit = RecordingAuditLog()
        router = ToolRouter(registry=registry, audit=audit, monotonic=counting_monotonic())

        from jarvis.tools.tool import ToolCall

        router.call(
            ToolCall(
                tool_id=WRITE_TEXT,
                parameters={"path": "diario.txt", "content": SECRET_CONTENT},
                execution_id="exec-1",
                correlation_id="corr-1",
            )
        )
        result = router.call(
            ToolCall(
                tool_id=READ_TEXT,
                parameters={"path": "diario.txt"},
                execution_id="exec-1",
                correlation_id="corr-1",
            )
        )

        # O conteúdo existe no resultado — é o que o usuário pediu — e em lugar
        # nenhum mais.
        assert result.data["content"] == SECRET_CONTENT
        assert SECRET_CONTENT not in caplog.text
        assert SECRET_CONTENT not in str([entry.detail for entry in audit.entries])
        assert SECRET_CONTENT not in result.message


class TestSecretsNeverLeak:
    def test_the_mcp_child_environment_is_not_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        spec = McpServerSpec(server_id="servidor", command=("x",), env_keys=("MEU_TOKEN",))

        child = child_environment(spec, {"PATH": "/usr/bin", "MEU_TOKEN": SECRET_TOKEN})

        assert child["MEU_TOKEN"] == SECRET_TOKEN
        assert SECRET_TOKEN not in caplog.text

    def test_the_config_file_never_contains_values(self, tmp_path: Path) -> None:
        """`env_keys` nomeia variáveis; o arquivo é versionável sem risco."""
        from jarvis.tools.adapters.mcp_config import load_mcp_config

        config = tmp_path / "mcp.json"
        config.write_text(
            '{"servers": {"s": {"command": ["x"], "env_keys": ["MEU_TOKEN"]}}}',
            encoding="utf-8",
        )

        specs = load_mcp_config(config)

        assert specs[0].env_keys == ("MEU_TOKEN",)
        assert SECRET_TOKEN not in config.read_text(encoding="utf-8")

    def test_a_startup_failure_does_not_echo_the_command_environment(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from jarvis.tools.adapters.mcp_stdio import StdioTransport
        from jarvis.tools.errors import ToolUnavailableError

        transport = StdioTransport(
            command=("executavel-que-nao-existe-em-lugar-nenhum",),
            env={"MEU_TOKEN": SECRET_TOKEN},
            server_id="servidor",
        )

        with pytest.raises(ToolUnavailableError) as error:
            transport.start()

        assert SECRET_TOKEN not in str(error.value)
        assert SECRET_TOKEN not in caplog.text


class TestErrorMessages:
    def test_an_invalid_parameter_error_names_the_field_not_the_value(self) -> None:
        executor, _, _ = build()

        outcome = executor.submit(
            ActionRequest(
                skill="test.skill",
                parameters={"text": SECRET_PARAMETER, "extra": SECRET_CONTENT},
                correlation_id="corr-1",
            )
        )

        assert outcome.reason == "invalid_parameters"
        assert SECRET_CONTENT not in outcome.detail
        assert "extra" in outcome.detail
