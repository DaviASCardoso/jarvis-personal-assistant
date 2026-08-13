"""O backend local, e a raiz allowlistada que ele impõe sozinho.

A barreira de caminho vive **aqui**, não na política. São independentes de
propósito: mesmo que uma regra de política seja afrouxada por engano, um caminho
fora do workspace continua recusado.
"""

from pathlib import Path

import pytest

from jarvis.tools.adapters.local_backend import (
    LIST_DIR,
    READ_TEXT,
    SYSTEM_INFO,
    WRITE_TEXT,
    LocalToolBackend,
)
from jarvis.tools.errors import ToolExecutionError, ToolInvalidInputError, ToolNotFoundError
from jarvis.tools.tool import ToolCall, ToolResult


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def call(tool_id: str, parameters: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        tool_id=tool_id,
        parameters=parameters or {},  # type: ignore[arg-type]
        execution_id="exec-1",
        correlation_id="corr-1",
    )


def invoke(
    backend: LocalToolBackend, tool_id: str, parameters: dict[str, object] | None = None
) -> ToolResult:
    return backend.invoke(call(tool_id, parameters), timeout_seconds=5.0)


class TestDiscovery:
    def test_it_exposes_the_four_expected_tools(self, workspace: Path) -> None:
        found = {item.tool_id for item in LocalToolBackend(root=workspace).discover()}

        assert found == {READ_TEXT, WRITE_TEXT, LIST_DIR, SYSTEM_INFO}

    def test_an_unknown_tool_is_refused(self, workspace: Path) -> None:
        with pytest.raises(ToolNotFoundError):
            invoke(LocalToolBackend(root=workspace), "local:inexistente")


class TestReadAndWrite:
    def test_a_written_file_can_be_read_back(self, workspace: Path) -> None:
        backend = LocalToolBackend(root=workspace)

        invoke(backend, WRITE_TEXT, {"path": "nota.txt", "content": "olá"})
        result = invoke(backend, READ_TEXT, {"path": "nota.txt"})

        assert result.data["content"] == "olá"
        assert result.data["characters"] == 3

    def test_append_adds_instead_of_replacing(self, workspace: Path) -> None:
        backend = LocalToolBackend(root=workspace)

        invoke(backend, WRITE_TEXT, {"path": "log.txt", "content": "a"})
        invoke(backend, WRITE_TEXT, {"path": "log.txt", "content": "b", "append": True})

        assert (workspace / "log.txt").read_text(encoding="utf-8") == "ab"

    def test_writing_creates_intermediate_directories(self, workspace: Path) -> None:
        invoke(
            LocalToolBackend(root=workspace),
            WRITE_TEXT,
            {"path": "a/b/c.txt", "content": "x"},
        )

        assert (workspace / "a" / "b" / "c.txt").exists()

    def test_a_missing_file_is_a_structured_error(self, workspace: Path) -> None:
        with pytest.raises(ToolExecutionError, match="não encontrado"):
            invoke(LocalToolBackend(root=workspace), READ_TEXT, {"path": "ausente.txt"})

    def test_a_binary_file_is_a_structured_error(self, workspace: Path) -> None:
        (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00")

        with pytest.raises(ToolExecutionError, match="UTF-8"):
            invoke(LocalToolBackend(root=workspace), READ_TEXT, {"path": "bin.dat"})

    def test_the_message_never_carries_the_content(self, workspace: Path) -> None:
        backend = LocalToolBackend(root=workspace)
        secret = "consulta com a Dra. Marina"
        invoke(backend, WRITE_TEXT, {"path": "diario.txt", "content": secret})

        result = invoke(backend, READ_TEXT, {"path": "diario.txt"})

        assert secret not in result.message
        assert result.data["content"] == secret


class TestListing:
    def test_directories_are_marked(self, workspace: Path) -> None:
        (workspace / "sub").mkdir()
        (workspace / "a.txt").write_text("x", encoding="utf-8")

        result = invoke(LocalToolBackend(root=workspace), LIST_DIR, {"path": "."})

        assert result.data["entries"] == ["a.txt", "sub/"]

    def test_a_missing_directory_is_a_structured_error(self, workspace: Path) -> None:
        with pytest.raises(ToolExecutionError):
            invoke(LocalToolBackend(root=workspace), LIST_DIR, {"path": "ausente"})


class TestPathBoundary:
    @pytest.mark.parametrize("path", ["../fora.txt", "a/../../fora.txt", "sub/../../x"])
    def test_traversal_is_refused(self, workspace: Path, path: str) -> None:
        with pytest.raises(ToolInvalidInputError, match="raiz permitida"):
            invoke(LocalToolBackend(root=workspace), READ_TEXT, {"path": path})

    @pytest.mark.parametrize("path", ["/etc/passwd", "C:/Windows/win.ini", "\\\\servidor\\share"])
    def test_absolute_paths_are_refused(self, workspace: Path, path: str) -> None:
        with pytest.raises(ToolInvalidInputError, match="relativo"):
            invoke(LocalToolBackend(root=workspace), READ_TEXT, {"path": path})

    def test_the_refusal_never_echoes_the_path(self, workspace: Path) -> None:
        with pytest.raises(ToolInvalidInputError) as error:
            invoke(
                LocalToolBackend(root=workspace),
                READ_TEXT,
                {"path": "../segredo-do-usuario.txt"},
            )

        assert "segredo-do-usuario" not in str(error.value)

    def test_writing_outside_the_root_never_touches_the_disk(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "invadido.txt"

        with pytest.raises(ToolInvalidInputError):
            invoke(
                LocalToolBackend(root=workspace),
                WRITE_TEXT,
                {"path": "../invadido.txt", "content": "x"},
            )

        assert not target.exists()


class TestSystemInfo:
    def test_it_reports_the_basics(self, workspace: Path) -> None:
        result = invoke(LocalToolBackend(root=workspace), SYSTEM_INFO)

        assert isinstance(result.data["os"], str)
        assert isinstance(result.data["python"], str)
        assert result.data["workspace_exists"] is True

    def test_it_never_reports_the_environment(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O resultado pode acabar num prompt enviado para a nuvem."""
        monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "chave-secreta-do-usuario")

        result = invoke(LocalToolBackend(root=workspace), SYSTEM_INFO)

        rendered = f"{result.data} {result.message}"
        assert "chave-secreta-do-usuario" not in rendered
        assert "USERPROFILE" not in rendered

    def test_a_missing_workspace_is_reported_not_created(self, tmp_path: Path) -> None:
        absent = tmp_path / "nao-existe"

        result = invoke(LocalToolBackend(root=absent), SYSTEM_INFO)

        assert result.data["workspace_exists"] is False
        assert not absent.exists()
