"""Regra de dependência de `jarvis.proactivity` (Fase 7.1/7.2/7.6/9.3).

Mesma técnica AST de `test_action_architecture.py`. A regra central: este pacote
nunca conhece `jarvis.agent` — ele decide *se* vale raciocinar, nunca *o que*
fazer, e por isso não tem, e não pode ganhar, um caminho até o LLM. Os pontos
que precisam de `jarvis.agent`/`jarvis.execution` de verdade (rodar o Agent
Runtime, submeter a `ActionExecutor`) vivem no composition root, que recebe
callbacks injetados em vez de o pacote conhecer essas camadas diretamente.

Exceção pontual desde a Fase 9.3 (ADR-0032): `jarvis.memory` sai de
`FORBIDDEN_ALWAYS` e vira `FORBIDDEN_IN_CORE` — mesmo desenho de
`test_memory_architecture.py` para `context_bridge.py`. O Core continua sem
conhecer `jarvis.memory`; só `proactivity/adapters/memory_bridge.py` pode,
e um teste próprio garante que nenhum outro adapter ganha essa exceção de
carona.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
PACKAGE_ROOT = SOURCE_ROOT / "proactivity"

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
    "jarvis.memory",
}

FORBIDDEN_ALWAYS = {
    "jarvis.agent",
    "jarvis.policy",
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.voice",
    "jarvis.interface",
    "jarvis.notify",
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
    assert _core_modules(), "nenhum módulo de Core em jarvis.proactivity"


@pytest.mark.parametrize("module", _core_modules(), ids=_relative)
def test_core_does_not_touch_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, proibido no Core de proactivity"
            )
        assert "adapters" not in imported, (
            f"{_relative(module)} importa {imported}: Core não conhece adapters"
        )


@pytest.mark.parametrize("module", _all_modules(), ids=_relative)
def test_never_depends_on_agent_or_downstream_capability_layers(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_ALWAYS:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}: proactivity nunca conhece "
                "o Agent Runtime nem as camadas de capacidade"
            )


def test_only_memory_bridge_is_allowed_to_import_memory() -> None:
    """A exceção do ADR-0032 é cirúrgica: nenhum outro adapter de proactivity
    ganha carona nela — `rules_config.py` continua livre de `jarvis.memory`."""
    offenders = [
        _relative(module)
        for module in _adapter_modules()
        if module.name != "memory_bridge.py"
        and any(_violates(name, "jarvis.memory") for name in _imported_names(module))
    ]
    assert offenders == []


def test_only_adapters_touch_the_filesystem() -> None:
    offenders = [
        f"{_relative(module)}:{name}"
        for module in _core_modules()
        for name in _imported_names(module)
        if name in ("pathlib", "json", "os", "shutil")
    ]
    assert offenders == []
