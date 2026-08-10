import logging
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.aggregator import ContextAggregator
from jarvis.context.errors import ContextProviderError
from jarvis.context.model import ContextField, ContextUpdate
from jarvis.context.observation import Freshness
from tests.context_doubles import FailingProvider, StubProvider, frozen_clock, make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


class FlakyProvider:
    """Funciona até `broken` ser ligado — para observar o que sobrevive à falha."""

    def __init__(self, update: ContextUpdate, *, name: str = "location") -> None:
        self._update = update
        self._name = name
        self.broken = False

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        if self.broken:
            raise ContextProviderError("fonte ficou indisponível")
        return self._update


class TestCollection:
    def test_polls_every_provider_with_the_same_instant(self) -> None:
        time_source = StubProvider(ContextUpdate(local_time=make_observation(NOON)), name="time")
        device = StubProvider(ContextUpdate(device_id=make_observation("notebook")), name="device")
        aggregator = ContextAggregator(providers=[time_source, device], clock=frozen_clock(NOON))

        aggregator.refresh()

        assert time_source.observed_with == [NOON]
        assert device.observed_with == [NOON]

    def test_combines_fields_from_independent_sources(self) -> None:
        aggregator = ContextAggregator(
            providers=[
                StubProvider(ContextUpdate(local_time=make_observation(NOON)), name="time"),
                StubProvider(ContextUpdate(place=make_observation("home")), name="location"),
            ],
            clock=frozen_clock(NOON),
        )

        aggregator.refresh()

        context = aggregator.get_current_context()
        assert context.environment.local_time is not None
        assert context.environment.place is not None
        assert context.environment.place.value == "home"

    def test_reports_conflicts_from_the_poll(self) -> None:
        aggregator = ContextAggregator(
            providers=[
                StubProvider(
                    ContextUpdate(place=make_observation("home", observed_at=NOON, source="a")),
                    name="a",
                ),
                StubProvider(
                    ContextUpdate(place=make_observation("work", observed_at=LATER, source="b")),
                    name="b",
                ),
            ],
            clock=frozen_clock(NOON),
        )

        conflicts = aggregator.refresh()

        assert [conflict.field for conflict in conflicts] == [ContextField.PLACE]


class TestProviderFailure:
    def test_declared_failure_degrades_without_stopping_the_others(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        aggregator = ContextAggregator(
            providers=[
                FailingProvider(name="location"),
                StubProvider(ContextUpdate(device_id=make_observation("notebook")), name="device"),
            ],
            clock=frozen_clock(NOON),
        )

        with caplog.at_level(logging.WARNING, logger="jarvis.context.aggregator"):
            aggregator.refresh()

        context = aggregator.get_current_context()
        assert context.device.device_id is not None
        record = next(item for item in caplog.records if item.message == "context.provider_failed")
        assert record.provider == "location"  # type: ignore[attr-defined]
        assert record.error_type == "ContextProviderError"  # type: ignore[attr-defined]

    def test_failure_never_erases_what_was_already_known(self) -> None:
        provider = FlakyProvider(ContextUpdate(place=make_observation("home", observed_at=NOON)))
        aggregator = ContextAggregator(providers=[provider], clock=frozen_clock(NOON))
        aggregator.refresh()

        provider.broken = True
        aggregator.refresh()

        context = aggregator.get_current_context()
        assert context.environment.place is not None
        assert context.environment.place.value == "home"

    def test_untranslated_exception_propagates_instead_of_degrading(self) -> None:
        aggregator = ContextAggregator(
            providers=[FailingProvider(error=RuntimeError("bug no adapter"))],
            clock=frozen_clock(NOON),
        )

        with pytest.raises(RuntimeError, match="bug no adapter"):
            aggregator.refresh()

    def test_provider_error_is_retryable_infrastructure(self) -> None:
        assert ContextProviderError("x").retryable is True


class TestReading:
    def test_get_current_context_does_not_poll(self) -> None:
        provider = StubProvider(ContextUpdate(place=make_observation("home")))
        aggregator = ContextAggregator(providers=[provider], clock=frozen_clock(NOON))

        aggregator.get_current_context()
        aggregator.get_current_context()

        assert provider.observed_with == []

    def test_as_of_comes_from_the_injected_clock(self) -> None:
        aggregator = ContextAggregator(clock=frozen_clock(NOON, LATER))

        assert aggregator.get_current_context().as_of == NOON
        assert aggregator.get_current_context().as_of == LATER

    def test_only_the_clock_makes_a_value_go_stale(self) -> None:
        aggregator = ContextAggregator(
            providers=[
                StubProvider(ContextUpdate(place=make_observation("home", observed_at=NOON)))
            ],
            clock=frozen_clock(NOON, NOON, NOON + timedelta(hours=3)),
        )
        aggregator.refresh()

        fresh = aggregator.get_current_context()
        stale = aggregator.get_current_context()

        assert fresh.environment.place is not None
        assert stale.environment.place is not None
        assert fresh.environment.place.freshness(fresh.as_of) is Freshness.FRESH
        assert stale.environment.place.freshness(stale.as_of) is Freshness.STALE

    def test_apply_incorporates_an_update_from_outside_the_providers(self) -> None:
        aggregator = ContextAggregator(clock=frozen_clock(NOON))

        aggregator.apply(ContextUpdate(availability=make_observation("busy")))

        context = aggregator.get_current_context()
        assert context.user.availability is not None
        assert context.user.availability.value == "busy"

    def test_an_aggregator_without_providers_knows_nothing(self) -> None:
        aggregator = ContextAggregator(clock=frozen_clock(NOON))

        assert aggregator.refresh() == ()
        assert aggregator.get_current_context().user.availability is None
