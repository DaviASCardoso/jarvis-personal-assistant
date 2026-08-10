import math
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.embedding import (
    EmbeddingModel,
    MemoryEmbedding,
    cosine_similarity,
    require_aware,
)
from jarvis.memory.errors import InvalidMemoryError

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
MODEL = EmbeddingModel(provider="stub", model="stub-v1", dimensions=3)


class TestEmbeddingModel:
    def test_rejects_blank_provider(self) -> None:
        with pytest.raises(InvalidMemoryError, match="provider"):
            EmbeddingModel(provider="  ", model="v1", dimensions=3)

    def test_rejects_blank_model(self) -> None:
        with pytest.raises(InvalidMemoryError, match="model"):
            EmbeddingModel(provider="stub", model=" ", dimensions=3)

    @pytest.mark.parametrize("dimensions", [0, -1])
    def test_rejects_non_positive_dimensions(self, dimensions: int) -> None:
        with pytest.raises(InvalidMemoryError, match="dimensions"):
            EmbeddingModel(provider="stub", model="v1", dimensions=dimensions)

    def test_equality_is_the_comparability_key(self) -> None:
        assert EmbeddingModel(provider="a", model="v1", dimensions=3) == EmbeddingModel(
            provider="a", model="v1", dimensions=3
        )
        assert EmbeddingModel(provider="a", model="v1", dimensions=3) != EmbeddingModel(
            provider="b", model="v1", dimensions=3
        )


class TestMemoryEmbedding:
    def test_normalises_created_at_to_utc(self) -> None:
        from datetime import timezone

        sao_paulo = timezone(timedelta(hours=-3))
        embedding = MemoryEmbedding(
            vector=(1.0, 0.0, 0.0),
            model=MODEL,
            created_at=datetime(2026, 8, 10, 9, 0, tzinfo=sao_paulo),
        )

        assert embedding.created_at == NOON

    def test_rejects_naive_created_at(self) -> None:
        with pytest.raises(InvalidMemoryError, match="timezone-aware"):
            MemoryEmbedding(vector=(1.0, 0.0, 0.0), model=MODEL, created_at=datetime(2026, 8, 10))

    def test_vector_length_must_match_model_dimensions(self) -> None:
        with pytest.raises(InvalidMemoryError, match="posições"):
            MemoryEmbedding(vector=(1.0, 0.0), model=MODEL, created_at=NOON)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_rejects_non_finite_values(self, bad: float) -> None:
        with pytest.raises(InvalidMemoryError, match="finito"):
            MemoryEmbedding(vector=(bad, 0.0, 0.0), model=MODEL, created_at=NOON)

    def test_is_comparable_to_only_when_model_matches(self) -> None:
        a = MemoryEmbedding(vector=(1.0, 0.0, 0.0), model=MODEL, created_at=NOON)
        same_model = MemoryEmbedding(vector=(0.0, 1.0, 0.0), model=MODEL, created_at=NOON)
        other_model = MemoryEmbedding(
            vector=(1.0, 0.0, 0.0),
            model=EmbeddingModel(provider="other", model="v2", dimensions=3),
            created_at=NOON,
        )

        assert a.is_comparable_to(same_model)
        assert not a.is_comparable_to(other_model)

    def test_require_aware_rejects_non_datetime(self) -> None:
        with pytest.raises(InvalidMemoryError, match="datetime"):
            require_aware("2026-08-10", field_name="x")


class TestCosineSimilarity:
    def test_identical_vectors_score_one(self) -> None:
        assert cosine_similarity((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self) -> None:
        assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self) -> None:
        assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)

    def test_zero_vector_scores_zero_instead_of_dividing_by_zero(self) -> None:
        assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0

    def test_partial_overlap_is_between_zero_and_one(self) -> None:
        score = cosine_similarity((1.0, 1.0), (1.0, 0.0))
        assert 0.0 < score < 1.0
        assert score == pytest.approx(1.0 / math.sqrt(2))

    def test_mismatched_dimensions_is_an_error(self) -> None:
        with pytest.raises(InvalidMemoryError, match="dimensões"):
            cosine_similarity((1.0, 0.0), (1.0, 0.0, 0.0))

    def test_result_is_clamped_to_the_unit_range(self) -> None:
        assert -1.0 <= cosine_similarity((1.0, 2.0), (3.0, -1.0)) <= 1.0
