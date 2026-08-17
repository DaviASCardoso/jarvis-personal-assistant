"""Testes dos Computer Context Providers (Fase 8.1).

Nenhum teste toca `ctypes`, `psutil` real ou `subprocess` de verdade — todas
as chamadas ao sistema operacional são injetadas, mesmo desenho de
`LocalDeviceProvider(hostname=...)` (2.2). A única exceção é um teste de
fumaça por provider, que chama o adapter real e tolera qualquer resultado —
mesmo padrão de `test_uses_the_standard_library_by_default`.
"""

from datetime import UTC, datetime

import psutil
import pytest

from jarvis.context.adapters.process_activity_provider import ProcessActivityProvider
from jarvis.context.adapters.resource_usage_provider import ResourceUsageProvider
from jarvis.context.adapters.window_activity_provider import (
    ForegroundWindow,
    WindowActivityProvider,
)
from jarvis.context.errors import ContextProviderError

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class TestWindowActivityProvider:
    def test_reports_application_and_title(self) -> None:
        window = ForegroundWindow(application="notepad.exe", title="untitled - Notepad")
        update = WindowActivityProvider(read_foreground_window=lambda: window).observe(NOON)

        assert update.active_application is not None
        assert update.active_application.value == "notepad.exe"
        assert update.active_application.source == "provider:window_activity"
        assert update.active_window_title is not None
        assert update.active_window_title.value == "untitled - Notepad"

    def test_no_foreground_window_is_absence(self) -> None:
        update = WindowActivityProvider(read_foreground_window=lambda: None).observe(NOON)
        assert update.is_empty()

    def test_empty_application_name_is_absence(self) -> None:
        window = ForegroundWindow(application="  ", title="something")
        update = WindowActivityProvider(read_foreground_window=lambda: window).observe(NOON)
        assert update.is_empty()

    def test_blank_title_does_not_produce_an_observation(self) -> None:
        window = ForegroundWindow(application="app.exe", title="   ")
        update = WindowActivityProvider(read_foreground_window=lambda: window).observe(NOON)

        assert update.active_application is not None
        assert update.active_window_title is None

    def test_long_title_is_truncated(self) -> None:
        window = ForegroundWindow(application="app.exe", title="x" * 500)
        update = WindowActivityProvider(read_foreground_window=lambda: window).observe(NOON)

        assert update.active_window_title is not None
        assert len(update.active_window_title.value) == 200

    def test_native_failure_is_translated_to_the_core_taxonomy(self) -> None:
        def broken() -> ForegroundWindow | None:
            raise OSError("sem acesso à API de janelas")

        with pytest.raises(ContextProviderError) as exc_info:
            WindowActivityProvider(read_foreground_window=broken).observe(NOON)

        assert isinstance(exc_info.value.__cause__, OSError)

    def test_uses_the_standard_library_by_default(self) -> None:
        update = WindowActivityProvider().observe(NOON)
        if update.active_application is not None:
            assert update.active_application.value.strip()


class TestResourceUsageProvider:
    def _provider(self, **overrides: object) -> ResourceUsageProvider:
        defaults: dict[str, object] = {
            "cpu_percent": lambda: 12.5,
            "memory_percent": lambda: 48.0,
            "network_connected": lambda: True,
            "idle_seconds": lambda: 3.0,
            "gpu_percent": lambda: 7.0,
        }
        defaults.update(overrides)
        return ResourceUsageProvider(**defaults)  # type: ignore[arg-type]

    def test_reports_every_metric_when_available(self) -> None:
        update = self._provider().observe(NOON)

        assert update.cpu_percent is not None and update.cpu_percent.value == 12.5
        assert update.memory_percent is not None and update.memory_percent.value == 48.0
        assert update.network_connected is not None and update.network_connected.value is True
        assert update.idle_seconds is not None and update.idle_seconds.value == 3.0
        assert update.gpu_percent is not None and update.gpu_percent.value == 7.0
        assert update.cpu_percent.source == "provider:resource_usage"

    def test_one_metric_failing_does_not_affect_the_others(self) -> None:
        def broken_gpu() -> float | None:
            raise psutil.Error("indisponível")

        update = self._provider(gpu_percent=broken_gpu).observe(NOON)

        assert update.gpu_percent is None
        assert update.cpu_percent is not None
        assert update.memory_percent is not None

    def test_gpu_and_idle_absent_independently(self) -> None:
        update = self._provider(gpu_percent=lambda: None, idle_seconds=lambda: None).observe(NOON)

        assert update.gpu_percent is None
        assert update.idle_seconds is None
        assert update.cpu_percent is not None

    def test_os_error_degrades_the_single_metric(self) -> None:
        def broken() -> float:
            raise OSError("sem permissão")

        update = self._provider(cpu_percent=broken).observe(NOON)
        assert update.cpu_percent is None
        assert update.memory_percent is not None

    def test_uses_the_standard_library_by_default(self) -> None:
        update = ResourceUsageProvider().observe(NOON)
        if update.cpu_percent is not None:
            assert 0.0 <= update.cpu_percent.value <= 100.0


class TestProcessActivityProvider:
    def test_empty_allowlist_is_absence(self) -> None:
        update = ProcessActivityProvider(running_process_names=lambda: ["python.exe"]).observe(NOON)
        assert update.is_empty()

    def test_counts_matching_processes_case_insensitively(self) -> None:
        provider = ProcessActivityProvider(
            relevant_process_names=frozenset({"Zoom.exe"}),
            running_process_names=lambda: ["zoom.exe", "notepad.exe", "ZOOM.EXE"],
        )
        update = provider.observe(NOON)

        assert update.relevant_process_count is not None
        assert update.relevant_process_count.value == 2

    def test_no_matching_processes_reports_zero_not_absence(self) -> None:
        provider = ProcessActivityProvider(
            relevant_process_names=frozenset({"zoom.exe"}),
            running_process_names=lambda: ["notepad.exe"],
        )
        update = provider.observe(NOON)

        assert update.relevant_process_count is not None
        assert update.relevant_process_count.value == 0

    def test_failure_enumerating_processes_is_absence(self) -> None:
        def broken() -> list[str]:
            raise psutil.Error("falha ao enumerar processos")

        provider = ProcessActivityProvider(
            relevant_process_names=frozenset({"zoom.exe"}), running_process_names=broken
        )
        assert provider.observe(NOON).is_empty()

    def test_uses_the_standard_library_by_default(self) -> None:
        provider = ProcessActivityProvider(relevant_process_names=frozenset({"__no_such_proc__"}))
        update = provider.observe(NOON)
        assert update.relevant_process_count is not None
        assert update.relevant_process_count.value == 0
