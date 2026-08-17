"""Resource Usage Provider: CPU, RAM, GPU, rede e ociosidade (Fase 8.1).

Quatro mecanismos independentes, e a independência é deliberada: perder um
não derruba os outros três.

- **CPU/RAM/rede** — `psutil`, multiplataforma; funciona igual em CI
  headless, sem hardware nem driver.
- **Ociosidade** — `ctypes GetLastInputInfo`, Windows-only.
- **GPU** — `Get-Counter` do PowerShell sobre o contador
  `\\GPU Engine(*)\\Utilization Percentage` (Windows 10 1803+), sem SDK de
  vendor. Comando **fixo**, sem interpolação de nenhum valor — sem
  superfície de injeção. Melhor esforço: nem todo driver publica o contador,
  e a ausência vira campo ausente, nunca um número inventado.

Cada leitura é tentada **independentemente**; uma falha esperada (permissão,
contador ausente, comando indisponível) vira ausência daquele campo só, não
`ContextProviderError` do provider inteiro — o contrato de "qualquer outra
exceção propaga" continua valendo para o que não é esperado.
"""

import platform
import subprocess
from collections.abc import Callable
from datetime import datetime

import psutil

from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation

GPU_COMMAND_TIMEOUT_SECONDS = 5.0

_GPU_POWERSHELL_SCRIPT = (
    "$ErrorActionPreference = 'SilentlyContinue'; "
    "$samples = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage' "
    "-ErrorAction SilentlyContinue).CounterSamples; "
    "if ($samples) { "
    "$sum = ($samples | Measure-Object -Property CookedValue -Sum).Sum; "
    "[Math]::Round([Math]::Min(100, $sum), 1) "
    "}"
)


def _try[T](read: Callable[[], T]) -> T | None:
    try:
        return read()
    except (OSError, psutil.Error, subprocess.SubprocessError, ValueError):
        return None


def _default_cpu_percent() -> float:
    """`interval=None`: instantâneo, sem bloquear o refresh do contexto —
    devolve a média desde a última chamada (0.0 na primeira, do processo)."""
    percent: float = psutil.cpu_percent(interval=None)
    return percent


def _default_memory_percent() -> float:
    percent: float = psutil.virtual_memory().percent
    return percent


def _default_network_connected() -> bool:
    return any(stats.isup for stats in psutil.net_if_stats().values())


def _idle_seconds_windows() -> float:
    """`getattr(ctypes, "windll")`: ver docstring equivalente em
    `window_activity_provider.py` — evita `# type: ignore` que seria "não
    utilizado" dependendo da plataforma em que o mypy roda."""
    import ctypes
    from ctypes import wintypes

    class _LastInputInfo(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))

    windll = getattr(ctypes, "windll")  # noqa: B009 - deliberado, ver docstring
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo falhou")
    millis_idle = int(windll.kernel32.GetTickCount()) - int(info.dwTime)
    return float(max(0.0, millis_idle / 1000.0))


def _default_idle_seconds() -> float | None:
    if platform.system() != "Windows":
        return None
    return _idle_seconds_windows()


def _gpu_percent_windows() -> float | None:
    # argv fixo, sem `shell=True` e sem nenhuma entrada externa interpolada —
    # sem superfície de injeção de comando.
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _GPU_POWERSHELL_SCRIPT],
        capture_output=True,
        text=True,
        timeout=GPU_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    output = result.stdout.strip()
    if not output:
        return None
    return float(output)


def _default_gpu_percent() -> float | None:
    if platform.system() != "Windows":
        return None
    return _gpu_percent_windows()


class ResourceUsageProvider:
    def __init__(
        self,
        *,
        cpu_percent: Callable[[], float] = _default_cpu_percent,
        memory_percent: Callable[[], float] = _default_memory_percent,
        network_connected: Callable[[], bool] = _default_network_connected,
        idle_seconds: Callable[[], float | None] = _default_idle_seconds,
        gpu_percent: Callable[[], float | None] = _default_gpu_percent,
        name: str = "resource_usage",
    ) -> None:
        self._cpu_percent = cpu_percent
        self._memory_percent = memory_percent
        self._network_connected = network_connected
        self._idle_seconds = idle_seconds
        self._gpu_percent = gpu_percent
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        source = f"provider:{self._name}"

        def observation[T](value: T | None) -> Observation[T] | None:
            if value is None:
                return None
            return Observation(value=value, observed_at=now, source=source)

        cpu = _try(self._cpu_percent)
        memory = _try(self._memory_percent)
        network = _try(self._network_connected)
        idle = _try(self._idle_seconds)
        gpu = _try(self._gpu_percent)

        return ContextUpdate(
            cpu_percent=observation(cpu),
            memory_percent=observation(memory),
            network_connected=observation(network),
            idle_seconds=observation(idle),
            gpu_percent=observation(gpu),
        )
