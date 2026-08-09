from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.events.errors import InvalidEventError
from jarvis.events.event import (
    Event,
    RecordedEvent,
    deterministic_event_id,
    new_event_id,
)
from tests.factories import make_event


class TestIdentity:
    def test_root_event_uses_its_own_id_as_correlation_id(self) -> None:
        event = make_event(event_id="abc")

        assert event.correlation_id == "abc"
        assert event.causation_id is None

    def test_explicit_correlation_id_is_preserved(self) -> None:
        event = make_event(event_id="child", correlation_id="root", causation_id="parent")

        assert event.correlation_id == "root"
        assert event.causation_id == "parent"

    def test_correlation_and_causation_are_not_synonyms(self) -> None:
        parent = make_event(event_id="parent")
        child = make_event(
            event_id="child", correlation_id=parent.correlation_id, causation_id=parent.event_id
        )

        assert child.correlation_id == parent.event_id
        assert child.causation_id == parent.event_id
        # Um neto compartilha a correlação da raiz, mas aponta para o pai direto.
        grandchild = make_event(
            event_id="grandchild", correlation_id=parent.correlation_id, causation_id=child.event_id
        )
        assert grandchild.correlation_id == parent.event_id
        assert grandchild.causation_id != grandchild.correlation_id

    def test_empty_identifiers_are_rejected(self) -> None:
        with pytest.raises(InvalidEventError, match="event_id"):
            make_event(event_id="  ")
        with pytest.raises(InvalidEventError, match="correlation_id"):
            make_event(correlation_id="")
        with pytest.raises(InvalidEventError, match="causation_id"):
            make_event(causation_id="")


class TestIdHelpers:
    def test_deterministic_id_is_stable(self) -> None:
        first = deterministic_event_id(source="gmail-watcher", natural_key="msg-1")
        second = deterministic_event_id(source="gmail-watcher", natural_key="msg-1")

        assert first == second

    def test_deterministic_id_separates_source_from_key(self) -> None:
        assert deterministic_event_id(source="a", natural_key="b:c") != deterministic_event_id(
            source="a:b", natural_key="c"
        )

    def test_random_ids_are_unique(self) -> None:
        assert new_event_id() != new_event_id()


class TestValidation:
    @pytest.mark.parametrize("event_type", ["received", "Email.Received", "", "email..received"])
    def test_event_type_must_be_namespaced_and_lowercase(self, event_type: str) -> None:
        with pytest.raises(InvalidEventError, match="event_type"):
            make_event(event_type=event_type)

    def test_valid_event_types_are_accepted(self) -> None:
        assert make_event(event_type="email.received").event_type == "email.received"
        assert make_event(event_type="email.received.retracted").event_type
        assert make_event(event_type="calendar.meeting_starting").event_type

    @pytest.mark.parametrize("source", ["", "Gmail", "-watcher", "gmail watcher"])
    def test_source_is_validated(self, source: str) -> None:
        with pytest.raises(InvalidEventError, match="source"):
            make_event(source=source)

    @pytest.mark.parametrize("version", [0, -1])
    def test_schema_version_must_be_positive(self, version: int) -> None:
        with pytest.raises(InvalidEventError, match="schema_version"):
            make_event(schema_version=version)

    def test_schema_version_defaults_to_one(self) -> None:
        assert make_event().schema_version == 1


class TestTimestamps:
    def test_naive_occurred_at_is_rejected(self) -> None:
        with pytest.raises(InvalidEventError, match="occurred_at"):
            make_event(occurred_at=datetime(2026, 8, 9, 12, 0))

    def test_aware_occurred_at_is_normalised_to_utc(self) -> None:
        in_sao_paulo = datetime(2026, 8, 9, 9, 0, tzinfo=timezone(timedelta(hours=-3)))

        event = make_event(occurred_at=in_sao_paulo)

        assert event.occurred_at == datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
        assert event.occurred_at.tzinfo is UTC

    def test_recorded_event_requires_aware_timestamp(self) -> None:
        with pytest.raises(InvalidEventError, match="recorded_at"):
            RecordedEvent(event=make_event(), recorded_at=datetime(2026, 8, 9, 12, 0))

    def test_event_has_no_recorded_at(self) -> None:
        # `recorded_at` pertence ao Event Store (ADR-0004): o producer não tem como
        # informá-lo nem por engano.
        assert not hasattr(make_event(), "recorded_at")
        with pytest.raises(TypeError):
            Event(  # type: ignore[call-arg]
                event_id="x",
                event_type="demo.happened",
                source="test-suite",
                occurred_at=datetime(2026, 8, 9, tzinfo=UTC),
                payload={},
                recorded_at=datetime(2026, 8, 9, tzinfo=UTC),
            )


class TestImmutability:
    def test_fields_cannot_be_reassigned(self) -> None:
        event = make_event()

        with pytest.raises(FrozenInstanceError):
            event.event_id = "other"  # type: ignore[misc]

    def test_payload_cannot_be_mutated(self) -> None:
        event = make_event(payload={"subject": "oi"})

        with pytest.raises(TypeError):
            event.payload["subject"] = "tchau"  # type: ignore[index]

    def test_nested_structures_are_frozen(self) -> None:
        event = make_event(payload={"headers": {"to": ["a@b.c"]}})

        headers = event.payload["headers"]
        with pytest.raises(TypeError):
            headers["to"] = []  # type: ignore[index]
        assert event.payload == {"headers": {"to": ("a@b.c",)}}

    def test_mutating_the_original_mapping_does_not_affect_the_event(self) -> None:
        source_payload: dict[str, object] = {"items": [1, 2]}

        event = make_event(payload=source_payload)  # type: ignore[arg-type]
        source_payload["items"] = [9]
        source_payload["new"] = True

        assert event.payload == {"items": (1, 2)}

    def test_metadata_defaults_to_an_empty_frozen_mapping(self) -> None:
        event = make_event()

        assert event.metadata == {}
        with pytest.raises(TypeError):
            event.metadata["x"] = 1  # type: ignore[index]


class TestPayloadTypes:
    def test_all_json_types_are_accepted(self) -> None:
        event = make_event(
            payload={
                "text": "a",
                "number": 1,
                "decimal": 1.5,
                "flag": True,
                "nothing": None,
                "list": [1, "b", None],
                "nested": {"deep": {"deeper": []}},
            }
        )

        assert event.payload["list"] == (1, "b", None)

    @pytest.mark.parametrize(
        "value",
        [datetime(2026, 8, 9, tzinfo=UTC), {1, 2}, b"bytes", object()],
    )
    def test_non_json_values_are_rejected(self, value: object) -> None:
        with pytest.raises(InvalidEventError, match="payload"):
            make_event(payload={"bad": value})  # type: ignore[dict-item]

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_non_finite_floats_are_rejected(self, value: float) -> None:
        with pytest.raises(InvalidEventError, match="JSON"):
            make_event(payload={"bad": value})

    def test_non_string_keys_are_rejected(self) -> None:
        with pytest.raises(InvalidEventError, match="chave"):
            make_event(payload={1: "a"})  # type: ignore[dict-item]

    def test_payload_must_be_a_mapping(self) -> None:
        with pytest.raises(InvalidEventError, match="payload"):
            make_event(payload=[1, 2])  # type: ignore[arg-type]


def test_events_compare_by_value() -> None:
    first = make_event(event_id="same", payload={"a": [1]})
    second = make_event(event_id="same", payload={"a": [1]})

    assert first == second
