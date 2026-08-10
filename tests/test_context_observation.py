from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.context.errors import InvalidContextError
from jarvis.context.observation import (
    MAX_LABEL_LENGTH,
    Freshness,
    Observation,
    require_aware,
    require_identifier,
    require_label,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class TestValidators:
    @pytest.mark.parametrize("value", ["busy", "do-not-disturb", "working_hard", "a1"])
    def test_accepts_closed_labels(self, value: str) -> None:
        assert require_label(value, field_name="x") == value

    @pytest.mark.parametrize(
        "value", ["", "Busy", "em reunião", "_busy", "busy_", "busy__hard", "café"]
    )
    def test_rejects_anything_that_is_not_a_label(self, value: str) -> None:
        with pytest.raises(InvalidContextError, match="x"):
            require_label(value, field_name="x")

    def test_rejects_long_labels_so_free_text_cannot_sneak_in(self) -> None:
        with pytest.raises(InvalidContextError, match="excede"):
            require_label("a" * (MAX_LABEL_LENGTH + 1), field_name="x")

    def test_rejects_non_text(self) -> None:
        with pytest.raises(InvalidContextError, match="texto"):
            require_label(7, field_name="x")

    def test_never_repeats_the_rejected_value(self) -> None:
        """A recusa vira log com stack trace no bus: repetir o valor vazaria o payload."""
        with pytest.raises(InvalidContextError) as exc_info:
            require_label("Reunião com Dra. Marina", field_name="payload.activity")

        assert "Marina" not in str(exc_info.value)
        assert "payload.activity" in str(exc_info.value)

    def test_identifier_is_opaque_but_not_blank(self) -> None:
        assert require_identifier("Conv-42/AB", field_name="x") == "Conv-42/AB"
        with pytest.raises(InvalidContextError, match="vazio"):
            require_identifier("   ", field_name="x")

    def test_naive_datetime_is_rejected(self) -> None:
        with pytest.raises(InvalidContextError, match="timezone-aware"):
            require_aware(datetime(2026, 8, 10, 12, 0), field_name="x")


class TestConstruction:
    def test_normalises_observed_at_to_utc(self) -> None:
        sao_paulo = timezone(timedelta(hours=-3))
        observation = Observation(
            value="busy", observed_at=datetime(2026, 8, 10, 9, 0, tzinfo=sao_paulo), source="s"
        )

        assert observation.observed_at == NOON
        assert observation.observed_at.tzinfo is UTC

    def test_rejects_naive_observed_at(self) -> None:
        with pytest.raises(InvalidContextError, match="observed_at"):
            Observation(value="busy", observed_at=datetime(2026, 8, 10, 12, 0), source="s")

    def test_rejects_blank_source(self) -> None:
        with pytest.raises(InvalidContextError, match="source"):
            Observation(value="busy", observed_at=NOON, source="  ")

    @pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
    def test_rejects_confidence_outside_the_unit_interval(self, confidence: float) -> None:
        with pytest.raises(InvalidContextError, match="confidence"):
            Observation(value="busy", observed_at=NOON, source="s", confidence=confidence)

    @pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
    def test_rejects_non_positive_ttl(self, ttl: timedelta) -> None:
        with pytest.raises(InvalidContextError, match="ttl"):
            Observation(value="busy", observed_at=NOON, source="s", ttl=ttl)

    def test_is_immutable(self) -> None:
        observation = Observation(value="busy", observed_at=NOON, source="s")

        with pytest.raises(FrozenInstanceError):
            observation.value = "free"  # type: ignore[misc]

    def test_observed_absence_is_a_value_like_any_other(self) -> None:
        observation: Observation[str | None] = Observation(
            value=None, observed_at=NOON, source="event:user.activity_ended"
        )

        assert observation.value is None
        assert observation.source == "event:user.activity_ended"


class TestFreshness:
    def test_without_ttl_never_goes_stale(self) -> None:
        observation = Observation(value="busy", observed_at=NOON, source="s")

        assert observation.expires_at() is None
        assert observation.freshness(NOON + timedelta(days=3650)) is Freshness.FRESH

    def test_is_fresh_until_the_exact_expiry_instant(self) -> None:
        observation = Observation(
            value="busy", observed_at=NOON, source="s", ttl=timedelta(minutes=15)
        )
        expires_at = NOON + timedelta(minutes=15)

        assert observation.expires_at() == expires_at
        assert observation.freshness(expires_at - timedelta(microseconds=1)) is Freshness.FRESH
        # O instante do vencimento já é stale: o intervalo de validade é semiaberto.
        assert observation.freshness(expires_at) is Freshness.STALE
        assert observation.is_stale(expires_at + timedelta(hours=1))

    def test_stale_value_is_still_readable(self) -> None:
        observation = Observation(
            value="busy", observed_at=NOON, source="s", ttl=timedelta(minutes=1)
        )

        later = NOON + timedelta(hours=2)

        assert observation.is_stale(later)
        # Vencer marca, não descarta (contracts §6).
        assert observation.value == "busy"
        assert observation.source == "s"
