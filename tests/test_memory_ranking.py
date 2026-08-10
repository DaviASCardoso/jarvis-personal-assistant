from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import MemoryType, StoredMemory
from jarvis.memory.ranking import (
    DEFAULT_HALF_LIVES,
    DEFAULT_RANKING_WEIGHTS,
    RankingWeights,
    recency_score,
    score,
)
from tests.memory_doubles import make_memory

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def stored(**overrides: object) -> StoredMemory:
    defaults: dict[str, object] = {
        "memory": make_memory(),
        "recorded_at": NOON,
        "updated_at": NOON,
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return StoredMemory(**defaults)  # type: ignore[arg-type]


class TestRankingWeights:
    def test_defaults_sum_to_one(self) -> None:
        weights = DEFAULT_RANKING_WEIGHTS
        assert (
            weights.semantic + weights.recency + weights.importance + weights.confidence
            == pytest.approx(1.0)
        )

    @pytest.mark.parametrize("field", ["semantic", "recency", "importance", "confidence"])
    def test_rejects_negative_weights(self, field: str) -> None:
        with pytest.raises(InvalidMemoryError, match=field):
            RankingWeights(**{field: -0.1})

    def test_rejects_all_non_semantic_weights_being_zero(self) -> None:
        with pytest.raises(InvalidMemoryError, match="renormalizar"):
            RankingWeights(recency=0.0, importance=0.0, confidence=0.0)


class TestHalfLives:
    def test_every_memory_type_has_a_half_life(self) -> None:
        for memory_type in MemoryType:
            assert DEFAULT_HALF_LIVES[memory_type] > timedelta(0)

    def test_half_lives_differ_by_type(self) -> None:
        assert DEFAULT_HALF_LIVES[MemoryType.WORKING] < DEFAULT_HALF_LIVES[MemoryType.TASK]
        assert DEFAULT_HALF_LIVES[MemoryType.TASK] < DEFAULT_HALF_LIVES[MemoryType.EPISODIC]
        assert DEFAULT_HALF_LIVES[MemoryType.EPISODIC] < DEFAULT_HALF_LIVES[MemoryType.PREFERENCE]
        assert DEFAULT_HALF_LIVES[MemoryType.PREFERENCE] < DEFAULT_HALF_LIVES[MemoryType.SEMANTIC]


class TestRecencyScore:
    def test_is_one_at_the_moment_of_the_update(self) -> None:
        item = stored(updated_at=NOON)
        assert recency_score(item, now=NOON) == pytest.approx(1.0)

    def test_is_exactly_half_at_the_half_life(self) -> None:
        half_life = DEFAULT_HALF_LIVES[MemoryType.EPISODIC]
        item = stored(updated_at=NOON)

        assert recency_score(item, now=NOON + half_life) == pytest.approx(0.5)

    def test_decays_further_at_twice_the_half_life(self) -> None:
        half_life = DEFAULT_HALF_LIVES[MemoryType.EPISODIC]
        item = stored(updated_at=NOON)

        assert recency_score(item, now=NOON + 2 * half_life) == pytest.approx(0.25)

    def test_half_life_depends_on_type(self) -> None:
        one_day = timedelta(days=1)
        working = stored(
            memory=make_memory(type=MemoryType.WORKING, valid_until=NOON + timedelta(days=30)),
            updated_at=NOON,
        )
        semantic = stored(memory=make_memory(type=MemoryType.SEMANTIC), updated_at=NOON)

        assert recency_score(working, now=NOON + one_day) < recency_score(
            semantic, now=NOON + one_day
        )

    def test_never_negative_even_if_now_precedes_updated_at(self) -> None:
        item = stored(updated_at=NOON)
        assert recency_score(item, now=NOON - timedelta(days=1)) == pytest.approx(1.0)

    def test_unmapped_type_is_an_error(self) -> None:
        item = stored(updated_at=NOON)
        with pytest.raises(InvalidMemoryError, match="meia-vida"):
            recency_score(item, now=NOON, half_lives={})


class TestScoreComposition:
    def test_total_is_within_the_unit_interval(self) -> None:
        item = stored(memory=make_memory(importance=0.9), confidence=0.9, updated_at=NOON)
        result = score(item, now=NOON)
        assert 0.0 <= result.total <= 1.0

    def test_without_semantic_the_term_is_none_and_the_rest_is_renormalised(self) -> None:
        item = stored(memory=make_memory(importance=1.0), confidence=1.0, updated_at=NOON)

        result = score(item, now=NOON)

        assert result.semantic is None
        # recency=1.0, importance=1.0, confidence=1.0 → total deveria ser 1.0
        # mesmo sem o termo semântico, porque os pesos restantes foram renormalizados.
        assert result.total == pytest.approx(1.0)

    def test_with_semantic_it_contributes_to_the_total(self) -> None:
        item = stored(
            memory=make_memory(importance=0.0),
            confidence=0.0,
            updated_at=NOON - timedelta(days=3650),
        )

        without = score(item, now=NOON, semantic=None)
        with_high_semantic = score(item, now=NOON, semantic=1.0)

        assert with_high_semantic.total > without.total

    def test_negative_cosine_is_clamped_to_zero(self) -> None:
        item = stored(memory=make_memory(importance=0.5), confidence=0.5, updated_at=NOON)

        result = score(item, now=NOON, semantic=-0.8)

        assert result.semantic == 0.0

    def test_recency_anchors_on_updated_at_not_last_accessed_at(self) -> None:
        """Consultar não é evidência nova — só `reinforce`/criação rejuvenescem."""
        never_accessed = stored(updated_at=NOON)
        recently_accessed = stored(updated_at=NOON, last_accessed_at=NOON)

        much_later = NOON + DEFAULT_HALF_LIVES[MemoryType.EPISODIC]

        assert recency_score(never_accessed, now=much_later) == recency_score(
            recently_accessed, now=much_later
        )

    def test_importance_and_confidence_are_reported_verbatim(self) -> None:
        item = stored(memory=make_memory(importance=0.37), confidence=0.62, updated_at=NOON)

        result = score(item, now=NOON)

        assert result.importance == 0.37
        assert result.confidence == 0.62

    def test_custom_weights_are_honoured(self) -> None:
        item = stored(memory=make_memory(importance=1.0), confidence=0.0, updated_at=NOON)
        heavy_importance = RankingWeights(semantic=0.0, recency=0.0, importance=1.0, confidence=0.0)

        result = score(item, now=NOON, weights=heavy_importance)

        assert result.total == pytest.approx(1.0)


class TestDeterminism:
    def test_scoring_the_same_memory_twice_gives_the_same_result(self) -> None:
        item = stored(memory=make_memory(importance=0.4), confidence=0.6, updated_at=NOON)

        first = score(item, now=NOON + timedelta(hours=5))
        second = score(item, now=NOON + timedelta(hours=5))

        assert first == second
