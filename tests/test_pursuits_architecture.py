"""Regra de dependência de `jarvis.pursuits` (Fase 10.5).

Mais estrito que `jarvis.tasks`: `PursuitState` guarda `last_action_result`/
`previous_proposal` como documentos JSON soltos, de propósito — é isso que
evita qualquer import de `jarvis.agent`/`jarvis.execution`. `pursuits` é um
armazém de checkpoint genérico; só `cli._agent_pursue` sabe o formato exato
do que guarda ali.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PACKAGE_ROOT = SOURCE_ROOT / "pursuits"

FORBIDDEN_IN_CORE = {
    "sqlite3",
    "subprocess",
    "socket",
    "ssl",
    "urllib",
    "http",
    "pathlib",
    "shutil",
    "platform",
    "threading",
    "queue",
    "jarvis.cli",
    "jarvis.config",
}

FORBIDDEN_ALWAYS = {
    "jarvis.agent",
    "jarvis.execution",
    "jarvis.memory",
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.policy",
    "jarvis.interface",
    "jarvis.voice",
    "jarvis.notify",
    "jarvis.proactivity",
    "jarvis.decisions",
    "jarvis.tasks",
}


def _core_modules() -> list[Path]:
    return sorted(path for path in PACKAGE_ROOT.rglob("*.py") if "adapters" not in path.parts)


def _adapter_modules() -> list[Path]:
    root = PACKAGE_ROOT / "adapters"
    return sorted(root.glob("*.py")) if root.exists() else []


def _all_modules() -> list[Path]:
    return [*_core_modules(), *_adapter_modules()]


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


def _relative(module: Path) -> str:
    return module.relative_to(SOURCE_ROOT).as_posix()


def test_there_are_modules_to_check() -> None:
    assert _core_modules(), "nenhum módulo de Core em jarvis.pursuits"
    assert _adapter_modules(), "nenhum adapter em jarvis.pursuits"


@pytest.mark.parametrize("module", _core_modules(), ids=_relative)
def test_core_does_not_touch_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, proibido no Core de pursuits"
            )
        assert "adapters" not in imported, (
            f"{_relative(module)} importa {imported}: Core não conhece adapters"
        )


@pytest.mark.parametrize("module", _all_modules(), ids=_relative)
def test_never_depends_on_agent_execution_or_downstream_layers(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_ALWAYS:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}: pursuits é um armazém de "
                "checkpoint genérico, nunca conhece o Agent Runtime nem a cadeia de execução"
            )
