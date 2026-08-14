"""Regra de dependência do pacote `jarvis.voice`.

Mesma técnica AST dos cinco componentes anteriores, com a fronteira **mais
estrita** de todas: este pacote importa de `jarvis` apenas `jarvis.errors` e ele
mesmo. Nem `jarvis.agent`.

`architecture-contracts.md §3.9` permitiria à Voice Interface conhecer a
interface conversacional do Agent Runtime. Um port próprio (`ConversationalAgent`)
é mais forte e mais barato: o loop inteiro fica testável sem LLM, sem banco e sem
rede, e "a voz não alcança execução" deixa de ser convenção para virar a lista
abaixo.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "jarvis"
VOICE_ROOT = SOURCE_ROOT / "voice"
ADAPTERS_ROOT = VOICE_ROOT / "adapters"

ALLOWED_JARVIS_IMPORTS = {"jarvis.errors", "jarvis.voice"}

FORBIDDEN_IN_CORE = {
    "sqlite3",
    "pathlib",
    "urllib",
    "http",
    "socket",
    "ssl",
    "subprocess",
    "wave",
    "base64",
    "json",
    "jarvis.voice.adapters",
    "jarvis.cli",
    "jarvis.config",
}

# Nem o Core nem os adapters alcançam qualquer outro componente. O resto do
# Jarvis chega por um port implementado no composition root.
FORBIDDEN_EVERYWHERE = {
    "jarvis.agent",
    "jarvis.context",
    "jarvis.events",
    "jarvis.execution",
    "jarvis.interface",
    "jarvis.memory",
    "jarvis.policy",
    "jarvis.skills",
    "jarvis.tools",
    "jarvis.audit",
}

FORBIDDEN_VENDOR_SDKS = {
    "groq",
    "openai",
    "anthropic",
    "google.cloud",
    "google.generativeai",
    "google.genai",
    "httpx",
    "requests",
    "numpy",
    "torch",
    "whisper",
    "pvporcupine",
    "openwakeword",
}

#: O único pacote de terceiros do repositório, e o único arquivo onde ele pode
#: aparecer ([ADR-0020](../docs/adr/0020-audio-io-ports-and-optional-backend.md)).
THIRD_PARTY_ALLOWED_IN = {"sounddevice_audio.py": {"sounddevice"}}


def _all_modules(root: Path) -> list[Path]:
    return sorted(root.glob("*.py"))


def _core_modules() -> list[Path]:
    return _all_modules(VOICE_ROOT)


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
        "audio.py",
        "ports.py",
        "vad.py",
        "wake.py",
        "session.py",
        "loop.py",
    }


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_does_not_depend_on_infrastructure(module: Path) -> None:
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_IN_CORE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido no Core da camada de voz"
            )


@pytest.mark.parametrize("module", _core_modules(), ids=lambda path: path.name)
def test_core_only_depends_on_its_own_errors(module: Path) -> None:
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
def test_no_path_from_the_voice_to_anything_else(module: Path) -> None:
    """`Voz ─X→ Agent`, `─X→ Memory`, `─X→ Execution`, `─X→ Events`.

    O caminho permitido é `Voz → ConversationalAgent (port) → composition root`,
    e ele começa **fora** deste pacote.
    """
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_EVERYWHERE:
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}: a camada de voz não conhece outros componentes"
            )


@pytest.mark.parametrize(
    "module",
    [*_core_modules(), *_all_modules(ADAPTERS_ROOT)],
    ids=lambda path: path.name,
)
def test_no_module_imports_a_vendor_sdk_or_a_local_model(module: Path) -> None:
    """Groq e Google são falados por HTTP da stdlib (ADR-0022); `torch`,
    `whisper` e detectores de wake word locais são **IA local**, que a fase
    proíbe (ADR-0021)."""
    allowed = THIRD_PARTY_ALLOWED_IN.get(module.name, set())
    for imported in _imported_names(module):
        for forbidden in FORBIDDEN_VENDOR_SDKS:
            if forbidden in allowed:
                continue
            assert not _violates(imported, forbidden), (
                f"{module.name} importa {imported}, proibido na camada de voz"
            )


def test_only_one_module_touches_the_audio_backend() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if module.name not in THIRD_PARTY_ALLOWED_IN
        and any(_violates(name, "sounddevice") for name in _imported_names(module))
    ]

    assert offenders == []


def test_only_the_adapters_touch_the_network_and_the_disk() -> None:
    offenders = [
        module.name
        for module in _core_modules()
        if any(
            _violates(name, "urllib") or _violates(name, "sqlite3") or _violates(name, "wave")
            for name in _imported_names(module)
        )
    ]

    assert offenders == []


def test_adapters_may_depend_on_core() -> None:
    imports = {
        name
        for module in _all_modules(ADAPTERS_ROOT)
        for name in _imported_names(module)
        if name.startswith("jarvis")
    }

    assert any(name.startswith("jarvis.voice") for name in imports)


def test_only_the_composition_root_wires_voice_adapters() -> None:
    offenders = [
        module.relative_to(SOURCE_ROOT).as_posix()
        for module in SOURCE_ROOT.rglob("*.py")
        if ADAPTERS_ROOT not in module.parents
        and module.name != "cli.py"
        and any(_violates(name, "jarvis.voice.adapters") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_other_components_do_not_know_the_voice_exists() -> None:
    """Mão única. Se `jarvis.agent` importasse `jarvis.voice`, o Agent Runtime
    ganharia um canal de saída que o ADR-0003 não prevê."""
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
        )
        for module in (SOURCE_ROOT / component).rglob("*.py")
        if any(_violates(name, "jarvis.voice") for name in _imported_names(module))
    ]

    assert offenders == []


def test_the_core_never_reads_configuration_by_itself() -> None:
    """Contracts §12: configuração é carregada uma vez, na composition root, e
    injetada. É também o que impede uma credencial de chegar a um adapter que loga."""
    offenders = [
        module.name
        for module in [*_core_modules(), *_all_modules(ADAPTERS_ROOT)]
        if any(_violates(name, "jarvis.config") for name in _imported_names(module))
    ]

    assert offenders == []
