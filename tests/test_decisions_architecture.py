"""Regra de dependência de `jarvis.decisions` (Fase 7.4).

A regra central: este pacote nunca conhece `jarvis.agent`. `decision_event`
recebe primitivos (`str`/`float`/`datetime`), nunca `Decision`/`AgentTurn` —
é essa escolha, não uma convenção de import, que torna a dependência
estruturalmente impossível.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PACKAGE_ROOT = SOURCE_ROOT / "decisions"

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
}


def _modules() -> list[Path]:
    return sorted(PACKAGE_ROOT.glob("*.py"))


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
    assert _modules(), "nenhum módulo em jarvis.decisions"


@pytest.mark.parametrize("module", _modules(), ids=_relative)
def test_does_not_touch_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, proibido em jarvis.decisions"
            )


@pytest.mark.parametrize("module", _modules(), ids=_relative)
def test_never_depends_on_other_capability_layers(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_ALWAYS:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}: decisions nunca conhece as "
                "camadas de capacidade"
            )
