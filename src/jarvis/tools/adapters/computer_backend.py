"""Backend de Tools sobre o sistema operacional: processos, janelas e comandos
allowlistados (Fase 8.2).

Cinco Tools, e a barreira de segurança real está aqui, não na Skill: `open_app`
e `run_command` **nunca** aceitam um `argv` vindo do chamador — só um `name`
que precisa bater com uma chave de `command_allowlist`, um mapa nome→argv
carregado uma única vez pelo composition root a partir de
`JARVIS_COMPUTER_COMMAND_ALLOWLIST_PATH`
([ADR-0031](../../../../docs/adr/0031-command-allowlist-execution-model.md)).
Nunca `shell=True`, nunca concatenação de texto — mesmo espírito da raiz
allowlistada de `LocalToolBackend._resolve` recusar antes de agir.

Cada operação nativa (enumerar janelas, encerrar processo, lançar programa,
rodar comando) é **injetável**, mesmo desenho de
`ResourceUsageProvider`/`WindowActivityProvider` (Fase 8.1): nenhum teste
chama `ctypes`, `psutil` ou `subprocess` de verdade.
"""

import json
import logging
import os
import platform
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final

import psutil

from jarvis.events.event import JsonValue
from jarvis.tools.errors import (
    ToolConfigurationError,
    ToolExecutionError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolTimeoutError,
    ToolUnavailableError,
)
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolResult, make_tool_id

logger = logging.getLogger(__name__)

BACKEND_ID: Final = "computer"

LIST_PROCESSES: Final = make_tool_id(backend_id=BACKEND_ID, name="list_processes")
FOCUS_WINDOW: Final = make_tool_id(backend_id=BACKEND_ID, name="focus_window")
OPEN_APP: Final = make_tool_id(backend_id=BACKEND_ID, name="open_app")
CLOSE_APP: Final = make_tool_id(backend_id=BACKEND_ID, name="close_app")
RUN_COMMAND: Final = make_tool_id(backend_id=BACKEND_ID, name="run_command")

MAX_PROCESSES: Final = 200
MAX_NAME_LENGTH: Final = 100
MAX_OUTPUT_CHARS: Final = 4000

_APPLICATION_FIELD: Final = FieldSpec(
    type=FieldType.STRING,
    required=True,
    max_length=MAX_NAME_LENGTH,
    description="Nome (ou parte do nome) do processo/aplicativo.",
)
_ALLOWLIST_NAME_FIELD: Final = FieldSpec(
    type=FieldType.STRING,
    required=True,
    max_length=MAX_NAME_LENGTH,
    description="Nome cadastrado na allowlist de comandos.",
)


def _descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_id=LIST_PROCESSES,
            backend_id=BACKEND_ID,
            name="list_processes",
            summary="Lista os processos em execução.",
            parameters=ParameterSchema(),
        ),
        ToolDescriptor(
            tool_id=FOCUS_WINDOW,
            backend_id=BACKEND_ID,
            name="focus_window",
            summary="Traz a janela de um aplicativo para primeiro plano.",
            parameters=ParameterSchema(fields={"application": _APPLICATION_FIELD}),
        ),
        ToolDescriptor(
            tool_id=OPEN_APP,
            backend_id=BACKEND_ID,
            name="open_app",
            summary="Abre um aplicativo cadastrado na allowlist de comandos.",
            parameters=ParameterSchema(fields={"name": _ALLOWLIST_NAME_FIELD}),
        ),
        ToolDescriptor(
            tool_id=CLOSE_APP,
            backend_id=BACKEND_ID,
            name="close_app",
            summary="Encerra os processos em execução de um aplicativo.",
            parameters=ParameterSchema(fields={"application": _APPLICATION_FIELD}),
        ),
        ToolDescriptor(
            tool_id=RUN_COMMAND,
            backend_id=BACKEND_ID,
            name="run_command",
            summary="Executa um comando cadastrado na allowlist de comandos.",
            parameters=ParameterSchema(fields={"name": _ALLOWLIST_NAME_FIELD}),
        ),
    )


def load_command_allowlist(path: Path) -> Mapping[str, tuple[str, ...]]:
    """Lê nome→argv de um JSON. Arquivo ausente = allowlist vazia, sem erro —
    mesmo critério de `load_mcp_config`: uma capacidade opcional não pode virar
    pré-requisito só porque o arquivo não existe.

    Nunca texto de shell: cada valor é uma lista de argumentos já separados,
    exatamente como `subprocess.run(argv)`/`Popen(argv)` esperam — sem
    interpolação, sem `shell=True`, sem superfície de injeção de comando
    ([ADR-0031](../../../../docs/adr/0031-command-allowlist-execution-model.md)).
    """
    if not path.exists():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolConfigurationError(f"não foi possível ler {path}: {error}") from error
    if not isinstance(raw, Mapping):
        raise ToolConfigurationError(f"{path}: o documento precisa ser um objeto JSON")

    allowlist: dict[str, tuple[str, ...]] = {}
    for name, argv in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ToolConfigurationError(f"{path}: allowlist tem uma chave inválida")
        if (
            not isinstance(argv, Sequence)
            or isinstance(argv, str)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
        ):
            raise ToolConfigurationError(
                f"{path}: '{name}' precisa mapear para uma lista não vazia de texto"
            )
        allowlist[name] = tuple(argv)
    return allowlist


def _process_name(pid: int) -> str:
    try:
        name: str = psutil.Process(pid).name()
    except psutil.Error:
        return ""
    return name


def _default_list_process_names() -> Sequence[str]:
    names: list[str] = []
    for process in psutil.process_iter(["name"]):
        try:
            name = process.info.get("name")
        except psutil.Error:
            continue
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _focus_window_windows(application: str) -> bool:
    """`getattr(ctypes, "windll")`: ver docstring equivalente em
    `context/adapters/window_activity_provider.py` — evita `# type: ignore`
    que seria "não utilizado" dependendo da plataforma em que o mypy roda."""
    import ctypes
    from ctypes import wintypes

    user32 = getattr(ctypes, "windll").user32  # noqa: B009 - deliberado, ver docstring
    # `WINFUNCTYPE` sofre do mesmo problema de tipagem condicional por
    # plataforma que `windll` — mesmo `getattr` pelo mesmo motivo.
    winfunctype = getattr(ctypes, "WINFUNCTYPE")  # noqa: B009 - deliberado, ver docstring
    target = application.lower()
    found: list[int] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if target in _process_name(pid.value).lower():
            found.append(hwnd)
            return False
        return True

    enum_proc = winfunctype(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(_callback)
    user32.EnumWindows(enum_proc, 0)
    if not found:
        return False
    user32.SetForegroundWindow(found[0])
    return True


def _default_focus_window(application: str) -> bool:
    if platform.system() != "Windows":
        raise ToolUnavailableError("foco de janela só é suportado no Windows")
    return _focus_window_windows(application)


def _default_launch(argv: Sequence[str]) -> None:
    # argv fixo, vindo só da allowlist carregada pelo composition root — sem
    # `shell=True` e sem nenhuma entrada externa interpolada.
    try:
        subprocess.Popen(list(argv))
    except OSError as error:
        raise ToolExecutionError("não foi possível abrir o aplicativo") from error


def _default_terminate_processes(application: str) -> int:
    """Nunca encerra o próprio processo do Jarvis (Fase 8.8 — revisão de
    limites de segurança). Um `application` cuja substring bata com o nome
    do interpretador (`python`/`pythonw`) mataria quem está executando esta
    chamada antes de devolver o resultado — auto-exclusão por `pid`, não por
    nome, porque o nome do executável não é estável entre ambientes."""
    target = application.lower()
    current_pid = os.getpid()
    terminated = 0
    for process in psutil.process_iter(["name"]):
        if process.pid == current_pid:
            continue
        try:
            name = process.info.get("name")
            if isinstance(name, str) and target in name.lower():
                process.terminate()
                terminated += 1
        except psutil.Error:
            continue
    return terminated


def _default_run(argv: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv), capture_output=True, text=True, timeout=timeout_seconds, check=False
    )


class ComputerToolBackend:
    """Implementação de `ToolBackend` sobre processos, janelas e comandos locais.

    `command_allowlist` é o único jeito de `open_app`/`run_command` chegarem a
    um `argv` — vazio por padrão, o que nega as duas Tools de propósito (mesmo
    critério de allowlist vazia = nega tudo de `policy_granted_capabilities`).
    """

    def __init__(
        self,
        *,
        command_allowlist: Mapping[str, tuple[str, ...]] = MappingProxyType({}),
        list_process_names: Callable[[], Sequence[str]] = _default_list_process_names,
        focus_window: Callable[[str], bool] = _default_focus_window,
        launch: Callable[[Sequence[str]], None] = _default_launch,
        terminate_processes: Callable[[str], int] = _default_terminate_processes,
        run: Callable[[Sequence[str], float], subprocess.CompletedProcess[str]] = _default_run,
    ) -> None:
        self._commands = dict(command_allowlist)
        self._list_process_names = list_process_names
        self._focus_window = focus_window
        self._launch = launch
        self._terminate_processes = terminate_processes
        self._run = run

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    def discover(self) -> Sequence[ToolDescriptor]:
        return _descriptors()

    def close(self) -> None:
        """Nada a encerrar: nenhum processo, conexão nem descritor aberto."""

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        match call.tool_id:
            case _ if call.tool_id == LIST_PROCESSES:
                data, message = self._list_processes_tool()
            case _ if call.tool_id == FOCUS_WINDOW:
                data, message = self._focus_window_tool(call)
            case _ if call.tool_id == OPEN_APP:
                data, message = self._open_app_tool(call)
            case _ if call.tool_id == CLOSE_APP:
                data, message = self._close_app_tool(call)
            case _ if call.tool_id == RUN_COMMAND:
                data, message = self._run_command_tool(call, timeout_seconds=timeout_seconds)
            case _:
                raise ToolNotFoundError(f"{call.tool_id} não é uma tool deste backend")

        return ToolResult(
            tool_id=call.tool_id,
            backend_id=BACKEND_ID,
            execution_id=call.execution_id,
            data=data,
            message=message,
        )

    # ------------------------------------------------------------ operações

    def _list_processes_tool(self) -> tuple[dict[str, JsonValue], str]:
        names = sorted(set(self._list_process_names()))[:MAX_PROCESSES]
        return {"processes": names, "count": len(names)}, f"{len(names)} processo(s) em execução"

    def _focus_window_tool(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        application = _text(call, "application")
        if not self._focus_window(application):
            raise ToolExecutionError("nenhuma janela encontrada para esse aplicativo")
        return (
            {"application": application, "focused": True},
            f"{application} trazido para primeiro plano",
        )

    def _open_app_tool(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        name = _text(call, "name")
        argv = self._commands.get(name)
        if argv is None:
            raise ToolInvalidInputError("aplicativo não está cadastrado na allowlist")
        self._launch(argv)
        return {"name": name}, f"{name} aberto"

    def _close_app_tool(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        application = _text(call, "application")
        terminated = self._terminate_processes(application)
        if terminated == 0:
            raise ToolExecutionError("nenhum processo encontrado com esse nome")
        return (
            {"application": application, "terminated_count": terminated},
            f"{terminated} processo(s) encerrado(s)",
        )

    def _run_command_tool(
        self, call: ToolCall, *, timeout_seconds: float
    ) -> tuple[dict[str, JsonValue], str]:
        name = _text(call, "name")
        argv = self._commands.get(name)
        if argv is None:
            raise ToolInvalidInputError("comando não está cadastrado na allowlist")
        try:
            result = self._run(argv, timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise ToolTimeoutError("comando excedeu o tempo limite") from error
        except OSError as error:
            raise ToolExecutionError("não foi possível executar o comando") from error
        return (
            {
                "name": name,
                "returncode": result.returncode,
                "stdout": (result.stdout or "")[:MAX_OUTPUT_CHARS],
                "stderr": (result.stderr or "")[:MAX_OUTPUT_CHARS],
            },
            f"comando {name!r} executado (código {result.returncode})",
        )


def _text(call: ToolCall, name: str) -> str:
    value = call.parameters.get(name)
    if not isinstance(value, str):
        raise ToolInvalidInputError(f"{name} precisa ser texto")
    return value
