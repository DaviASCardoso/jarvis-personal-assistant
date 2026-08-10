from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.context.adapters.device_provider import LocalDeviceProvider
from jarvis.context.adapters.time_provider import SystemTimeProvider
from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextUpdate
from jarvis.context.ports import ContextProvider
from tests.context_doubles import StubProvider, make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SAO_PAULO = timezone(timedelta(hours=-3))


class TestSystemTimeProvider:
    def test_reports_the_instant_it_was_given(self) -> None:
        update = SystemTimeProvider().observe(NOON)

        assert update.local_time is not None
        assert update.local_time.observed_at == NOON
        assert update.local_time.source == "provider:time"

    def test_converts_the_value_to_the_injected_zone(self) -> None:
        update = SystemTimeProvider(time_zone=SAO_PAULO).observe(NOON)

        assert update.local_time is not None
        assert update.local_time.value == datetime(2026, 8, 10, 9, 0, tzinfo=SAO_PAULO)
        # O valor guarda o offset local; o metadado é sempre UTC.
        assert update.local_time.value.utcoffset() == timedelta(hours=-3)
        assert update.local_time.observed_at.tzinfo is UTC

    def test_never_reads_the_real_clock(self) -> None:
        """Duas observações do mesmo instante são idênticas — nada de `now()` interno."""
        provider = SystemTimeProvider(time_zone=UTC)

        first = provider.observe(NOON)
        second = provider.observe(NOON)

        assert first == second

    def test_speaks_only_about_its_own_field(self) -> None:
        update = SystemTimeProvider().observe(NOON)

        assert update.device_id is None
        assert update.availability is None


class TestLocalDeviceProvider:
    def test_reports_the_hostname(self) -> None:
        update = LocalDeviceProvider(hostname=lambda: "notebook").observe(NOON)

        assert update.device_id is not None
        assert update.device_id.value == "notebook"
        assert update.device_id.source == "provider:device"
        assert update.device_id.observed_at == NOON

    @pytest.mark.parametrize("unknown", ["", "   "])
    def test_unknown_hostname_stays_absent_instead_of_being_invented(self, unknown: str) -> None:
        update = LocalDeviceProvider(hostname=lambda: unknown).observe(NOON)

        assert update.is_empty()

    def test_native_failure_is_translated_to_the_core_taxonomy(self) -> None:
        def broken() -> str:
            raise OSError("sem acesso ao hostname")

        with pytest.raises(ContextProviderError) as exc_info:
            LocalDeviceProvider(hostname=broken).observe(NOON)

        assert isinstance(exc_info.value.__cause__, OSError)
        assert exc_info.value.retryable is True

    def test_uses_the_standard_library_by_default(self) -> None:
        update = LocalDeviceProvider().observe(NOON)

        assert update.local_time is None
        if update.device_id is not None:
            assert update.device_id.value.strip()


def test_the_port_accepts_sources_without_an_adapter_in_src() -> None:
    """Activity, Calendar e Location existem como port + double, não como integração."""
    sources: list[ContextProvider] = [
        SystemTimeProvider(),
        LocalDeviceProvider(hostname=lambda: "notebook"),
        StubProvider(ContextUpdate(activity=make_observation("working")), name="activity"),
        StubProvider(ContextUpdate(next_entry_at=make_observation(NOON)), name="calendar"),
        StubProvider(ContextUpdate(place=make_observation("home")), name="location"),
    ]

    updates = [provider.observe(NOON) for provider in sources]

    assert [provider.name for provider in sources] == [
        "time",
        "device",
        "activity",
        "calendar",
        "location",
    ]
    assert not any(update.is_empty() for update in updates)
