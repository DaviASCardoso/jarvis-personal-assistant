"""O painel servido por HTTP local, sobre `http.server` da biblioteca padrão.

Zero dependência nova e zero build de front-end: o navegador é o renderizador, e
`ThreadingHTTPServer` é o servidor
([ADR-0024](../../../../docs/adr/0024-observability-panel-as-snapshot-reader.md)).

Três propriedades que o desenho garante, e que os testes verificam:

1. **Somente leitura.** Não existe rota de escrita — `POST`, `PUT` e `DELETE`
   respondem 405 em qualquer caminho. Confirmar uma ação continua sendo assunto
   do CLI (ADR-0014) e da voz; um painel que executa seria um segundo caminho
   até a Tool, sem o cuidado que o CLI tem.
2. **Local.** O bind é verificado na construção: um host que não seja de
   loopback é recusado com `PanelError`.
3. **Sem banco.** O handler lê um `PanelSnapshot` já montado do `LiveState`.
   Nenhuma thread além da principal toca SQLite (ADR-0023).
"""

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Final, Self

from jarvis.interface.adapters.page import PANEL_HTML
from jarvis.interface.errors import PanelAddressInUseError, PanelError
from jarvis.interface.live import LiveState
from jarvis.interface.viewmodel import to_json_object

logger = logging.getLogger(__name__)

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765

LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost", "::1"})

#: Nenhuma origem externa: a página não carrega nada de fora e não consegue
#: mandar nada para fora.
CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "connect-src 'self'; img-src 'self' data:"
)

_METHOD_NOT_ALLOWED: Final = 405


class _QuietServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` que não despeja traceback no terminal.

    O default imprime a exceção de qualquer handler em stderr — e stderr aqui é o
    mesmo terminal onde a conversa por voz está acontecendo. Um navegador que
    fecha a aba não é um incidente que mereça dez linhas de stack trace.
    """

    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        logger.debug("panel.request_failed", extra={"client": str(client_address)})


class PanelServer:
    def __init__(
        self,
        *,
        live: LiveState,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        stream_timeout: float = 25.0,
    ) -> None:
        if host not in LOCAL_HOSTS:
            raise PanelError(
                f"o painel só serve em loopback, recebido {host!r}; expor na rede exigiria "
                "autenticação, que está fora do escopo desta fase"
            )
        if not 0 <= port <= 65535:
            raise PanelError(f"porta inválida: {port}")

        self._live = live
        self._host = host
        self._stream_timeout = stream_timeout
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

        try:
            self._server = _QuietServer((host, port), _handler(self))
        except OSError as error:
            raise PanelAddressInUseError(
                f"não foi possível abrir o painel em {host}:{port}"
            ) from error

    @property
    def port(self) -> int:
        """Resolvido de verdade — `port=0` vira a porta que o SO escolheu."""
        address: tuple[str, int] = self._server.server_address[:2]  # type: ignore[assignment]
        return address[1]

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}"

    @property
    def live(self) -> LiveState:
        return self._live

    @property
    def stream_timeout(self) -> float:
        return self._stream_timeout

    @property
    def stopping(self) -> threading.Event:
        return self._stopping

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="jarvis-panel", daemon=True
        )
        self._thread.start()
        logger.info("panel.started", extra={"url": self.url})

    def stop(self) -> None:
        self._stopping.set()
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("panel.stopped")

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()


def _handler(panel: PanelServer) -> type[BaseHTTPRequestHandler]:
    class PanelHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "jarvis-panel"

        def log_message(self, format: str, *args: object) -> None:
            # O default escreve em stderr e polui o terminal da conversa.
            logger.debug("panel.request", extra={"detail": format % args})

        def handle_one_request(self) -> None:
            # Um navegador que fecha a aba derruba a conexão no meio de um
            # `readline`, e o default do `socketserver` despeja o traceback em
            # stderr — bem no terminal onde a conversa por voz está acontecendo.
            # Cliente que vai embora é fim de conexão, não incidente.
            try:
                super().handle_one_request()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
                logger.debug("panel.client_gone")

        def _headers(self, status: int, content_type: str, *, length: int | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.send_header("X-Content-Type-Options", "nosniff")
            if length is not None:
                self.send_header("Content-Length", str(length))
            self.end_headers()

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self._headers(status, content_type, length=len(body))
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, PANEL_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(200, _state_body(panel.live), "application/json; charset=utf-8")
            elif path == "/api/stream":
                self._stream()
            elif path == "/healthz":
                body = f"ok revision={panel.live.revision}".encode()
                self._send(200, body, "text/plain; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def _stream(self) -> None:
            self._headers(200, "text/event-stream; charset=utf-8")
            seen = 0
            try:
                self.wfile.write(b"retry: 3000\n\n")
                self.wfile.flush()
                while not panel.stopping.is_set():
                    snapshot = panel.live.wait_for(after=seen, timeout=panel.stream_timeout)
                    if snapshot is None:
                        self.wfile.write(b": heartbeat\n\n")
                    else:
                        seen = snapshot.revision
                        payload = json.dumps(to_json_object(snapshot), ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (TimeoutError, BrokenPipeError, ConnectionResetError, OSError):
                # O cliente foi embora. Fim de conexão, não erro.
                logger.debug("panel.stream_closed")

        def _reject(self) -> None:
            self._send(_METHOD_NOT_ALLOWED, b"o painel e somente leitura", "text/plain")

        do_POST = _reject
        do_PUT = _reject
        do_DELETE = _reject
        do_PATCH = _reject

    return PanelHandler


def _state_body(live: LiveState) -> bytes:
    snapshot = live.current()
    if snapshot is None:
        return json.dumps({"revision": 0, "as_of": None, "degraded": ["snapshot"]}).encode("utf-8")
    return json.dumps(to_json_object(snapshot), ensure_ascii=False).encode("utf-8")


def open_browser(url: str, *, opener: Callable[[str], bool] | None = None) -> None:
    """Abre o painel no navegador, se o usuário pediu.

    Import tardio de `webbrowser` de propósito: é conveniência de borda, e não
    tem por que ser carregado por quem só quer a API.
    """
    if opener is None:  # pragma: no cover - conveniência de terminal
        import webbrowser

        opener = webbrowser.open
    try:
        opener(url)
    except Exception as error:  # pragma: no cover - navegador é opcional
        logger.debug("panel.browser_failed", extra={"error_type": type(error).__name__})
