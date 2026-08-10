"""Verifica a regra de dependência do ADR-0001 sobre o pacote `jarvis.context`.

Mesma técnica de `test_events_architecture.py`: a fronteira real é a que a análise
estática de imports checa, não uma separação física em `domain/`/`infrastructure/`
— que continua deliberadamente inexistente.

`jarvis.events` **é** permitido no Core de contexto: contracts §3.2 lista o Event
System como dependência legítima do Context Engine, na posição de consumidor e
leitor. `jarvis.events.adapters`, não.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
CONTEXT_ROOT = SOURCE_ROOT / "context"
ADAPTERS_ROOT = CONTEXT_ROOT / "adapters"

FORBIDDEN_IN_CORE = {
    "sqlite3",
    "json",
    "pathlib",
    "jarvis.context.adapters",
    "jarvis.events.adapters",
    "jarvis.cli",
    "jarvis.config",
}
ALLOWED_JARVIS_IMPORTS_IN_CONTEXT = {"jarvis.context", "jarvis.errors", "jarvis.events"}


def _core_modules() -> list[Path]:
    return sorted(path for path in CONTEXT_ROOT.glob("*.py"))


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
    # Impede que o teste passe por vacuidade se o pacote for reorganizado.
    assert {path.name for path in _core_modules()} >= {
        "observation.py",
        "model.py",
        "freshness.py",
        "ports.py",
        "projection.py",
        "aggregator.py",
        "snapshot.py",
        "consumer.py",
        "engine.py",
    }


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido no Core do Context Engine"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_allowed_components(module: Path) -> None:
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(
            _violates(imported, allowed) or imported == allowed
            for allowed in ALLOWED_JARVIS_IMPORTS_IN_CONTEXT
        ), f"{module.name} importa {imported}, fora das dependências permitidas"


def test_adapters_may_depend_on_core() -> None:
    # A direção oposta é obrigatória: adapters conhecem os ports que implementam.
    imports = {
        name
        for module in ADAPTERS_ROOT.glob("*.py")
        for name in _imported_names(module)
        if name.startswith("jarvis")
    }

    assert any(name.startswith("jarvis.context") for name in imports)


def test_only_the_composition_root_wires_context_adapters() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.context.adapters") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_event_system_still_does_not_know_the_context_engine() -> None:
    """A dependência é de mão única: contracts §3.1 proíbe o caminho inverso."""
    offenders = [
        module.name
        for module in (SOURCE_ROOT / "events").rglob("*.py")
        if any(_violates(name, "jarvis.context") for name in _imported_names(module))
    ]

    assert offenders == []
