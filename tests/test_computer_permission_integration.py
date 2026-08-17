"""Fase 8.3 — Permission System: as cinco Skills de computador contra o
Policy Engine de verdade.

O modelo de permissão (capabilities, `RiskLevel`, `Effect`,
`ConfirmationRequirement`) já existe inteiro desde a Fase 5
(`jarvis/policy/`) — esta fase não recria nada, só **prova** que a
integração das capacidades novas (`computer:read/open/close/run`) é segura
por padrão. Mesma estrutura de `test_action_security.py`: sistema real
montado, `ComputerToolBackend` com as operações nativas injetadas (nenhum
teste toca `psutil`/`ctypes`/`subprocess`), e cada teste prova uma barreira
específica em vez de confiar que ela existe.
"""

from collections.abc import Sequence

from jarvis.execution.model import ActionRequest, Actor, ExecutionStatus
from jarvis.execution.orchestrator import ActionExecutor
from jarvis.policy.engine import PolicyEngine
from jarvis.policy.rules import PolicyRuleSet
from jarvis.policy.vocabulary import parse_capabilities
from jarvis.skills.builtin.computer import (
    close_app_skill,
    focus_window_skill,
    list_processes_skill,
    open_app_skill,
    run_command_skill,
)
from jarvis.skills.registry import SkillRegistry
from jarvis.tools.adapters.computer_backend import ComputerToolBackend
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import (
    NOON,
    InMemoryActionRepository,
    RecordingAuditLog,
    counting_monotonic,
    frozen_clock,
)

ALL_COMPUTER_CAPABILITIES = frozenset(
    {"computer:read", "computer:open", "computer:close", "computer:run"}
)


class Fixture:
    def __init__(self, *, granted: frozenset[str] = frozenset()) -> None:
        launched: list[Sequence[str]] = []
        self.launched = launched
        self.backend = ComputerToolBackend(
            command_allowlist={"notepad": ("notepad.exe",)},
            list_process_names=lambda: ["notepad.exe"],
            focus_window=lambda application: True,
            launch=launched.append,
            terminate_processes=lambda application: 1,
        )
        self.tools = ToolRegistry()
        self.tools.register_backend(self.backend)
        self.tools.refresh()
        self.skills = SkillRegistry()
        self.skills.register_all(
            (
                list_processes_skill(),
                focus_window_skill(),
                open_app_skill(),
                close_app_skill(),
                run_command_skill(),
            )
        )
        self.policy = PolicyEngine(
            rules=PolicyRuleSet(granted_capabilities=granted), clock=frozen_clock(NOON)
        )
        self.executor = ActionExecutor(
            skills=self.skills,
            tools=self.tools,
            router=ToolRouter(registry=self.tools, monotonic=counting_monotonic()),
            policy=self.policy,
            repository=InMemoryActionRepository(),
            audit=RecordingAuditLog(),
            clock=frozen_clock(NOON),
            monotonic=counting_monotonic(),
        )

    def submit(self, skill: str, **parameters: object) -> ExecutionStatus:
        outcome = self.executor.submit(
            ActionRequest(
                skill=skill,
                parameters=parameters,  # type: ignore[arg-type]
                correlation_id="corr-1",
                actor=Actor.USER,
            )
        )
        return outcome.status


class TestDeniedByDefault:
    """Configuração default (`JARVIS_POLICY_GRANTED_CAPABILITIES` sem
    `computer:*`, ver `config.py`) nega as cinco de propósito."""

    def test_list_processes_is_denied_without_the_capability(self) -> None:
        fixture = Fixture(granted=frozenset())

        status = fixture.submit("computer.list_processes")

        assert status is ExecutionStatus.DENIED

    def test_focus_window_is_denied_without_the_capability(self) -> None:
        fixture = Fixture(granted=frozenset())

        status = fixture.submit("computer.focus_window", application="notepad")

        assert status is ExecutionStatus.DENIED

    def test_open_app_is_denied_without_the_capability(self) -> None:
        fixture = Fixture(granted=frozenset())

        status = fixture.submit("computer.open_app", name="notepad")

        assert status is ExecutionStatus.DENIED
        assert fixture.launched == []

    def test_close_app_is_denied_without_the_capability(self) -> None:
        fixture = Fixture(granted=frozenset())

        status = fixture.submit("computer.close_app", application="notepad")

        assert status is ExecutionStatus.DENIED

    def test_run_command_is_denied_without_the_capability(self) -> None:
        fixture = Fixture(granted=frozenset())

        status = fixture.submit("computer.run_command", name="notepad")

        assert status is ExecutionStatus.DENIED

    def test_granting_only_read_still_denies_the_other_four(self) -> None:
        fixture = Fixture(granted=frozenset({"computer:read"}))

        assert fixture.submit("computer.open_app", name="notepad") is ExecutionStatus.DENIED
        assert fixture.submit("computer.close_app", application="notepad") is ExecutionStatus.DENIED
        assert fixture.submit("computer.run_command", name="notepad") is ExecutionStatus.DENIED


class TestGrantedButStillGated:
    """Capacidade concedida não é o fim da história: risco/efeito continuam
    valendo, exatamente como já valem para `file.write` desde a Fase 5."""

    def test_read_only_skills_execute_straight_through(self) -> None:
        fixture = Fixture(granted=frozenset({"computer:read"}))

        assert fixture.submit("computer.list_processes") is ExecutionStatus.COMPLETED
        assert (
            fixture.submit("computer.focus_window", application="notepad")
            is ExecutionStatus.COMPLETED
        )

    def test_open_app_still_asks_for_confirmation(self) -> None:
        """`effect=PHYSICAL` está em `DEFAULT_CONFIRM_EFFECTS` — pedida pelo
        usuário ou não, o efeito por si só já exige confirmação."""
        fixture = Fixture(granted=frozenset({"computer:open"}))

        status = fixture.submit("computer.open_app", name="notepad")

        assert status is ExecutionStatus.AWAITING_CONFIRMATION
        assert fixture.launched == []

    def test_close_app_still_asks_for_confirmation(self) -> None:
        fixture = Fixture(granted=frozenset({"computer:close"}))

        status = fixture.submit("computer.close_app", application="notepad")

        assert status is ExecutionStatus.AWAITING_CONFIRMATION

    def test_run_command_still_asks_for_confirmation(self) -> None:
        fixture = Fixture(granted=frozenset({"computer:run"}))

        status = fixture.submit("computer.run_command", name="notepad")

        assert status is ExecutionStatus.AWAITING_CONFIRMATION

    def test_granting_everything_still_gates_the_destructive_three(self) -> None:
        fixture = Fixture(granted=ALL_COMPUTER_CAPABILITIES)

        assert fixture.submit("computer.list_processes") is ExecutionStatus.COMPLETED
        assert fixture.submit("computer.open_app", name="notepad") is (
            ExecutionStatus.AWAITING_CONFIRMATION
        )
        assert fixture.submit("computer.close_app", application="notepad") is (
            ExecutionStatus.AWAITING_CONFIRMATION
        )
        assert fixture.submit("computer.run_command", name="notepad") is (
            ExecutionStatus.AWAITING_CONFIRMATION
        )


class TestDefaultPolicyConfiguration:
    """`config.py`'s `policy_granted_capabilities` default nunca incluiu
    `computer:*` — a mesma prova que `Settings()` faria, sem montar toda a CLI."""

    def test_the_default_allowlist_grants_none_of_the_four(self) -> None:
        from jarvis.config import Settings

        granted = parse_capabilities(Settings().policy_granted_capabilities)

        assert not (granted & ALL_COMPUTER_CAPABILITIES)
