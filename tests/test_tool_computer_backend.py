"""`ComputerToolBackend`: cinco Tools sobre processos, janelas e comandos.

Todas as operações nativas são injetadas — nenhum teste toca `psutil`,
`ctypes` ou `subprocess` de verdade, mesmo desenho de
`tests/test_context_computer_providers.py` (Fase 8.1). A barreira real de
segurança (allowlist de comandos) é o que a classe `TestCommandAllowlist`
prova: sem entrada na allowlist, `open_app`/`run_command` nunca chegam a
`launch`/`run`.
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis.tools.adapters.computer_backend import (
    CLOSE_APP,
    FOCUS_WINDOW,
    LIST_PROCESSES,
    OPEN_APP,
    RUN_COMMAND,
    ComputerToolBackend,
    load_command_allowlist,
)
from jarvis.tools.errors import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from jarvis.tools.tool import ToolCall, ToolResult


def call(tool_id: str, parameters: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_id=tool_id,
        parameters=parameters or {},  # type: ignore[arg-type]
        execution_id="exec-1",
        correlation_id="corr-1",
    )


def invoke(
    backend: ComputerToolBackend, tool_id: str, parameters: dict[str, object] | None = None
) -> ToolResult:
    return backend.invoke(call(tool_id, parameters), timeout_seconds=5.0)


class TestDiscovery:
    def test_it_exposes_the_five_expected_tools(self) -> None:
        found = {item.tool_id for item in ComputerToolBackend().discover()}

        assert found == {LIST_PROCESSES, FOCUS_WINDOW, OPEN_APP, CLOSE_APP, RUN_COMMAND}

    def test_an_unknown_tool_is_refused(self) -> None:
        with pytest.raises(ToolNotFoundError):
            invoke(ComputerToolBackend(), "computer:inexistente")


class TestListProcesses:
    def test_it_deduplicates_and_sorts(self) -> None:
        backend = ComputerToolBackend(
            list_process_names=lambda: ["chrome.exe", "notepad.exe", "chrome.exe"]
        )

        result = invoke(backend, LIST_PROCESSES)

        assert result.data["processes"] == ["chrome.exe", "notepad.exe"]
        assert result.data["count"] == 2


class TestFocusWindow:
    def test_a_found_window_is_reported_focused(self) -> None:
        backend = ComputerToolBackend(focus_window=lambda application: True)

        result = invoke(backend, FOCUS_WINDOW, {"application": "notepad"})

        assert result.data["focused"] is True
        assert "notepad" in result.message

    def test_a_missing_window_is_a_structured_error(self) -> None:
        backend = ComputerToolBackend(focus_window=lambda application: False)

        with pytest.raises(ToolExecutionError, match="nenhuma janela"):
            invoke(backend, FOCUS_WINDOW, {"application": "inexistente"})

    def test_a_non_text_application_is_refused(self) -> None:
        backend = ComputerToolBackend(focus_window=lambda application: True)

        with pytest.raises(ToolInvalidInputError):
            invoke(backend, FOCUS_WINDOW, {"application": 123})


class TestCommandAllowlist:
    def test_open_app_refuses_a_name_outside_the_allowlist(self) -> None:
        launched: list[Sequence[str]] = []
        backend = ComputerToolBackend(
            command_allowlist={"notepad": ("notepad.exe",)},
            launch=launched.append,
        )

        with pytest.raises(ToolInvalidInputError, match="allowlist"):
            invoke(backend, OPEN_APP, {"name": "powershell"})

        assert launched == []

    def test_open_app_launches_the_allowlisted_argv(self) -> None:
        launched: list[Sequence[str]] = []
        backend = ComputerToolBackend(
            command_allowlist={"notepad": ("notepad.exe",)},
            launch=launched.append,
        )

        result = invoke(backend, OPEN_APP, {"name": "notepad"})

        assert launched == [("notepad.exe",)]
        assert result.data["name"] == "notepad"

    def test_run_command_refuses_a_name_outside_the_allowlist(self) -> None:
        backend = ComputerToolBackend(command_allowlist={"dir": ("cmd", "/c", "dir")})

        with pytest.raises(ToolInvalidInputError, match="allowlist"):
            invoke(backend, RUN_COMMAND, {"name": "format"})

    def test_run_command_runs_the_allowlisted_argv(self) -> None:
        seen: list[Sequence[str]] = []

        def fake_run(
            argv: Sequence[str], timeout_seconds: float
        ) -> subprocess.CompletedProcess[str]:
            seen.append(argv)
            return subprocess.CompletedProcess(list(argv), returncode=0, stdout="ok", stderr="")

        backend = ComputerToolBackend(command_allowlist={"dir": ("cmd", "/c", "dir")}, run=fake_run)

        result = invoke(backend, RUN_COMMAND, {"name": "dir"})

        assert seen == [("cmd", "/c", "dir")]
        assert result.data["returncode"] == 0
        assert result.data["stdout"] == "ok"

    def test_run_command_timeout_is_a_structured_error(self) -> None:
        def fake_run(
            argv: Sequence[str], timeout_seconds: float
        ) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=list(argv), timeout=timeout_seconds)

        backend = ComputerToolBackend(command_allowlist={"dir": ("dir",)}, run=fake_run)

        with pytest.raises(ToolTimeoutError):
            invoke(backend, RUN_COMMAND, {"name": "dir"})


class TestCloseApp:
    def test_terminating_at_least_one_process_reports_the_count(self) -> None:
        backend = ComputerToolBackend(terminate_processes=lambda application: 2)

        result = invoke(backend, CLOSE_APP, {"application": "notepad"})

        assert result.data["terminated_count"] == 2

    def test_terminating_nothing_is_a_structured_error(self) -> None:
        backend = ComputerToolBackend(terminate_processes=lambda application: 0)

        with pytest.raises(ToolExecutionError, match="nenhum processo"):
            invoke(backend, CLOSE_APP, {"application": "inexistente"})


class TestLoadCommandAllowlist:
    def test_a_missing_file_is_an_empty_allowlist(self, tmp_path: Path) -> None:
        assert load_command_allowlist(tmp_path / "ausente.json") == {}

    def test_a_valid_file_is_parsed_into_argv_tuples(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text(
            '{"notepad": ["notepad.exe"], "dir": ["cmd", "/c", "dir"]}', encoding="utf-8"
        )

        allowlist = load_command_allowlist(path)

        assert allowlist == {"notepad": ("notepad.exe",), "dir": ("cmd", "/c", "dir")}

    def test_invalid_json_is_a_configuration_error(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(ToolConfigurationError):
            load_command_allowlist(path)

    def test_a_non_object_document_is_a_configuration_error(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        with pytest.raises(ToolConfigurationError):
            load_command_allowlist(path)

    def test_an_empty_argv_is_a_configuration_error(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text('{"notepad": []}', encoding="utf-8")

        with pytest.raises(ToolConfigurationError, match="não vazia"):
            load_command_allowlist(path)

    def test_a_shell_string_instead_of_argv_is_a_configuration_error(self, tmp_path: Path) -> None:
        path = tmp_path / "allowlist.json"
        path.write_text('{"notepad": "notepad.exe /A"}', encoding="utf-8")

        with pytest.raises(ToolConfigurationError):
            load_command_allowlist(path)
