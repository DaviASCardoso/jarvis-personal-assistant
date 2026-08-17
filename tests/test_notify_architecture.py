"""Regra de dependência de `jarvis.notify` (Fase 7.3).

Mesma técnica AST de `test_proactivity_architecture.py`. O Core (`manager.py`,
`notification.py`, `ports.py`, `errors.py`) não conhece `jarvis.voice` — só o
adapter de voz conhece, porque é ele quem fala. Nenhum dos dois conhece
`jarvis.agent`, `jarvis.execution`, `jarvis.memory`, `jarvis.skills`,
`jarvis.tools`, `jarvis.policy` nem `jarvis.events`
(`architecture-contracts.md §3.10`: só `Notification` e ports de canal).
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PACKAGE_ROOT = SOURCE_ROOT / "notify"

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
    "sys",
    "jarvis.cli",
    "jarvis.config",
    "jarvis.voice",
}

FORBIDDEN_ALWAYS = {
    "jarvis.agent",
    "jarvis.execution",
    "jarvis.memory",
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.policy",
    "jarvis.interface",
    "jarvis.events",
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
    assert _core_modules(), "nenhum módulo de Core em jarvis.notify"
    assert _adapter_modules(), "nenhum adapter em jarvis.notify"


@pytest.mark.parametrize("module", _core_modules(), ids=_relative)
def test_core_does_not_touch_infrastructure_or_voice(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, proibido no Core de notify"
            )
        assert "adapters" not in imported, (
            f"{_relative(module)} importa {imported}: Core não conhece adapters"
        )


@pytest.mark.parametrize("module", _all_modules(), ids=_relative)
def test_never_depends_on_capability_layers(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_ALWAYS:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}: notify nunca conhece as camadas "
                "de capacidade"
            )
