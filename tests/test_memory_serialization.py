from datetime import timedelta

import pytest

from jarvis.memory.adapters.serialization import (
    SCHEMA_VERSION,
    decode_tags,
    decode_vector,
    encode_tags,
    encode_vector,
    from_record,
    to_record,
)
from jarvis.memory.errors import MemoryReadError
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance, StoredMemory
from tests.memory_doubles import DEFAULT_CREATED_AT, make_embedding, make_memory

NOON = DEFAULT_CREATED_AT


def fully_populated_stored() -> StoredMemory:
    memory = make_memory(
        content="Prefere Python para scripts",
        provenance=Provenance(origin=MemoryOrigin.USER, reference="evt-1"),
        importance=0.7,
        confidence=0.9,
        subject="preference.language",
        scope="conv-1",
        entities=["python"],
        tags=["dev", "linguagem"],
        derived_from=["mem-a", "mem-b"],
        embedding=make_embedding((0.5, 0.5, 0.5, 0.5)),
        valid_from=NOON,
        valid_until=NOON + timedelta(days=30),
        type=MemoryType.SEMANTIC,
    )
    return StoredMemory(
        memory=memory,
        recorded_at=NOON,
        updated_at=NOON + timedelta(minutes=5),
        confidence=0.95,
        last_accessed_at=NOON + timedelta(minutes=10),
        access_count=3,
        reinforced_count=1,
    )


class TestRoundTrip:
    def test_fully_populated_record_survives_intact(self) -> None:
        stored = fully_populated_stored()

        assert from_record(dict(to_record(stored))) == stored

    def test_minimal_record_without_optionals_survives_intact(self) -> None:
        stored = StoredMemory(
            memory=make_memory(), recorded_at=NOON, updated_at=NOON, confidence=0.8
        )

        assert from_record(dict(to_record(stored))) == stored

    def test_lifecycle_fields_survive(self) -> None:
        stored = StoredMemory(
            memory=make_memory(),
            recorded_at=NOON,
            updated_at=NOON,
            confidence=0.5,
            superseded_by="mem-new",
            invalidated_at=NOON + timedelta(hours=1),
            invalidation_reason="usuário pediu",
        )

        recovered = from_record(dict(to_record(stored)))

        assert recovered.superseded_by == "mem-new"
        assert recovered.invalidated_at == NOON + timedelta(hours=1)
        assert recovered.invalidation_reason == "usuário pediu"

    def test_schema_version_constant_is_stable(self) -> None:
        assert SCHEMA_VERSION == 1


class TestTags:
    def test_encode_decode_round_trip(self) -> None:
        assert decode_tags(encode_tags(["a", "b"]), field_name="tags") == ("a", "b")

    def test_empty_sequence_round_trips(self) -> None:
        assert decode_tags(encode_tags([]), field_name="tags") == ()

    def test_invalid_json_is_reported(self) -> None:
        with pytest.raises(MemoryReadError, match="JSON"):
            decode_tags("{quebrado", field_name="tags")

    def test_non_array_json_is_reported(self) -> None:
        with pytest.raises(MemoryReadError, match="tags"):
            decode_tags('{"a": 1}', field_name="tags")

    def test_array_of_non_strings_is_reported(self) -> None:
        with pytest.raises(MemoryReadError, match="tags"):
            decode_tags("[1, 2]", field_name="tags")


class TestVectorCodec:
    def test_round_trips_float_values(self) -> None:
        vector = (0.1, -0.5, 1.0, 0.0)
        blob = encode_vector(vector)
        decoded = decode_vector(blob, dimensions=4, field_name="embedding")

        for original, recovered in zip(vector, decoded, strict=True):
            assert recovered == pytest.approx(original, abs=1e-6)

    def test_truncated_blob_is_reported(self) -> None:
        blob = encode_vector((1.0, 2.0, 3.0, 4.0))[:-1]
        with pytest.raises(MemoryReadError, match="embedding"):
            decode_vector(blob, dimensions=4, field_name="embedding")

    def test_blob_size_must_match_declared_dimensions(self) -> None:
        blob = encode_vector((1.0, 2.0))

        # O tamanho declarado bate com o blob: decodifica sem erro.
        assert decode_vector(blob, dimensions=2, field_name="embedding") == (1.0, 2.0)

        # Um `dimensions` diferente do que o blob realmente contém é corrupção.
        with pytest.raises(MemoryReadError, match="3 dimensões"):
            decode_vector(blob, dimensions=3, field_name="embedding")


class TestCorruption:
    def test_unknown_memory_type_is_reported(self) -> None:
        record = dict(to_record(fully_populated_stored()))
        record["type"] = "not-a-real-type"

        with pytest.raises(MemoryReadError, match="type"):
            from_record(record)

    def test_unknown_origin_is_reported(self) -> None:
        record = dict(to_record(fully_populated_stored()))
        record["origin"] = "not-a-real-origin"

        with pytest.raises(MemoryReadError, match="origin"):
            from_record(record)

    def test_missing_created_at_is_reported(self) -> None:
        record = dict(to_record(fully_populated_stored()))
        record["created_at"] = None

        with pytest.raises(MemoryReadError, match="created_at"):
            from_record(record)

    def test_wrong_typed_importance_is_reported(self) -> None:
        record = dict(to_record(fully_populated_stored()))
        record["importance"] = "alta"

        with pytest.raises(MemoryReadError, match="importance"):
            from_record(record)
