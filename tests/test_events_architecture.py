"""Verifica a regra de dependência do ADR-0001 sobre o código que existe hoje.

A separação física em `domain/`/`application/`/`infrastructure/` foi deliberadamente
não criada (ADR-0001, "Alternativas consideradas"). A fronteira real é a que este
teste checa: os módulos de Core de `jarvis.events` não podem importar
`jarvis.events.adapters` nem qualquer tecnologia concreta de persistência.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
EVENTS_ROOT = SOURCE_ROOT / "events"
ADAPTERS_ROOT = EVENTS_ROOT / "adapters"

FORBIDDEN_IN_CORE = {"sqlite3", "json", "jarvis.events.adapters", "jarvis.cli", "jarvis.config"}
ALLOWED_JARVIS_IMPORTS_IN_EVENTS = {"jarvis.events", "jarvis.errors"}


def _core_modules() -> list[Path]:
    return sorted(path for path in EVENTS_ROOT.glob("*.py"))


def _imported_names(module: Path) -> Iterator[str]:
    """Nomes totalmente qualificados importados por um módulo."""
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
    # Impede que o teste passe por vacuidade se o pacote for reorganizado.
    assert {path.name for path in _core_modules()} >= {
        "event.py",
        "ports.py",
        "bus.py",
        "publisher.py",
    }


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido no Core do Event System"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_its_own_component(module: Path) -> None:
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(
            _violates(imported, allowed) or imported == allowed
            for allowed in ALLOWED_JARVIS_IMPORTS_IN_EVENTS
        ), f"{module.name} importa {imported}, fora do Event System"


def test_adapters_may_depend_on_core() -> None:
    # A direção oposta é obrigatória: adapters conhecem os ports que implementam.
    imports = {
        name
        for module in ADAPTERS_ROOT.glob("*.py")
        for name in _imported_names(module)
        if name.startswith("jarvis")
    }

    assert any(name.startswith("jarvis.events.ports") for name in imports)


def test_only_the_composition_root_wires_adapters() -> None:
    """Fora dos próprios adapters, só `cli.py` pode conhecer implementações concretas."""
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.events.adapters") for name in _imported_names(module))
    ]

    assert offenders == []
