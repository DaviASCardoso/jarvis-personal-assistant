"""Regra de dependência do pacote `jarvis.interface`.

O documento da fase é explícito: "a interface nunca acessa diretamente SQLite,
MCP, Skills ou LLM". Este arquivo é o que transforma essa frase em propriedade
verificável — a interface importa **tipos de domínio** e nada mais.

A distinção que a lista de permitidos carrega: `jarvis.execution.model` é dado
(`PendingAction`), enquanto `jarvis.execution.orchestrator` é o serviço que
executa. O painel pode conhecer o primeiro e não pode conhecer o segundo.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
INTERFACE_ROOT = SOURCE_ROOT / "interface"
ADAPTERS_ROOT = INTERFACE_ROOT / "adapters"

#: Só módulos de **modelo**. Nenhum serviço, nenhum registry, nenhum repositório.
ALLOWED_JARVIS_IMPORTS = {
    "jarvis.errors",
    "jarvis.interface",
    "jarvis.events.event",
    "jarvis.context.model",
    "jarvis.context.observation",
    "jarvis.memory.memory",
    "jarvis.memory.retrieval",
    "jarvis.execution.model",
    "jarvis.voice.session",
    "jarvis.decisions.query",
    "jarvis.decisions.record",
}

FORBIDDEN_EVERYWHERE = {
    "jarvis.agent",
    "jarvis.policy",
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.audit",
    "jarvis.execution.orchestrator",
    "jarvis.execution.consumer",
    "jarvis.execution.adapters",
    "jarvis.events.adapters",
    "jarvis.context.adapters",
    "jarvis.memory.adapters",
    "jarvis.voice.adapters",
    "jarvis.voice.loop",
    "jarvis.cli",
    "jarvis.config",
    "sqlite3",
}

FORBIDDEN_IN_CORE = {"urllib", "http", "socket", "ssl", "subprocess", "sqlite3"}


def _all_modules(root: Path) -> list[Path]:
    return sorted(root.glob("*.py"))


def _core_modules() -> list[Path]:
    return _all_modules(INTERFACE_ROOT)


def _imported_names(module: Path) -> Iterator[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def _violates(imported: str, forbidden: str) -> bool:
    return imported == forbidden or imported.startswith(f"{forbidden}.")


def test_there_are_core_modules_to_check() -> None:
    assert {path.name for path in _core_modules()} >= {
        "errors.py",
        "viewmodel.py",
        "service.py",
        "live.py",
    }


@pytest.mark.parametrize(
    "module",
    [*_core_modules(), *_all_modules(ADAPTERS_ROOT)],
    ids=lambda path: path.name,
)
def test_the_panel_never_reaches_a_service_a_database_or_the_llm(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_EVERYWHERE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}: a interface só conhece tipos de domínio"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_allowed_models(module: Path) -> None:
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(_violates(imported, allowed) for allowed in ALLOWED_JARVIS_IMPORTS), (
            f"{module.name} importa {imported}, fora das dependências permitidas"
        )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_only_the_adapter_speaks_http(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}: servir é assunto do adapter"
            )


def test_the_panel_has_no_write_route() -> None:
    """Um painel que executa seria um segundo caminho até a Tool, sem o cuidado
    que o CLI tem. As únicas definições de método de escrita são o handler único
    que responde 405."""
    module = ADAPTERS_ROOT / "http_panel.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    handlers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("do_")
    }
    written = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.startswith("do_")
    }

    assert handlers == {"do_GET"}
    assert written == {"do_POST", "do_PUT", "do_DELETE", "do_PATCH"}


def test_only_the_composition_root_wires_the_panel() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.interface.adapters") for name in _imported_names(module))
    ]

    assert offenders == []


def test_no_component_knows_the_panel_exists() -> None:
    """Mão única: a interface lê o Core, o Core não sabe que ela existe."""
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for component in (
            "events",
            "context",
            "memory",
            "agent",
            "policy",
            "skills",
            "tools",
            "execution",
            "voice",
        )
        for module in (SOURCE_ROOT / component).rglob("*.py")
        if any(_violates(name, "jarvis.interface") for name in _imported_names(module))
    ]

    assert offenders == []
