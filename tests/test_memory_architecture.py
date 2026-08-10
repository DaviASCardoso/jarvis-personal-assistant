"""Verifica a regra de dependência do ADR-0001 sobre o pacote `jarvis.memory`.

Mesma técnica AST de `test_events_architecture.py`/`test_context_architecture.py`.

Diferença deliberada em relação ao Context Engine: **`jarvis.events` e
`jarvis.context` NÃO são permitidos no Core de memória.** Contracts §3.3 lista
as dependências permitidas do Memory System como "Domain, `EmbeddingProvider`
port, `MemoryRepository` port" — o Event System não está nessa lista (ao
contrário da §3.2, que o lista explicitamente para o Context Engine). A
integração dos dois vive inteiramente em `memory/adapters/` (`event_consumer.py`,
`context_bridge.py`), nunca no Core.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
MEMORY_ROOT = SOURCE_ROOT / "memory"
ADAPTERS_ROOT = MEMORY_ROOT / "adapters"

FORBIDDEN_IN_CORE = {
    "sqlite3",
    "json",
    "pathlib",
    "jarvis.memory.adapters",
    "jarvis.events",
    "jarvis.context",
    "jarvis.cli",
    "jarvis.config",
}
ALLOWED_JARVIS_IMPORTS_IN_MEMORY = {"jarvis.memory", "jarvis.errors"}

# Nenhum SDK de LLM ou de embedding de vendor é dependência deste projeto —
# PHASE-3.md §17/§18 exige que nem o Core nem os adapters conheçam um. A lista
# é a checagem direta dessa proibição, não uma suposição sobre o que existirá.
FORBIDDEN_VENDOR_SDKS = {
    "openai",
    "anthropic",
    "cohere",
    "google.generativeai",
    "mistralai",
    "httpx",
    "requests",
}


def _all_modules(root: Path) -> list[Path]:
    return sorted(root.glob("*.py"))


def _core_modules() -> list[Path]:
    return _all_modules(MEMORY_ROOT)


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
        "memory.py",
        "embedding.py",
        "errors.py",
        "ports.py",
        "ranking.py",
        "retrieval.py",
        "consolidation.py",
        "manager.py",
    }


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido no Core do Memory System"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_allowed_components(module: Path) -> None:
    for imported in _imported_names(module):
        if not imported.startswith("jarvis"):
            continue
        assert any(
            _violates(imported, allowed) or imported == allowed
            for allowed in ALLOWED_JARVIS_IMPORTS_IN_MEMORY
        ), f"{module.name} importa {imported}, fora das dependências permitidas"


def test_adapters_may_depend_on_core() -> None:
    # A direção oposta é obrigatória: adapters conhecem os ports que implementam.
    imports = {
        name
        for module in ADAPTERS_ROOT.glob("*.py")
        for name in _imported_names(module)
        if name.startswith("jarvis")
    }

    assert any(name.startswith("jarvis.memory") for name in imports)


def test_only_the_composition_root_wires_memory_adapters() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.memory.adapters") for name in _imported_names(module))
    ]

    assert offenders == []


def test_neither_the_event_system_nor_the_context_engine_know_about_memory() -> None:
    """Mão única, nos dois sentidos: nem `events/` nem `context/` (Core) sabem
    que `jarvis.memory` existe — a integração vive só em `memory/adapters/`."""
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for component in ("events", "context")
        for module in (SOURCE_ROOT / component).rglob("*.py")
        if any(_violates(name, "jarvis.memory") for name in _imported_names(module))
    ]

    assert offenders == []


@pytest.mark.parametrize(
    "module",
    [*_core_modules(), *_all_modules(ADAPTERS_ROOT)],
    ids=lambda path: path.name,
)
def test_no_module_imports_a_vendor_llm_or_embedding_sdk(module: Path) -> None:
    """`PHASE-3.md §17`: nenhuma operação básica de memória pode depender de
    `LLMProvider`/SDK de vendor. `HashingEmbeddingProvider` é local, e nenhum
    outro adapter desta fase chama serviço externo."""
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_VENDOR_SDKS:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, um SDK de vendor proibido nesta fase"
            )
