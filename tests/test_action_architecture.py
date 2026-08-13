"""Regra de dependência da camada de ação: `policy`, `skills`, `tools`, `execution`.

Mesma técnica AST dos quatro componentes anteriores, com um acréscimo que só faz
sentido nesta fase: além de verificar *quem importa quem*, este arquivo verifica
**quem constrói o quê**. `PolicyApproval` e `ToolAccess` são os dois objetos que
conferem poder; que só o emissor legítimo os construa é o que torna a fronteira
estrutural em vez de disciplinar.

O grafo que os testes fixam:

```text
policy      →  (nada de jarvis além de jarvis.errors)
skills      →  policy.vocabulary, tools, events.event
tools       →  events.event, jarvis.errors
execution   →  policy, skills, tools, events
agent       ─X→  policy, skills, tools, execution, mcp
```
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"

ACTION_PACKAGES = ("policy", "skills", "tools", "execution")

# O que nenhum módulo de Core da camada de ação pode importar. `pathlib`,
# `subprocess` e `platform` moram exclusivamente sob `adapters/`.
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

# Por pacote, o que ele pode importar de dentro de `jarvis`.
ALLOWED_JARVIS_IMPORTS: dict[str, set[str]] = {
    "policy": {"jarvis.errors", "jarvis.policy", "jarvis.tools.tool"},
    "skills": {
        "jarvis.errors",
        "jarvis.skills",
        "jarvis.tools",
        "jarvis.policy.vocabulary",
        "jarvis.events.event",
    },
    "tools": {"jarvis.errors", "jarvis.tools", "jarvis.events.event", "jarvis.audit"},
    "execution": {
        "jarvis.errors",
        "jarvis.execution",
        "jarvis.policy",
        "jarvis.skills",
        "jarvis.tools",
        "jarvis.events",
        "jarvis.audit",
    },
}

FORBIDDEN_SDKS = {
    "mcp",
    "fastmcp",
    "httpx",
    "requests",
    "anyio",
    "openai",
    "anthropic",
    "google.generativeai",
}


def _core_modules(package: str) -> list[Path]:
    root = SOURCE_ROOT / package
    return sorted(path for path in root.rglob("*.py") if "adapters" not in path.parts)


def _adapter_modules(package: str) -> list[Path]:
    root = SOURCE_ROOT / package / "adapters"
    return sorted(root.glob("*.py")) if root.exists() else []


def _all_action_modules() -> list[Path]:
    return [
        path
        for package in ACTION_PACKAGES
        for path in (*_core_modules(package), *_adapter_modules(package))
    ]


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


def _constructs(module: Path, name: str) -> bool:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
        for node in ast.walk(tree)
    )


def _relative(module: Path) -> str:
    return module.relative_to(SOURCE_ROOT).as_posix()


def test_there_are_modules_to_check() -> None:
    """Impede que a suíte inteira passe por vacuidade se algo for reorganizado."""
    for package in ACTION_PACKAGES:
        assert _core_modules(package), f"nenhum módulo de Core em {package}"
    assert len(_all_action_modules()) >= 25


@pytest.mark.parametrize(
    "module",
    [path for package in ACTION_PACKAGES for path in _core_modules(package)],
    ids=_relative,
)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, proibido no Core da camada de ação"
            )
        assert "adapters" not in imported, (
            f"{_relative(module)} importa {imported}: Core não conhece adapters"
        )


@pytest.mark.parametrize(
    "package_and_module",
    [(package, path) for package in ACTION_PACKAGES for path in _core_modules(package)],
    ids=lambda pair: _relative(pair[1]),
)
def test_each_package_only_imports_what_it_may(package_and_module: tuple[str, Path]) -> None:
    package, module = package_and_module
    allowed = ALLOWED_JARVIS_IMPORTS[package]
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(_violates(imported, item) for item in allowed), (
            f"{_relative(module)} importa {imported}, fora das dependências permitidas de {package}"
        )


def test_skills_never_reach_the_policy_engine() -> None:
    """Uma Skill declara risco; ela não pode chegar a quem decide sobre ele."""
    offenders = [
        f"{_relative(module)}:{name}"
        for module in _core_modules("skills")
        for name in _imported_names(module)
        if _violates(name, "jarvis.policy") and not _violates(name, "jarvis.policy.vocabulary")
    ]

    assert offenders == []


def test_policy_knows_nothing_about_skills_or_tools() -> None:
    """Uma autoridade que dependesse de quem ela autoriza não seria independente."""
    offenders = [
        f"{_relative(module)}:{name}"
        for module in _core_modules("policy")
        for name in _imported_names(module)
        # `tools.tool` entra só pelo alias `ToolId`, que é um tipo de texto.
        if (_violates(name, "jarvis.skills") or _violates(name, "jarvis.tools"))
        and not _violates(name, "jarvis.tools.tool")
    ]

    assert offenders == []


def test_the_tool_router_never_knows_policy() -> None:
    """O router assume que a chamada já foi autorizada; ele não decide nada."""
    offenders = [
        f"{_relative(module)}:{name}"
        for module in (*_core_modules("tools"), *_adapter_modules("tools"))
        for name in _imported_names(module)
        if _violates(name, "jarvis.policy") or _violates(name, "jarvis.skills")
    ]

    assert offenders == []


def test_only_the_policy_engine_builds_an_approval() -> None:
    """Se qualquer módulo pudesse emitir `PolicyApproval`, o ledger seria decorativo."""
    offenders = [
        _relative(module)
        for module in SOURCE_ROOT.rglob("*.py")
        if module.name not in ("engine.py", "verdict.py") and _constructs(module, "PolicyApproval")
    ]

    assert offenders == []


def test_only_execution_builds_tool_access() -> None:
    """`ToolAccess` é o que uma Skill segura; construí-lo é conceder privilégio."""
    allowed = {"execution/orchestrator.py", "tools/access.py"}
    offenders = [
        _relative(module)
        for module in SOURCE_ROOT.rglob("*.py")
        if _relative(module) not in allowed and _constructs(module, "ToolAccess")
    ]

    assert offenders == []


@pytest.mark.parametrize("module", _all_action_modules(), ids=_relative)
def test_no_module_imports_an_sdk(module: Path) -> None:
    """Nem o Core nem os adapters: MCP é falado com a stdlib (ADR-0015)."""
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_SDKS:
            assert not _violates(imported, forbidden), (
                f"{_relative(module)} importa {imported}, um SDK proibido"
            )


def test_only_adapters_touch_processes_and_the_filesystem() -> None:
    offenders = [
        f"{_relative(module)}:{name}"
        for package in ACTION_PACKAGES
        for module in _core_modules(package)
        for name in _imported_names(module)
        if name in ("subprocess", "pathlib", "platform", "os", "shutil")
    ]

    assert offenders == []


def test_only_the_composition_root_wires_adapters() -> None:
    offenders = [
        _relative(module)
        for module in SOURCE_ROOT.rglob("*.py")
        if module.name != "cli.py"
        and "adapters" not in module.parts
        and any(
            _violates(name, f"jarvis.{package}.adapters")
            for package in ACTION_PACKAGES
            for name in _imported_names(module)
        )
    ]

    assert offenders == []


def test_the_earlier_components_do_not_know_the_action_layer() -> None:
    """Mão única: a camada de ação conhece Event/Context/Memory, nunca o contrário.

    E o Agent Runtime não conhece nenhum dos quatro — é o ADR-0003 em forma de
    teste, agora que os pacotes existem de verdade.
    """
    offenders = [
        f"{_relative(module)}:{name}"
        for component in ("events", "context", "memory", "agent")
        for module in (SOURCE_ROOT / component).rglob("*.py")
        for name in _imported_names(module)
        if any(_violates(name, f"jarvis.{package}") for package in ACTION_PACKAGES)
    ]

    assert offenders == []


def test_the_core_never_reads_configuration_by_itself() -> None:
    """Contracts §12: configuração é carregada uma vez, na composition root."""
    offenders = [
        _relative(module)
        for module in _all_action_modules()
        if any(_violates(name, "jarvis.config") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_audit_port_is_a_leaf_shared_by_components_that_do_not_know_each_other() -> None:
    """`jarvis.audit` existe justamente por não pertencer a nenhum dos três."""
    for name in _imported_names(SOURCE_ROOT / "audit.py"):
        if name.startswith("jarvis"):
            assert _violates(name, "jarvis.events.event"), (
                f"jarvis/audit.py importa {name}; ele precisa continuar folha"
            )
