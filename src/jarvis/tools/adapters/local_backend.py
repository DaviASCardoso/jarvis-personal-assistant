"""Backend de Tools em processo: sistema de arquivos e informação de sistema.

Existe por duas razões, e a segunda é arquitetural:

1. dá execução real de ponta a ponta sem nenhum processo externo — a Fase 5
   consegue provar a cadeia inteira com `uv run pytest`, sem rede e sem servidor;
2. é a prova executável de que o contrato de `Tool` **não** é o formato de wire
   do MCP disfarçado. Se só existisse o backend MCP, `ToolDescriptor` acabaria
   virando um espelho do protocolo sem que ninguém percebesse
   ([ADR-0005](../../../../docs/adr/0005-skill-tool-mcp-distinction.md)).

Este é o único lugar da camada de ação que toca `pathlib` e `platform` — as
Skills que usam estas tools são Core puro e não importam nem um nem outro. É essa
separação que faz o teste "nenhuma Skill toca o sistema de arquivos" ser
verdadeiro em vez de decorativo.

**A raiz allowlistada é imposta aqui, e não pela política.** São barreiras
independentes: mesmo que uma regra de política seja afrouxada por engano, um
caminho fora da raiz continua recusado.
"""

import logging
import os
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from jarvis.events.event import JsonValue
from jarvis.tools.errors import ToolExecutionError, ToolInvalidInputError, ToolNotFoundError
from jarvis.tools.schema import FieldSpec, FieldType, ParameterSchema
from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolResult, make_tool_id

logger = logging.getLogger(__name__)

BACKEND_ID: Final = "local"

READ_TEXT: Final = make_tool_id(backend_id=BACKEND_ID, name="fs.read_text")
WRITE_TEXT: Final = make_tool_id(backend_id=BACKEND_ID, name="fs.write_text")
LIST_DIR: Final = make_tool_id(backend_id=BACKEND_ID, name="fs.list_dir")
SYSTEM_INFO: Final = make_tool_id(backend_id=BACKEND_ID, name="system.info")

MAX_PATH_LENGTH: Final = 300
MAX_CONTENT_LENGTH: Final = 100_000
MAX_READ_CHARS: Final = 100_000
MAX_ENTRIES: Final = 500

_PATH_FIELD: Final = FieldSpec(
    type=FieldType.STRING,
    required=True,
    description="Caminho relativo à raiz do workspace.",
    max_length=MAX_PATH_LENGTH,
)


def _descriptors() -> tuple[ToolDescriptor, ...]:
    return (
        ToolDescriptor(
            tool_id=READ_TEXT,
            backend_id=BACKEND_ID,
            name="fs.read_text",
            summary="Lê um arquivo de texto do workspace.",
            parameters=ParameterSchema(fields={"path": _PATH_FIELD}),
        ),
        ToolDescriptor(
            tool_id=WRITE_TEXT,
            backend_id=BACKEND_ID,
            name="fs.write_text",
            summary="Escreve (ou acrescenta) texto em um arquivo do workspace.",
            parameters=ParameterSchema(
                fields={
                    "path": _PATH_FIELD,
                    "content": FieldSpec(
                        type=FieldType.STRING, required=True, max_length=MAX_CONTENT_LENGTH
                    ),
                    "append": FieldSpec(type=FieldType.BOOLEAN, default=False),
                }
            ),
        ),
        ToolDescriptor(
            tool_id=LIST_DIR,
            backend_id=BACKEND_ID,
            name="fs.list_dir",
            summary="Lista o conteúdo de um diretório do workspace.",
            parameters=ParameterSchema(
                fields={
                    "path": FieldSpec(
                        type=FieldType.STRING, max_length=MAX_PATH_LENGTH, default="."
                    )
                }
            ),
        ),
        ToolDescriptor(
            tool_id=SYSTEM_INFO,
            backend_id=BACKEND_ID,
            name="system.info",
            summary="Informação básica do sistema e do workspace.",
            parameters=ParameterSchema(),
        ),
    )


class LocalToolBackend:
    """Implementação de `ToolBackend` sobre o sistema de arquivos local."""

    def __init__(self, *, root: Path) -> None:
        self._root = root

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    def discover(self) -> Sequence[ToolDescriptor]:
        return _descriptors()

    def close(self) -> None:
        """Nada a encerrar: não há processo, conexão nem descritor aberto."""

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult:
        """`timeout_seconds` é ignorado: operação local, síncrona e limitada por
        tamanho. Um watchdog aqui seria complexidade sem risco correspondente."""
        match call.tool_id:
            case _ if call.tool_id == READ_TEXT:
                data, message = self._read_text(call)
            case _ if call.tool_id == WRITE_TEXT:
                data, message = self._write_text(call)
            case _ if call.tool_id == LIST_DIR:
                data, message = self._list_dir(call)
            case _ if call.tool_id == SYSTEM_INFO:
                data, message = self._system_info()
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

    def _read_text(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        target = self._resolve(_text(call, "path"))
        try:
            content = target.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ToolExecutionError("arquivo não encontrado no workspace") from error
        except IsADirectoryError as error:
            raise ToolExecutionError("o caminho aponta para um diretório") from error
        except UnicodeDecodeError as error:
            raise ToolExecutionError("o arquivo não é texto UTF-8") from error
        except OSError as error:
            raise ToolExecutionError("não foi possível ler o arquivo") from error

        truncated = len(content) > MAX_READ_CHARS
        return (
            {
                "content": content[:MAX_READ_CHARS],
                "characters": len(content),
                "truncated": truncated,
            },
            # A mensagem descreve; o conteúdo fica só em `data`. Mensagem é o que
            # tende a virar log e resumo — conteúdo de arquivo não pode ir junto.
            f"{len(content)} caracteres lidos",
        )

    def _write_text(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        target = self._resolve(_text(call, "path"))
        content = _text(call, "content")
        append = bool(call.parameters.get("append", False))
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a" if append else "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        except IsADirectoryError as error:
            raise ToolExecutionError("o caminho aponta para um diretório") from error
        except OSError as error:
            raise ToolExecutionError("não foi possível gravar o arquivo") from error

        return (
            {"characters": len(content), "appended": append},
            f"{len(content)} caracteres {'acrescentados' if append else 'gravados'}",
        )

    def _list_dir(self, call: ToolCall) -> tuple[dict[str, JsonValue], str]:
        raw = call.parameters.get("path", ".")
        target = self._resolve(raw if isinstance(raw, str) else ".")
        try:
            entries = sorted(
                item.name + ("/" if item.is_dir() else "") for item in target.iterdir()
            )
        except FileNotFoundError as error:
            raise ToolExecutionError("diretório não encontrado no workspace") from error
        except NotADirectoryError as error:
            raise ToolExecutionError("o caminho não é um diretório") from error
        except OSError as error:
            raise ToolExecutionError("não foi possível listar o diretório") from error

        return (
            {"entries": entries[:MAX_ENTRIES], "count": len(entries)},
            f"{len(entries)} item(ns)",
        )

    def _system_info(self) -> tuple[dict[str, JsonValue], str]:
        """Deliberadamente **sem** hostname, usuário e variáveis de ambiente.

        O resultado de uma Skill pode acabar num prompt enviado a um serviço de
        nuvem; informação de identificação da máquina não tem por que fazer essa
        viagem para responder "o sistema está de pé?".
        """
        free_mb: JsonValue = None
        if self._root.exists():
            usage = shutil.disk_usage(self._root)
            free_mb = round(usage.free / (1024 * 1024), 1)

        return (
            {
                "os": platform.system(),
                "os_release": platform.release(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
                "workspace_exists": self._root.exists(),
                "free_disk_mb": free_mb,
                "executable_is_venv": sys.prefix != sys.base_prefix,
            },
            f"{platform.system()} {platform.release()}, Python {platform.python_version()}",
        )

    # ------------------------------------------------------------- caminhos

    def _resolve(self, raw: str) -> Path:
        """Resolve dentro da raiz allowlistada, ou recusa.

        Três recusas distintas, e todas antes de tocar o disco: caminho absoluto,
        travessia com `..`, e o caso que só a resolução revela — um symlink que
        aponta para fora. `resolve()` segue links, e é por isso que a checagem
        acontece **depois** dele, e não sobre o texto.
        """
        candidate = Path(raw)
        if candidate.is_absolute() or candidate.drive or candidate.anchor:
            raise ToolInvalidInputError("o caminho precisa ser relativo ao workspace")

        root = self._root.resolve()
        resolved = (root / candidate).resolve()
        if resolved != root and root not in resolved.parents:
            # A mensagem não repete o caminho recusado: ele pode ter vindo de um
            # payload de evento.
            raise ToolInvalidInputError("o caminho sai da raiz permitida do workspace")
        return resolved


def _text(call: ToolCall, name: str) -> str:
    value = call.parameters.get(name)
    if not isinstance(value, str):
        raise ToolInvalidInputError(f"{name} precisa ser texto")
    return value
