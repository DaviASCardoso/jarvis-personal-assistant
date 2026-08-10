from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memory.consolidation import find_contradiction, find_duplicate, find_promotions
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import Memory, MemoryOrigin, MemoryType, Provenance, StoredMemory
from jarvis.memory.ports import MemoryCriteria
from tests.memory_doubles import (
    FailingEmbeddingProvider,
    FakeMemoryRepository,
    StubEmbeddingProvider,
    frozen_clock,
    make_memory,
)

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


def add(repository: FakeMemoryRepository, memory: Memory) -> StoredMemory:
    return repository.add(memory, recorded_at=NOON)


def all_of(repository: FakeMemoryRepository) -> list[StoredMemory]:
    """Todas as linhas, ativas ou não — para exercitar os filtros de
    `find_duplicate`/`find_promotions` sem depender do estado interno do double."""
    return list(
        repository.search(MemoryCriteria(include_invalidated=True, include_superseded=True))
    )


def episodic(
    *, subject: str = "s", content: str = "c", reference: str, confidence: float = 0.8
) -> Memory:
    return make_memory(
        type=MemoryType.EPISODIC,
        subject=subject,
        content=content,
        provenance=Provenance(origin=MemoryOrigin.EVENT, reference=reference),
        confidence=confidence,
    )


class TestFindDuplicate:
    def test_same_type_subject_and_content_is_a_duplicate(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(
            repository,
            make_memory(
                type=MemoryType.PREFERENCE,
                subject="preference.language",
                content="prefere python",
            ),
        )
        candidate = make_memory(
            type=MemoryType.PREFERENCE, subject="preference.language", content="Prefere Python"
        )

        assert find_duplicate(candidate, [existing], now=NOON) is existing

    def test_different_content_is_not_a_duplicate(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(
            repository,
            make_memory(
                type=MemoryType.PREFERENCE,
                subject="preference.language",
                content="prefere python",
            ),
        )
        candidate = make_memory(
            type=MemoryType.PREFERENCE, subject="preference.language", content="prefere rust"
        )

        assert find_duplicate(candidate, [existing], now=NOON) is None

    def test_different_scope_is_not_a_duplicate(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(
            repository,
            make_memory(type=MemoryType.TASK, scope="task-1", content="mesmo conteúdo"),
        )
        candidate = make_memory(type=MemoryType.TASK, scope="task-2", content="mesmo conteúdo")

        assert find_duplicate(candidate, [existing], now=NOON) is None

    def test_inactive_existing_memory_is_not_a_duplicate(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(repository, make_memory(content="mesmo conteúdo"))
        repository.invalidate(existing.memory.memory_id, reason="x", moment=NOON)
        candidate = make_memory(content="mesmo conteúdo")

        assert find_duplicate(candidate, all_of(repository), now=NOON) is None


class TestFindContradiction:
    def test_same_subject_different_content_is_a_contradiction(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(
            repository,
            make_memory(
                type=MemoryType.PREFERENCE,
                subject="preference.language",
                content="prefere python",
            ),
        )
        candidate = make_memory(
            type=MemoryType.PREFERENCE, subject="preference.language", content="prefere rust"
        )

        assert find_contradiction(candidate, [existing], now=NOON) is existing

    def test_without_a_subject_nothing_ever_contradicts(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(repository, make_memory(content="fato a"))
        candidate = make_memory(content="fato b")

        assert find_contradiction(candidate, [existing], now=NOON) is None

    def test_same_content_is_not_a_contradiction(self) -> None:
        repository = FakeMemoryRepository()
        existing = add(
            repository, make_memory(subject="preference.language", content="prefere python")
        )
        candidate = make_memory(subject="preference.language", content="prefere python")

        assert find_contradiction(candidate, [existing], now=NOON) is None

    def test_lower_confidence_still_contradicts(self) -> None:
        """A memória mais nova ganha vigência por ser mais nova, não por confiança."""
        repository = FakeMemoryRepository()
        existing = add(
            repository,
            make_memory(subject="preference.language", content="prefere python", confidence=0.9),
        )
        candidate = make_memory(
            subject="preference.language", content="prefere rust", confidence=0.3
        )

        assert find_contradiction(candidate, [existing], now=NOON) is existing


class TestFindPromotions:
    def test_promotes_after_three_occurrences_from_two_references(self) -> None:
        repository = FakeMemoryRepository()
        for reference in ("evt-1", "evt-2", "evt-2"):
            add(repository, episodic(reference=reference))

        promotions = find_promotions(all_of(repository), now=NOON)

        assert len(promotions) == 1
        assert promotions[0].subject == "s"
        assert len(promotions[0].contributors) == 3

    def test_does_not_promote_below_the_occurrence_threshold(self) -> None:
        repository = FakeMemoryRepository()
        for reference in ("evt-1", "evt-2"):
            add(repository, episodic(reference=reference))

        assert find_promotions(all_of(repository), now=NOON) == ()

    def test_does_not_promote_from_a_single_reference(self) -> None:
        repository = FakeMemoryRepository()
        for _ in range(3):
            add(repository, episodic(reference="evt-1"))

        assert find_promotions(all_of(repository), now=NOON) == ()

    def test_without_a_subject_nothing_is_promoted(self) -> None:
        repository = FakeMemoryRepository()
        for reference in ("evt-1", "evt-2", "evt-3"):
            add(
                repository,
                make_memory(
                    type=MemoryType.EPISODIC,
                    content="c",
                    provenance=Provenance(origin=MemoryOrigin.EVENT, reference=reference),
                ),
            )

        assert find_promotions(all_of(repository), now=NOON) == ()

    def test_confidence_grows_with_repetition_but_caps(self) -> None:
        repository = FakeMemoryRepository()
        for index, reference in enumerate(("evt-1", "evt-2", "evt-3", "evt-4", "evt-5")):
            add(repository, episodic(reference=reference, confidence=0.9 + index * 0.001))

        promotions = find_promotions(all_of(repository), now=NOON)

        assert promotions[0].confidence <= 0.95

    def test_is_idempotent_once_the_semantic_memory_exists(self) -> None:
        repository = FakeMemoryRepository()
        for reference in ("evt-1", "evt-2", "evt-2"):
            add(repository, episodic(reference=reference))
        add(
            repository,
            make_memory(
                type=MemoryType.SEMANTIC,
                subject="s",
                content="c",
                provenance=Provenance(origin=MemoryOrigin.SYSTEM),
            ),
        )

        assert find_promotions(all_of(repository), now=NOON) == ()


class TestMemoryManagerRemember:
    def test_a_new_memory_is_created(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))

        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        assert stored.memory.content == "prefere python"
        assert repository.get(stored.memory.memory_id) == stored

    def test_a_duplicate_reinforces_instead_of_creating(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))

        first = manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
            confidence=0.5,
        )
        second = manager.remember(
            type=MemoryType.PREFERENCE,
            content="Prefere Python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
        )

        assert second.memory.memory_id == first.memory.memory_id
        assert second.reinforced_count == 1
        assert second.confidence > first.confidence
        assert len(all_of(repository)) == 1

    def test_identical_content_from_a_different_origin_is_not_a_duplicate(self) -> None:
        """Duplicata é a **mesma fonte** reafirmando o mesmo fato — reprocessar um
        evento. Duas fontes distintas dizendo a mesma coisa são ocorrências
        genuinamente separadas, e é isso que sustenta a contagem de promoção
        (§16.4): sem essa distinção, nenhum padrão episódico chegaria a 3 linhas."""
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))

        first = manager.remember(
            type=MemoryType.EPISODIC,
            content="chegou atrasado",
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference="evt-1"),
            subject="pattern.lateness",
        )
        second = manager.remember(
            type=MemoryType.EPISODIC,
            content="chegou atrasado",
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference="evt-2"),
            subject="pattern.lateness",
        )

        assert second.memory.memory_id != first.memory.memory_id
        assert len(all_of(repository)) == 2

    def test_reprocessing_the_same_reference_still_reinforces(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))

        first = manager.remember(
            type=MemoryType.EPISODIC,
            content="chegou atrasado",
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference="evt-1"),
            subject="pattern.lateness",
        )
        second = manager.remember(
            type=MemoryType.EPISODIC,
            content="chegou atrasado",
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference="evt-1"),
            subject="pattern.lateness",
        )

        assert second.memory.memory_id == first.memory.memory_id
        assert len(all_of(repository)) == 1

    def test_a_contradiction_supersedes_the_previous_memory(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER))

        first = manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
        )
        second = manager.remember(
            type=MemoryType.PREFERENCE,
            content="prefere rust",
            provenance=Provenance(origin=MemoryOrigin.USER),
            subject="preference.language",
        )

        superseded = repository.get(first.memory.memory_id)
        assert superseded is not None
        assert superseded.superseded_by == second.memory.memory_id
        assert superseded.memory.valid_until == second.memory.valid_from

    def test_working_memory_is_not_embedded_by_default(self) -> None:
        repository = FakeMemoryRepository()
        provider = StubEmbeddingProvider()
        manager = MemoryManager(
            repository=repository, embeddings=provider, clock=frozen_clock(NOON)
        )

        stored = manager.remember(
            type=MemoryType.WORKING,
            content="lembrete temporário",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="x"),
            confidence=0.5,
            valid_until=NOON + timedelta(hours=2),
        )

        assert stored.memory.embedding is None
        assert provider.embedded == []

    def test_embed_true_overrides_the_working_default(self) -> None:
        repository = FakeMemoryRepository()
        provider = StubEmbeddingProvider()
        manager = MemoryManager(
            repository=repository, embeddings=provider, clock=frozen_clock(NOON)
        )

        stored = manager.remember(
            type=MemoryType.WORKING,
            content="lembrete temporário",
            provenance=Provenance(origin=MemoryOrigin.AGENT, reference="x"),
            confidence=0.5,
            valid_until=NOON + timedelta(hours=2),
            embed=True,
        )

        assert stored.memory.embedding is not None

    def test_non_working_memory_is_embedded_when_a_provider_exists(self) -> None:
        repository = FakeMemoryRepository()
        provider = StubEmbeddingProvider()
        manager = MemoryManager(
            repository=repository, embeddings=provider, clock=frozen_clock(NOON)
        )

        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        assert stored.memory.embedding is not None
        assert provider.embedded == ["prefere python"]

    def test_provider_failure_degrades_to_no_embedding(self) -> None:
        repository = FakeMemoryRepository()
        provider = FailingEmbeddingProvider()
        manager = MemoryManager(
            repository=repository, embeddings=provider, clock=frozen_clock(NOON)
        )

        stored = manager.remember(
            type=MemoryType.EPISODIC,
            content="prefere python",
            provenance=Provenance(origin=MemoryOrigin.USER),
        )

        assert stored.memory.embedding is None

    def test_invalid_memory_never_touches_the_repository(self) -> None:
        class ExplodingRepository(FakeMemoryRepository):
            def add(self, memory: Memory, *, recorded_at: datetime) -> StoredMemory:
                raise AssertionError("não deveria ser chamado")

        manager = MemoryManager(repository=ExplodingRepository(), clock=frozen_clock(NOON))

        with pytest.raises(InvalidMemoryError):
            manager.remember(
                type=MemoryType.PREFERENCE,
                content="x",
                provenance=Provenance(origin=MemoryOrigin.USER),
                # PREFERENCE exige subject — dispara a invariante do domínio.
            )


class TestMemoryManagerConsolidate:
    def test_promotes_a_repeated_episodic_pattern(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        for reference in ("evt-1", "evt-2", "evt-3"):
            manager.remember(
                type=MemoryType.EPISODIC,
                content="chega sempre atrasado às segundas",
                provenance=Provenance(origin=MemoryOrigin.EVENT, reference=reference),
                subject="pattern.monday_lateness",
            )

        report = manager.consolidate()

        assert len(report.promoted) == 1
        promoted = report.promoted[0]
        assert promoted.memory.type is MemoryType.SEMANTIC
        assert promoted.memory.provenance.origin is MemoryOrigin.SYSTEM
        assert len(promoted.memory.derived_from) == 3

    def test_calling_consolidate_twice_does_not_duplicate(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))
        for reference in ("evt-1", "evt-2", "evt-3"):
            manager.remember(
                type=MemoryType.EPISODIC,
                content="chega sempre atrasado às segundas",
                provenance=Provenance(origin=MemoryOrigin.EVENT, reference=reference),
                subject="pattern.monday_lateness",
            )

        first = manager.consolidate()
        second = manager.consolidate()

        assert len(first.promoted) == 1
        assert len(second.promoted) == 0

    def test_nothing_to_promote_returns_an_empty_report(self) -> None:
        repository = FakeMemoryRepository()
        manager = MemoryManager(repository=repository, clock=frozen_clock(NOON))

        report = manager.consolidate()

        assert report.promoted == ()
