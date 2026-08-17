"""As cinco Skills de computador, contra um `ComputerToolBackend` de verdade
(com as operações nativas injetadas, mesmo desenho de
`tests/test_tool_computer_backend.py`).

Mesma estrutura de `test_skill_builtin.py`: Skill é Core puro, compõe
chamadas de Tool e valida a regra de negócio dela; o I/O mora no backend.
"""

import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from jarvis.policy.vocabulary import ConfirmationRequirement, Effect, Idempotency, RiskLevel
from jarvis.skills.builtin.computer import (
    close_app_skill,
    focus_window_skill,
    list_processes_skill,
    open_app_skill,
    run_command_skill,
)
from jarvis.skills.errors import SkillInputError
from jarvis.skills.skill import Skill, SkillInvocation, SkillOutput
from jarvis.tools.access import ToolAccess
from jarvis.tools.adapters.computer_backend import ComputerToolBackend
from jarvis.tools.errors import ToolInvalidInputError
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.router import ToolRouter
from tests.action_doubles import counting_monotonic

NOON = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def run(skill: Skill, backend: ComputerToolBackend, **parameters: object) -> SkillOutput:
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
    def test_risk_escalates_from_read_to_destructive(self) -> None:
        assert list_processes_skill().descriptor.risk is RiskLevel.NONE
        assert focus_window_skill().descriptor.risk is RiskLevel.LOW
        assert open_app_skill().descriptor.risk is RiskLevel.MEDIUM
        assert close_app_skill().descriptor.risk is RiskLevel.HIGH
        assert run_command_skill().descriptor.risk is RiskLevel.HIGH

    def test_destructive_skills_always_confirm(self) -> None:
        assert close_app_skill().descriptor.confirmation_requirement is (
            ConfirmationRequirement.ALWAYS
        )
        assert run_command_skill().descriptor.confirmation_requirement is (
            ConfirmationRequirement.ALWAYS
        )
        assert close_app_skill().descriptor.effects == frozenset({Effect.DESTRUCTIVE})
        assert run_command_skill().descriptor.effects == frozenset({Effect.DESTRUCTIVE})

    def test_read_only_listing_never_confirms(self) -> None:
        descriptor = list_processes_skill().descriptor

        assert descriptor.effects == frozenset({Effect.READ})
        assert descriptor.confirmation_requirement is ConfirmationRequirement.NEVER
        assert descriptor.idempotency is Idempotency.SAFE

    def test_every_skill_declares_exactly_the_computer_tool_it_uses(self) -> None:
        for skill in (
            list_processes_skill(),
            focus_window_skill(),
            open_app_skill(),
            close_app_skill(),
            run_command_skill(),
        ):
            assert skill.descriptor.required_tools
            assert all(item.startswith("computer:") for item in skill.descriptor.required_tools)
            assert len(skill.descriptor.required_tools) == 1


class TestListProcesses:
    def test_it_reports_without_parameters(self) -> None:
        backend = ComputerToolBackend(list_process_names=lambda: ["notepad.exe"])

        output = run(list_processes_skill(), backend)

        assert output.data["processes"] == ["notepad.exe"]
        assert output.summary


class TestFocusWindow:
    def test_a_found_window_is_reported(self) -> None:
        backend = ComputerToolBackend(focus_window=lambda application: True)

        output = run(focus_window_skill(), backend, application="notepad")

        assert output.data["focused"] is True

    def test_an_empty_application_is_refused_by_the_skill(self) -> None:
        backend = ComputerToolBackend(focus_window=lambda application: True)

        with pytest.raises(SkillInputError):
            run(focus_window_skill(), backend, application="   ")


class TestOpenApp:
    def test_an_allowlisted_name_is_launched(self) -> None:
        launched: list[Sequence[str]] = []
        backend = ComputerToolBackend(
            command_allowlist={"notepad": ("notepad.exe",)}, launch=launched.append
        )

        output = run(open_app_skill(), backend, name="notepad")

        assert launched == [("notepad.exe",)]
        assert output.data["name"] == "notepad"

    def test_a_non_allowlisted_name_never_reaches_launch(self) -> None:
        launched: list[Sequence[str]] = []
        backend = ComputerToolBackend(
            command_allowlist={"notepad": ("notepad.exe",)}, launch=launched.append
        )

        with pytest.raises(ToolInvalidInputError):
            run(open_app_skill(), backend, name="powershell")

        assert launched == []


class TestCloseApp:
    def test_terminated_processes_are_reported(self) -> None:
        backend = ComputerToolBackend(terminate_processes=lambda application: 3)

        output = run(close_app_skill(), backend, application="notepad")

        assert output.data["terminated_count"] == 3


class TestRunCommand:
    def test_an_allowlisted_command_is_run(self) -> None:
        def fake_run(
            argv: Sequence[str], timeout_seconds: float
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(list(argv), returncode=0, stdout="ok", stderr="")

        backend = ComputerToolBackend(command_allowlist={"dir": ("cmd", "/c", "dir")}, run=fake_run)

        output = run(run_command_skill(), backend, name="dir")

        assert output.data["returncode"] == 0
        assert output.data["stdout"] == "ok"
