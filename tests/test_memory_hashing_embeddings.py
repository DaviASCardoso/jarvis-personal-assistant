import pytest

from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.embedding import cosine_similarity
from jarvis.memory.errors import EmbeddingProviderError


class TestDeterminism:
    def test_the_same_text_always_produces_the_same_vector(self) -> None:
        provider = HashingEmbeddingProvider()

        assert provider.embed("prefere python") == provider.embed("prefere python")

    def test_is_stable_across_separate_instances(self) -> None:
        first = HashingEmbeddingProvider().embed("prefere python")
        second = HashingEmbeddingProvider().embed("prefere python")

        assert first == second


class TestShape:
    def test_declares_and_produces_the_configured_dimensions(self) -> None:
        provider = HashingEmbeddingProvider(dimensions=32)

        assert provider.model.dimensions == 32
        assert len(provider.embed("qualquer coisa")) == 32

    def test_model_identity_is_the_hashing_adapter(self) -> None:
        provider = HashingEmbeddingProvider()

        assert provider.model.provider == "hashing"
        assert provider.model.model == "hashing-v1"

    def test_vector_is_l2_normalised(self) -> None:
        vector = HashingEmbeddingProvider().embed("prefere python para scripts")

        norm = sum(value * value for value in vector) ** 0.5
        assert norm == pytest.approx(1.0, abs=1e-6)


class TestBehaviour:
    def test_different_texts_produce_different_vectors(self) -> None:
        provider = HashingEmbeddingProvider()

        assert provider.embed("prefere python") != provider.embed("prefere rust")

    def test_blank_text_is_rejected(self) -> None:
        with pytest.raises(EmbeddingProviderError, match="vazio"):
            HashingEmbeddingProvider().embed("   ")

    def test_normalisation_ignores_case_accent_and_spacing(self) -> None:
        provider = HashingEmbeddingProvider()

        assert provider.embed("Café  Quente") == provider.embed("cafe quente")

    def test_lexical_overlap_scores_higher_than_no_overlap(self) -> None:
        provider = HashingEmbeddingProvider()

        base = provider.embed("prefere python para automação de scripts")
        overlapping = provider.embed("prefere python para escrever scripts")
        unrelated = provider.embed("o clima hoje está nublado em Lisboa")

        assert cosine_similarity(base, overlapping) > cosine_similarity(base, unrelated)

    def test_short_words_still_produce_a_usable_vector(self) -> None:
        provider = HashingEmbeddingProvider()

        vector = provider.embed("ok")

        assert any(value != 0.0 for value in vector)
