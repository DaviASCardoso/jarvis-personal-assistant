from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.memory import (
    MAX_SUBJECT_LENGTH,
    Memory,
    MemoryOrigin,
    MemoryType,
    Provenance,
    StoredMemory,
    content_fingerprint,
    deterministic_memory_id,
    new_memory_id,
    normalize_content,
    require_slug,
)
from tests.memory_doubles import DEFAULT_CREATED_AT, make_embedding, make_memory

NOON = DEFAULT_CREATED_AT
LATER = NOON + timedelta(hours=1)


class TestIdentifiers:
    def test_new_memory_id_is_unique(self) -> None:
        assert new_memory_id() != new_memory_id()

    def test_deterministic_memory_id_is_stable(self) -> None:
        first = deterministic_memory_id(source="event", natural_key="evt-1")
        second = deterministic_memory_id(source="event", natural_key="evt-1")
        assert first == second

    def test_deterministic_memory_id_distinguishes_source_and_key(self) -> None:
        a = deterministic_memory_id(source="event", natural_key="evt-1")
        b = deterministic_memory_id(source="event", natural_key="evt-2")
        c = deterministic_memory_id(source="other", natural_key="evt-1")
        assert len({a, b, c}) == 3


class TestProvenance:
    def test_reference_must_be_non_blank_when_present(self) -> None:
        with pytest.raises(InvalidMemoryError, match="reference"):
            Provenance(origin=MemoryOrigin.EVENT, reference="  ")

    def test_reference_is_optional(self) -> None:
        provenance = Provenance(origin=MemoryOrigin.USER)
        assert provenance.reference is None


class TestConstruction:
    def test_valid_memory_is_constructed(self) -> None:
        memory = make_memory()
        assert memory.type is MemoryType.EPISODIC
        assert memory.importance == 0.5
        assert memory.confidence == 0.8

    def test_rejects_blank_memory_id(self) -> None:
        with pytest.raises(InvalidMemoryError, match="memory_id"):
            make_memory(memory_id="  ")

    def test_rejects_blank_content(self) -> None:
        with pytest.raises(InvalidMemoryError, match="content"):
            make_memory(content="   ")

    @pytest.mark.parametrize("importance", [-0.01, 1.01, float("nan")])
    def test_rejects_importance_outside_unit_interval(self, importance: float) -> None:
        with pytest.raises(InvalidMemoryError, match="importance"):
            make_memory(importance=importance)

    @pytest.mark.parametrize("confidence", [-0.01, 1.01, float("nan")])
    def test_rejects_confidence_outside_unit_interval(self, confidence: float) -> None:
        with pytest.raises(InvalidMemoryError, match="confidence"):
            make_memory(confidence=confidence)

    def test_rejects_naive_created_at(self) -> None:
        with pytest.raises(InvalidMemoryError, match="created_at"):
            make_memory(created_at=datetime(2026, 8, 10, 12, 0))

    def test_normalises_created_at_to_utc(self) -> None:
        sao_paulo = timezone(timedelta(hours=-3))
        memory = make_memory(created_at=datetime(2026, 8, 10, 9, 0, tzinfo=sao_paulo))
        assert memory.created_at == NOON
        assert memory.created_at.tzinfo is UTC

    def test_valid_from_defaults_to_created_at(self) -> None:
        memory = make_memory(created_at=NOON)
        assert memory.valid_from == NOON

    def test_valid_from_can_be_overridden(self) -> None:
        earlier = NOON - timedelta(days=1)
        memory = make_memory(created_at=NOON, valid_from=earlier)
        assert memory.valid_from == earlier

    def test_rejects_naive_valid_from(self) -> None:
        with pytest.raises(InvalidMemoryError, match="valid_from"):
            make_memory(valid_from=datetime(2026, 8, 10, 12, 0))

    def test_valid_until_must_be_after_valid_from(self) -> None:
        with pytest.raises(InvalidMemoryError, match="valid_until"):
            make_memory(
                type=MemoryType.WORKING,
                scope=None,
                valid_from=NOON,
                valid_until=NOON,
            )

    def test_valid_until_strictly_after_valid_from_is_accepted(self) -> None:
        memory = make_memory(
            type=MemoryType.WORKING, valid_from=NOON, valid_until=NOON + timedelta(hours=1)
        )
        assert memory.valid_until == NOON + timedelta(hours=1)


class TestSubject:
    @pytest.mark.parametrize(
        "subject", ["Preference", "with space", "trailing_", "_leading", "a__b", ""]
    )
    def test_rejects_non_slug_subjects(self, subject: str) -> None:
        with pytest.raises(InvalidMemoryError):
            make_memory(subject=subject)

    def test_accepts_a_dotted_slug(self) -> None:
        memory = make_memory(subject="preference.programming_language")
        assert memory.subject == "preference.programming_language"

    def test_rejects_subjects_over_the_length_limit(self) -> None:
        with pytest.raises(InvalidMemoryError, match="excede"):
            make_memory(subject="a" * (MAX_SUBJECT_LENGTH + 1))

    def test_require_slug_helper_matches_the_domain_rule(self) -> None:
        assert require_slug("a.b-c_d", field_name="x") == "a.b-c_d"


class TestConditionalInvariants:
    def test_agent_origin_cannot_claim_full_certainty(self) -> None:
        with pytest.raises(InvalidMemoryError, match="confidence"):
            make_memory(provenance=Provenance(origin=MemoryOrigin.AGENT), confidence=1.0)

    def test_agent_origin_below_full_certainty_is_fine(self) -> None:
        memory = make_memory(provenance=Provenance(origin=MemoryOrigin.AGENT), confidence=0.99)
        assert memory.confidence == 0.99

    def test_working_memory_requires_valid_until(self) -> None:
        with pytest.raises(InvalidMemoryError, match="working"):
            make_memory(type=MemoryType.WORKING)

    def test_working_memory_with_valid_until_is_accepted(self) -> None:
        memory = make_memory(type=MemoryType.WORKING, valid_until=NOON + timedelta(hours=2))
        assert memory.type is MemoryType.WORKING

    def test_task_memory_requires_scope(self) -> None:
        with pytest.raises(InvalidMemoryError, match="task"):
            make_memory(type=MemoryType.TASK)

    def test_task_memory_with_scope_is_accepted(self) -> None:
        memory = make_memory(type=MemoryType.TASK, scope="task-42")
        assert memory.scope == "task-42"

    def test_preference_memory_requires_subject(self) -> None:
        with pytest.raises(InvalidMemoryError, match="preference"):
            make_memory(type=MemoryType.PREFERENCE)

    def test_preference_memory_with_subject_is_accepted(self) -> None:
        memory = make_memory(type=MemoryType.PREFERENCE, subject="preference.coffee")
        assert memory.subject == "preference.coffee"


class TestCollections:
    def test_entities_are_deduplicated_and_sorted(self) -> None:
        memory = make_memory(entities=["b", "a", "b"])
        assert memory.entities == ("a", "b")

    def test_tags_are_deduplicated_and_sorted(self) -> None:
        memory = make_memory(tags=["z", "a"])
        assert memory.tags == ("a", "z")

    def test_derived_from_is_deduplicated_and_sorted(self) -> None:
        memory = make_memory(derived_from=["id-2", "id-1", "id-2"])
        assert memory.derived_from == ("id-1", "id-2")

    def test_blank_tag_is_rejected(self) -> None:
        with pytest.raises(InvalidMemoryError, match="tags"):
            make_memory(tags=["ok", ""])

    def test_a_bare_string_is_not_accepted_as_a_sequence_of_tags(self) -> None:
        with pytest.raises(InvalidMemoryError, match="tags"):
            Memory(
                memory_id=new_memory_id(),
                type=MemoryType.EPISODIC,
                content="x",
                provenance=Provenance(origin=MemoryOrigin.USER),
                created_at=NOON,
                tags="abc",  # type: ignore[arg-type]
            )


class TestEmbeddingField:
    def test_accepts_a_compatible_embedding(self) -> None:
        embedding = make_embedding()
        memory = make_memory(embedding=embedding)
        assert memory.embedding is embedding

    def test_embedding_is_optional(self) -> None:
        assert make_memory().embedding is None


class TestFingerprint:
    def test_is_stable_under_case_and_whitespace_variation(self) -> None:
        a = content_fingerprint("Prefere  Python")
        b = content_fingerprint("prefere python")
        assert a == b

    def test_is_stable_under_accent_variation(self) -> None:
        assert content_fingerprint("café") == content_fingerprint("cafe")

    def test_differs_for_different_content(self) -> None:
        assert content_fingerprint("prefere python") != content_fingerprint("prefere rust")

    def test_memory_fingerprint_matches_the_helper(self) -> None:
        memory = make_memory(content="Prefere Python")
        assert memory.fingerprint() == content_fingerprint("Prefere Python")

    def test_normalize_content_collapses_internal_whitespace(self) -> None:
        assert normalize_content("a   b\tc") == "a b c"


class TestValidity:
    def test_is_valid_before_valid_from_is_false(self) -> None:
        memory = make_memory(valid_from=NOON)
        assert not memory.is_valid_at(NOON - timedelta(seconds=1))

    def test_is_valid_at_valid_from_is_true(self) -> None:
        memory = make_memory(valid_from=NOON)
        assert memory.is_valid_at(NOON)

    def test_without_valid_until_never_expires(self) -> None:
        memory = make_memory(valid_from=NOON)
        assert memory.is_valid_at(NOON + timedelta(days=3650))

    def test_is_valid_strictly_before_valid_until(self) -> None:
        memory = make_memory(
            type=MemoryType.WORKING, valid_from=NOON, valid_until=NOON + timedelta(hours=1)
        )
        assert memory.is_valid_at(NOON + timedelta(minutes=59, seconds=59))
        # O intervalo é semiaberto: o instante do vencimento já não é válido.
        assert not memory.is_valid_at(NOON + timedelta(hours=1))


class TestImmutability:
    def test_memory_is_frozen(self) -> None:
        memory = make_memory()
        with pytest.raises(FrozenInstanceError):
            memory.content = "outro"  # type: ignore[misc]

    def test_provenance_is_frozen(self) -> None:
        provenance = Provenance(origin=MemoryOrigin.USER)
        with pytest.raises(FrozenInstanceError):
            provenance.origin = MemoryOrigin.AGENT  # type: ignore[misc]


def _stored(**overrides: object) -> StoredMemory:
    defaults: dict[str, object] = {
        "memory": make_memory(),
        "recorded_at": NOON,
        "updated_at": NOON,
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return StoredMemory(**defaults)  # type: ignore[arg-type]


class TestStoredMemory:
    def _base(self, **overrides: object) -> StoredMemory:
        return _stored(**overrides)

    def test_normalises_recorded_at_and_updated_at(self) -> None:
        sao_paulo = timezone(timedelta(hours=-3))
        stored = self._base(
            recorded_at=datetime(2026, 8, 10, 9, 0, tzinfo=sao_paulo),
            updated_at=datetime(2026, 8, 10, 9, 0, tzinfo=sao_paulo),
        )
        assert stored.recorded_at == NOON
        assert stored.updated_at == NOON

    def test_rejects_naive_recorded_at(self) -> None:
        with pytest.raises(InvalidMemoryError, match="recorded_at"):
            self._base(recorded_at=datetime(2026, 8, 10, 12, 0))

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_rejects_confidence_outside_unit_interval(self, confidence: float) -> None:
        with pytest.raises(InvalidMemoryError, match="confidence"):
            self._base(confidence=confidence)

    def test_last_accessed_at_is_optional_but_validated_when_present(self) -> None:
        assert self._base().last_accessed_at is None
        with pytest.raises(InvalidMemoryError, match="last_accessed_at"):
            self._base(last_accessed_at=datetime(2026, 8, 10, 12, 0))

    @pytest.mark.parametrize("field", ["access_count", "reinforced_count"])
    def test_counters_cannot_be_negative(self, field: str) -> None:
        with pytest.raises(InvalidMemoryError, match=field):
            self._base(**{field: -1})

    def test_superseded_by_must_be_non_blank_when_present(self) -> None:
        with pytest.raises(InvalidMemoryError, match="superseded_by"):
            self._base(superseded_by="  ")

    def test_invalidation_reason_must_be_non_blank_when_present(self) -> None:
        with pytest.raises(InvalidMemoryError, match="invalidation_reason"):
            self._base(invalidated_at=NOON, invalidation_reason="  ")

    def test_is_frozen(self) -> None:
        stored = self._base()
        with pytest.raises(FrozenInstanceError):
            stored.confidence = 0.9  # type: ignore[misc]


class TestIsActiveAt:
    def test_active_when_valid_and_untouched(self) -> None:
        stored = _stored(memory=make_memory(valid_from=NOON))
        assert stored.is_active_at(NOON)

    def test_inactive_when_invalidated(self) -> None:
        stored = _stored(
            memory=make_memory(valid_from=NOON),
            invalidated_at=LATER,
            invalidation_reason="usuário pediu",
        )
        assert not stored.is_active_at(LATER)

    def test_inactive_when_superseded(self) -> None:
        stored = _stored(memory=make_memory(valid_from=NOON), superseded_by=new_memory_id())
        assert not stored.is_active_at(NOON)

    def test_inactive_when_expired_by_time(self) -> None:
        memory = make_memory(
            type=MemoryType.WORKING, valid_from=NOON, valid_until=NOON + timedelta(hours=1)
        )
        stored = _stored(memory=memory)
        assert not stored.is_active_at(NOON + timedelta(hours=2))
