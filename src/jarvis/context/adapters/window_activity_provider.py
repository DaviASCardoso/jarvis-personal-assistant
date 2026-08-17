"""Window Activity Provider: aplicação e janela em primeiro plano (Fase 8.1).

Windows-only de verdade: fora do Windows, degrada para ausência silenciosa —
mesmo tratamento que a Fase 2 já deu a Location, e pelo mesmo motivo (nenhuma
fonte segura existe). A chamada ao sistema operacional é **injetável**:
nenhum teste chama `ctypes` de verdade, mesmo desenho de
`LocalDeviceProvider(hostname: Callable[[], str] = platform.node)`.

`ctypes.windll` só é acessado **dentro** de uma função, nunca no nível do
módulo — é o que permite importar este arquivo em qualquer sistema
operacional sem erro; só chamá-lo fora do Windows falharia, e por isso a
função real nunca é chamada fora dele.
"""

import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation

MAX_TITLE_LENGTH = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class ForegroundWindow:
    application: str
    title: str


def _process_name(pid: int) -> str:
    import psutil

    try:
        name: str = psutil.Process(pid).name()
    except psutil.Error:
        return ""
    return name


def _read_foreground_window_windows() -> ForegroundWindow | None:
    """Implementação real. Só é chamada quando `platform.system() == "Windows"`.

    `getattr(ctypes, "windll")` em vez de `ctypes.windll`: o stub de tipos da
    stdlib só declara `windll` condicionalmente para `sys.platform == "win32"`,
    e este módulo precisa tipar limpo tanto no Windows (onde é desenvolvido)
    quanto no Linux (onde o CI roda) — `getattr` devolve `Any` nos dois,
    sem exigir um `# type: ignore` que seria "não utilizado" numa das plataformas.
    """
    import ctypes
    from ctypes import wintypes

    user32 = getattr(ctypes, "windll").user32  # noqa: B009 - deliberado, ver docstring

    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    return ForegroundWindow(application=_process_name(pid.value), title=buffer.value)


def _default_read_foreground_window() -> ForegroundWindow | None:
    if platform.system() != "Windows":
        return None
    return _read_foreground_window_windows()


class WindowActivityProvider:
    def __init__(
        self,
        *,
        read_foreground_window: Callable[
            [], ForegroundWindow | None
        ] = _default_read_foreground_window,
        name: str = "window_activity",
    ) -> None:
        self._read = read_foreground_window
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        try:
            window = self._read()
        except OSError as error:
            raise ContextProviderError(
                "não foi possível observar a janela em primeiro plano"
            ) from error

        if window is None or not window.application.strip():
            return ContextUpdate()

        source = f"provider:{self._name}"
        title = window.title.strip()[:MAX_TITLE_LENGTH]
        return ContextUpdate(
            active_application=Observation(
                value=window.application, observed_at=now, source=source
            ),
            active_window_title=(
                Observation(value=title, observed_at=now, source=source) if title else None
            ),
        )
