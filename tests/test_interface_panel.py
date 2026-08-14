"""O servidor do painel: rotas, cabeçalhos, SSE e a ausência de escrita.

Sobe um servidor de verdade em porta efêmera (`port=0`) e fala com ele por
`http.client` — nenhuma rede externa, nenhum navegador, nenhum banco.
"""

import http.client
import json
from collections.abc import Iterator

import pytest

from jarvis.interface.adapters.http_panel import CONTENT_SECURITY_POLICY, PanelServer
from jarvis.interface.errors import PanelError
from jarvis.interface.live import LiveState
from jarvis.interface.viewmodel import PanelSnapshot, VoiceStatusView, entries_of
from tests.interface_doubles import PANEL_NOW, audit_event


@pytest.fixture
def live() -> LiveState:
    return LiveState()


@pytest.fixture
def panel(live: LiveState) -> Iterator[PanelServer]:
    server = PanelServer(live=live, port=0, stream_timeout=0.2)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def get(panel: PanelServer, path: str) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=5)
    connection.request("GET", path)
    return connection.getresponse()


def send(panel: PanelServer, method: str, path: str = "/") -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection("127.0.0.1", panel.port, timeout=5)
    connection.request(method, path)
    return connection.getresponse()


def full(revision: int = 1) -> PanelSnapshot:
    return PanelSnapshot(
        revision=revision,
        as_of=PANEL_NOW,
        voice=VoiceStatusView(state="listening", at=PANEL_NOW),
        timeline=entries_of([audit_event("action.completed", payload={"skill": "file.write"})]),
    )


# --- construção --------------------------------------------------------------


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.10", "example.com"])
def test_the_panel_refuses_to_serve_outside_loopback(host: str, live: LiveState) -> None:
    # Expor na rede exigiria autenticação, e autenticação é multiusuário — fora
    # do escopo declarado da fase.
    with pytest.raises(PanelError):
        PanelServer(live=live, host=host, port=0)


def test_an_impossible_port_is_refused(live: LiveState) -> None:
    with pytest.raises(PanelError):
        PanelServer(live=live, port=99_999)


def test_the_url_reports_the_port_the_os_actually_gave(panel: PanelServer) -> None:
    assert panel.port > 0
    assert panel.url == f"http://127.0.0.1:{panel.port}"


# --- rotas -------------------------------------------------------------------


def test_the_root_serves_a_self_contained_page(panel: PanelServer) -> None:
    response = get(panel, "/")
    body = response.read().decode("utf-8")

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/html; charset=utf-8"
    assert "<title>Jarvis" in body
    # Autocontida: nada de origem externa, nem script, nem folha de estilo.
    assert "http://" not in body.replace("http://127.0.0.1", "")
    assert "cdn" not in body.lower()


def test_every_response_carries_the_restrictive_headers(panel: PanelServer) -> None:
    response = get(panel, "/")

    assert response.getheader("Content-Security-Policy") == CONTENT_SECURITY_POLICY
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("X-Content-Type-Options") == "nosniff"


def test_the_state_route_returns_the_current_snapshot(panel: PanelServer, live: LiveState) -> None:
    live.publish(full())

    body = json.loads(get(panel, "/api/state").read())

    assert body["revision"] == 1
    assert body["voice"]["state"] == "listening"
    assert body["timeline"][0]["event_type"] == "action.completed"


def test_the_state_route_is_honest_before_the_first_snapshot(panel: PanelServer) -> None:
    body = json.loads(get(panel, "/api/state").read())

    assert body["revision"] == 0
    assert body["degraded"] == ["snapshot"]


def test_healthz_reports_the_revision(panel: PanelServer, live: LiveState) -> None:
    live.publish(full())

    response = get(panel, "/healthz")

    assert response.status == 200
    assert response.read() == b"ok revision=1"


def test_an_unknown_route_is_a_404(panel: PanelServer) -> None:
    assert get(panel, "/nao-existe").status == 404


def test_a_query_string_does_not_confuse_the_router(panel: PanelServer) -> None:
    assert get(panel, "/api/state?x=1").status == 200


# --- somente leitura ---------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("path", ["/", "/api/state", "/qualquer"])
def test_no_route_accepts_a_write(method: str, path: str, panel: PanelServer) -> None:
    """Um painel que executa seria um segundo caminho até a Tool, sem o cuidado
    que o CLI tem. Confirmar ação continua no CLI (ADR-0014) e na voz."""
    assert send(panel, method, path).status == 405


# --- SSE ---------------------------------------------------------------------


def test_the_stream_sends_the_snapshot_and_then_a_heartbeat(
    panel: PanelServer, live: LiveState
) -> None:
    live.publish(full())
    response = get(panel, "/api/stream")

    assert response.status == 200
    assert response.getheader("Content-Type") == "text/event-stream; charset=utf-8"
    assert response.readline() == b"retry: 3000\n"
    response.readline()
    payload = response.readline().decode("utf-8")
    assert payload.startswith("data: ")
    assert json.loads(payload[len("data: ") :])["revision"] == 1

    response.readline()
    assert response.readline() == b": heartbeat\n"
    response.close()


def test_stopping_the_panel_is_idempotent_enough_to_be_safe(live: LiveState) -> None:
    server = PanelServer(live=live, port=0)
    with server:
        assert server.port > 0
    # `stop` já rodou no `__exit__`; chamar de novo não pode explodir o processo
    # que está encerrando.
    assert server.stopping.is_set()
