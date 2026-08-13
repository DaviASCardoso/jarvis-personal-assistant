"""Transporte stdio para MCP: subprocesso + JSON-RPC delimitado por linha.

Duas decisões que a portabilidade impôs, e que valem registro porque não são
óbvias:

1. **thread leitora + `queue`, não `select`.** `selectors`/`select` não funcionam
   sobre pipes no Windows, e este projeto é desenvolvido em Windows e testado em
   Linux no CI. Uma thread que só faz `for line in stdout` e empurra para uma
   `Queue` funciona igual nos dois, e dá timeout de graça via `Queue.get(timeout)`.
2. **`stderr=DEVNULL`.** Capturar stderr exigiria uma segunda thread para não
   travar o pipe, e o que viesse de lá acabaria em log — inclusive o que um
   servidor mal-comportado imprimir sobre a própria credencial. O diagnóstico do
   servidor é responsabilidade dele.

`Transport` é Protocol porque é o ponto de injeção que permite testar o cliente
MCP inteiro — handshake, timeout, `id` trocado, servidor que morre — sem levantar
processo nenhum.
"""

import contextlib
import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Final, Protocol

from jarvis.tools.errors import ToolProtocolError, ToolTimeoutError, ToolUnavailableError

logger = logging.getLogger(__name__)

TERMINATE_GRACE_SECONDS: Final = 2.0

# Sentinela de fim de fluxo: a thread leitora a empurra ao ver EOF, e é assim que
# `receive` distingue "o servidor está pensando" de "o servidor morreu".
_EOF: Final = None


class Transport(Protocol):
    def start(self) -> None: ...

    def send(self, line: str) -> None: ...

    def receive(self, *, timeout_seconds: float) -> str: ...

    def close(self) -> None: ...

    @property
    def is_running(self) -> bool: ...


class StdioTransport:
    """Um MCP Server local, falado por stdin/stdout."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        env: Mapping[str, str],
        cwd: str | None = None,
        server_id: str = "mcp",
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._command = tuple(command)
        self._env = dict(env)
        self._cwd = cwd
        self._server_id = server_id
        self._monotonic = monotonic
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.is_running:
            return
        try:
            process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self._env,
                cwd=self._cwd,
                text=True,
                encoding="utf-8",
                # MCP é UTF-8 no fio, mas um servidor mal configurado pode emitir
                # outra coisa — em Windows, o padrão do console ainda é cp1252.
                # `replace` faz esse byte virar uma resposta que não é JSON, e daí
                # um `ToolProtocolError` claro; sem isto, a thread leitora morre
                # com `UnicodeDecodeError` e o sintoma vira "o servidor sumiu".
                errors="replace",
                bufsize=1,
            )
        except (OSError, ValueError) as error:
            raise ToolUnavailableError(
                f"não foi possível iniciar o MCP Server {self._server_id}"
            ) from error

        self._process = process
        self._lines = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_forever,
            args=(process, self._lines),
            name=f"mcp-reader-{self._server_id}",
            daemon=True,
        )
        self._reader.start()
        logger.info("mcp.started", extra={"server_id": self._server_id})

    @staticmethod
    def _read_forever(process: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
        stdout = process.stdout
        if stdout is None:  # pragma: no cover - PIPE garantido no Popen
            lines.put(_EOF)
            return
        try:
            for line in stdout:
                lines.put(line)
        except (OSError, ValueError):
            # Pipe fechado enquanto líamos: o `finally` sinaliza EOF, e quem
            # espera recebe `ToolUnavailableError` em vez de travar.
            pass
        finally:
            lines.put(_EOF)

    def send(self, line: str) -> None:
        process = self._process
        if process is None or process.stdin is None or not self.is_running:
            raise ToolUnavailableError(f"MCP Server {self._server_id} não está em execução")
        try:
            process.stdin.write(f"{line}\n")
            process.stdin.flush()
        except (OSError, ValueError) as error:
            raise ToolUnavailableError(
                f"falha ao escrever para o MCP Server {self._server_id}"
            ) from error

    def receive(self, *, timeout_seconds: float) -> str:
        """Uma linha, ou uma exceção. Linhas em branco são puladas, não devolvidas."""
        deadline = self._monotonic() + timeout_seconds
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise ToolTimeoutError(
                    f"MCP Server {self._server_id} não respondeu em {timeout_seconds:g}s"
                )
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty as error:
                raise ToolTimeoutError(
                    f"MCP Server {self._server_id} não respondeu em {timeout_seconds:g}s"
                ) from error
            if line is _EOF:
                raise ToolUnavailableError(
                    f"MCP Server {self._server_id} encerrou o fluxo de saída"
                )
            if line.strip():
                return line
            # Linha em branco não é resposta e não deve consumir o orçamento como
            # se fosse; o laço continua até a deadline.

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except OSError:
            pass
        finally:
            if process.stdout is not None:
                with contextlib.suppress(OSError):
                    process.stdout.close()
            reader, self._reader = self._reader, None
            if reader is not None:
                reader.join(timeout=TERMINATE_GRACE_SECONDS)
            logger.info("mcp.stopped", extra={"server_id": self._server_id})


def require_line(transport: Transport, *, timeout_seconds: float) -> str:
    """Lê uma linha traduzindo o improvável — transporte que devolve vazio."""
    line = transport.receive(timeout_seconds=timeout_seconds)
    if not line.strip():  # pragma: no cover - `receive` já pula linhas em branco
        raise ToolProtocolError("o servidor devolveu uma linha vazia")
    return line
