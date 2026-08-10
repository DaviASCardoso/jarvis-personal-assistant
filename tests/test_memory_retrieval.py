from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.embedding import EmbeddingModel
from jarvis.memory.errors import EmbeddingProviderError, InvalidMemoryError
from jarvis.memory.memory import MemoryType
from jarvis.memory.ports import MemoryCriteria
from jarvis.memory.retrieval import MemoryRetrieval, RetrievalQuery
from tests.memory_doubles import (
    FailingEmbeddingProvider,
    FakeMemoryRepository,
    StubEmbeddingProvider,
    make_embedding,
    make_memory,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)
MODEL = EmbeddingModel(provider="stub", model="stub-v1", dimensions=4)


class TestQueryValidation:
    def test_rejects_non_positive_limit(self) -> None:
        with pytest.raises(InvalidMemoryError, match="limit"):
            RetrievalQuery(limit=0)

    def test_rejects_blank_text(self) -> None:
        with pytest.raises(InvalidMemoryError, match="text"):
            RetrievalQuery(text="   ")

    def test_defaults_are_a_plain_structured_lookup(self) -> None:
        query = RetrievalQuery()
        assert query.text is None
        assert query.limit == 10


class TestStructuredLookup:
    def test_does_not_call_the_embedding_provider(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        provider = StubEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        retrieval.retrieve(RetrievalQuery())

        assert provider.embedded == []

    def test_works_without_any_embedding_provider_configured(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        retrieval = MemoryRetrieval(repository=repository, embeddings=None)

        outcome = retrieval.retrieve(RetrievalQuery())

        assert [item.memory.memory.memory_id for item in outcome.results] == ["a"]
        assert outcome.skipped_incompatible == 0

    def test_applies_the_given_criteria(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(make_memory(memory_id="a", type=MemoryType.EPISODIC), recorded_at=NOON)
        repository.add(make_memory(memory_id="b", type=MemoryType.SEMANTIC), recorded_at=NOON)
        retrieval = MemoryRetrieval(repository=repository)

        outcome = retrieval.retrieve(
            RetrievalQuery(criteria=MemoryCriteria(types=frozenset({MemoryType.SEMANTIC})))
        )

        assert [item.memory.memory.memory_id for item in outcome.results] == ["b"]

    def test_respects_the_query_limit(self) -> None:
        repository = FakeMemoryRepository()
        for index in range(5):
            repository.add(make_memory(memory_id=f"m-{index}"), recorded_at=NOON)
        retrieval = MemoryRetrieval(repository=repository)

        outcome = retrieval.retrieve(RetrievalQuery(limit=2))

        assert len(outcome.results) == 2
        assert outcome.scanned == 5


class TestSemanticRetrieval:
    def test_calls_the_provider_exactly_once(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(
            make_memory(memory_id="a", embedding=make_embedding(model=MODEL)), recorded_at=NOON
        )
        provider = StubEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        retrieval.retrieve(RetrievalQuery(text="python"))

        assert provider.embedded == ["python"]

    def test_requires_a_configured_provider(self) -> None:
        repository = FakeMemoryRepository()
        retrieval = MemoryRetrieval(repository=repository, embeddings=None)

        with pytest.raises(InvalidMemoryError, match="EmbeddingProvider"):
            retrieval.retrieve(RetrievalQuery(text="python"))

    def test_orders_by_similarity_to_the_query(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(
            make_memory(
                memory_id="close", embedding=make_embedding((1.0, 0.0, 0.0, 0.0), model=MODEL)
            ),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(
                memory_id="far", embedding=make_embedding((0.0, 1.0, 0.0, 0.0), model=MODEL)
            ),
            recorded_at=NOON,
        )
        provider = StubEmbeddingProvider(model=MODEL, default_vector=(1.0, 0.0, 0.0, 0.0))
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        outcome = retrieval.retrieve(RetrievalQuery(text="python"))

        assert [item.memory.memory.memory_id for item in outcome.results] == ["close", "far"]
        assert outcome.results[0].score.total > outcome.results[1].score.total

    def test_a_memory_without_embedding_does_not_break_the_query(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(make_memory(memory_id="no-embedding"), recorded_at=NOON)
        repository.add(
            make_memory(memory_id="with-embedding", embedding=make_embedding(model=MODEL)),
            recorded_at=NOON,
        )
        provider = StubEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        outcome = retrieval.retrieve(RetrievalQuery(text="python"))

        assert [item.memory.memory.memory_id for item in outcome.results] == ["with-embedding"]
        assert outcome.skipped_incompatible == 1
        assert outcome.scanned == 2

    def test_incompatible_embedding_model_is_skipped_and_counted(self) -> None:
        other_model = EmbeddingModel(provider="other", model="v2", dimensions=4)
        repository = FakeMemoryRepository()
        repository.add(
            make_memory(memory_id="mismatched", embedding=make_embedding(model=other_model)),
            recorded_at=NOON,
        )
        provider = StubEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        outcome = retrieval.retrieve(RetrievalQuery(text="python"))

        assert outcome.results == ()
        assert outcome.skipped_incompatible == 1

    def test_provider_failure_propagates_without_corrupting_state(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(
            make_memory(memory_id="a", embedding=make_embedding(model=MODEL)), recorded_at=NOON
        )
        provider = FailingEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        with pytest.raises(EmbeddingProviderError):
            retrieval.retrieve(RetrievalQuery(text="python"))

    def test_semantic_query_still_respects_structured_criteria(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(
            make_memory(
                memory_id="episodic",
                type=MemoryType.EPISODIC,
                embedding=make_embedding(model=MODEL),
            ),
            recorded_at=NOON,
        )
        repository.add(
            make_memory(
                memory_id="semantic",
                type=MemoryType.SEMANTIC,
                embedding=make_embedding(model=MODEL),
            ),
            recorded_at=NOON,
        )
        provider = StubEmbeddingProvider(model=MODEL)
        retrieval = MemoryRetrieval(repository=repository, embeddings=provider)

        outcome = retrieval.retrieve(
            RetrievalQuery(
                text="python", criteria=MemoryCriteria(types=frozenset({MemoryType.SEMANTIC}))
            )
        )

        assert [item.memory.memory.memory_id for item in outcome.results] == ["semantic"]


class TestDefaultVigency:
    def test_active_at_in_criteria_excludes_invalidated_and_superseded(self) -> None:
        repository = FakeMemoryRepository()
        repository.add(make_memory(memory_id="a"), recorded_at=NOON)
        repository.invalidate("a", reason="usuário pediu", moment=NOON)
        repository.add(make_memory(memory_id="b"), recorded_at=NOON)
        retrieval = MemoryRetrieval(repository=repository)

        outcome = retrieval.retrieve(RetrievalQuery())

        assert [item.memory.memory.memory_id for item in outcome.results] == ["b"]
