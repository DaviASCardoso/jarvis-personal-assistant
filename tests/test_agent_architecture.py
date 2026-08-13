"""Regra de dependência e fronteira de segurança do pacote `jarvis.agent`.

Mesma técnica AST dos três componentes anteriores, com um acréscimo que não
existe nos outros: além de verificar a direção das dependências, este arquivo
verifica **a ausência de caminho até a execução**.

O ADR-0003 diz que o Agent Runtime nunca executa ações. Um comentário não
sustenta isso; os testes de `test_no_path_from_the_agent_to_execution` sim. Até a
Fase 4 esses nomes eram apenas reservados; desde a Fase 5 `jarvis.policy`,
`jarvis.skills`, `jarvis.tools` e `jarvis.execution` existem de verdade, e a
proibição passou de precaução a fronteira em vigor.

Diferença deliberada em relação ao Memory System: `jarvis.context`,
`jarvis.memory` e `jarvis.events` **são** permitidos no Core do agente.
Contracts §3.4 lista `Event`, `Context`, `Memory` e os serviços de aplicação de
Memory/Context entre as dependências legítimas do Agent Runtime — é o único
componente que conhece os três ao mesmo tempo, e é por isso que ele existe.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
AGENT_ROOT = SOURCE_ROOT / "agent"
ADAPTERS_ROOT = AGENT_ROOT / "adapters"

# `json` é permitido **só** onde o ADR-0002 exige interpretação no Core: JSON é
# formato genérico de intercâmbio, não formato de wire de vendor. Nos demais
# módulos ele continuaria significando serialização, que é de adapter.
JSON_ALLOWED_IN = {"decision.py", "prompt.py"}

FORBIDDEN_IN_CORE = {
    "sqlite3",
    "pathlib",
    "urllib",
    "http",
    "socket",
    "ssl",
    "subprocess",
    "jarvis.agent.adapters",
    "jarvis.events.adapters",
    "jarvis.context.adapters",
    "jarvis.memory.adapters",
    "jarvis.cli",
    "jarvis.config",
}

ALLOWED_JARVIS_IMPORTS = {
    "jarvis.errors",
    "jarvis.agent",
    "jarvis.events",
    "jarvis.context",
    "jarvis.memory",
}

# Os componentes que executam ações. Desde a Fase 5 eles **existem**, e é por
# isso que esta checagem passou a ter dentes: o que era reserva de nome agora é
# uma fronteira real entre raciocinar e agir.
EXECUTION_PACKAGES = {
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.policy",
    "jarvis.execution",
    "jarvis.mcp",
    "mcp",
}

FORBIDDEN_VENDOR_SDKS = {
    "google.generativeai",
    "google.genai",
    "google.ai",
    "openai",
    "anthropic",
    "groq",
    "cohere",
    "mistralai",
    "httpx",
    "requests",
}


def _all_modules(root: Path) -> list[Path]:
    return sorted(root.glob("*.py"))


def _core_modules() -> list[Path]:
    return _all_modules(AGENT_ROOT)


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
        "errors.py",
        "messages.py",
        "ports.py",
        "decision.py",
        "conversation.py",
        "input.py",
        "importance.py",
        "prompt.py",
        "runtime.py",
    }


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido no Core do Agent Runtime"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_json_is_only_used_where_the_adr_requires_core_interpretation(module: Path) -> None:
    if module.name in JSON_ALLOWED_IN:
        return
    for imported in _imported_names(module):
        assert not _violates(imported, "json"), (
            f"{module.name} importa json; fora de {sorted(JSON_ALLOWED_IN)} isso é serialização, "
            "que pertence a um adapter"
        )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_allowed_components(module: Path) -> None:
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(_violates(imported, allowed) for allowed in ALLOWED_JARVIS_IMPORTS), (
            f"{module.name} importa {imported}, fora das dependências permitidas"
        )


@pytest.mark.parametrize(
    "module",
    [*_core_modules(), *_all_modules(ADAPTERS_ROOT)],
    ids=lambda path: path.name,
)
def test_no_path_from_the_agent_to_execution(module: Path) -> None:
    """`Agent ─X→ Skill`, `─X→ Tool Router`, `─X→ MCP`, `─X→ Policy`.

    O caminho permitido é `Agent → Decision → Policy → Skill → Tool Router`, e
    ele começa **fora** deste pacote: o agente entrega a `Decision` e para.
    """
    for imported in _imported_names(module):
        for forbidden in EXECUTION_PACKAGES:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}: o Agent Runtime não pode alcançar execução"
            )


@pytest.mark.parametrize(
    "module",
    [*_core_modules(), *_all_modules(ADAPTERS_ROOT)],
    ids=lambda path: path.name,
)
def test_no_module_imports_a_vendor_sdk(module: Path) -> None:
    """Nem o Core nem o adapter: o Gemini é falado por HTTP da stdlib
    ([ADR-0011](../docs/adr/0011-gemini-rest-llm-adapter.md))."""
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_VENDOR_SDKS:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, um SDK de vendor proibido"
            )


def test_only_the_adapters_touch_the_network() -> None:
    offenders = [
        module.name
        for module in _core_modules()
        if any(
            _violates(name, "urllib") or _violates(name, "http") for name in _imported_names(module)
        )
    ]

    assert offenders == []


def test_adapters_may_depend_on_core() -> None:
    # A direção oposta é obrigatória: adapters conhecem os ports que implementam.
    imports = {
        name
        for module in _all_modules(ADAPTERS_ROOT)
        for name in _imported_names(module)
        if name.startswith("jarvis")
    }

    assert any(name.startswith("jarvis.agent") for name in imports)


def test_adapters_do_not_reach_other_components() -> None:
    """Um adapter de LLM não tem nada que consultar contexto ou memória: ele
    recebe uma `LLMRequest` pronta (ADR-0002)."""
    offenders = [
        f"{module.name}:{name}"
        for module in _all_modules(ADAPTERS_ROOT)
        for name in _imported_names(module)
        if name.startswith("jarvis")
        and not _violates(name, "jarvis.agent")
        and not _violates(name, "jarvis.errors")
    ]

    assert offenders == []


def test_only_the_composition_root_wires_agent_adapters() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.agent.adapters") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_other_components_do_not_know_the_agent_exists() -> None:
    """Mão única: o agente conhece Event/Context/Memory, nunca o contrário.

    Se `jarvis.memory` passasse a importar `jarvis.agent`, o Memory System
    ganharia uma dependência de LLM que contracts §3.3 proíbe explicitamente.
    """
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for component in ("events", "context", "memory")
        for module in (SOURCE_ROOT / component).rglob("*.py")
        if any(_violates(name, "jarvis.agent") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_core_never_reads_configuration_by_itself() -> None:
    """Contracts §12: configuração é carregada uma vez, na composition root, e
    injetada. É também o que impede um secret de chegar ao prompt."""
    offenders = [
        module.name
        for module in [*_core_modules(), *_all_modules(ADAPTERS_ROOT)]
        if any(_violates(name, "jarvis.config") for name in _imported_names(module))
    ]

    assert offenders == []
