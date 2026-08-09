import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from jarvis.events.adapters.serialization import (
    decode_json_object,
    encode_json_object,
    event_fingerprint,
    format_timestamp,
    from_record,
    parse_timestamp,
    to_record,
)
from jarvis.events.errors import EventReadError
from jarvis.events.event import RecordedEvent
from tests.factories import make_event

RECORDED_AT = datetime(2026, 8, 9, 12, 5, tzinfo=UTC)


class TestRoundTrip:
    def test_preserves_every_field(self) -> None:
        event = make_event(
            event_id="e-1",
            event_type="email.received",
            source="gmail-watcher",
            payload={"subject": "olá", "to": ["a@b.c"], "read": False, "score": 1.5},
            schema_version=3,
            correlation_id="root",
            causation_id="parent",
            metadata={"trace": "x"},
        )

        restored = from_record(dict(to_record(event, RECORDED_AT)))

        assert restored == RecordedEvent(event=event, recorded_at=RECORDED_AT)

    def test_preserves_nested_and_unicode_content(self) -> None:
        event = make_event(payload={"nested": {"list": [1, {"deep": "ação"}], "null": None}})

        restored = from_record(dict(to_record(event, RECORDED_AT)))

        assert restored.event.payload == event.payload

    def test_absent_causation_id_survives(self) -> None:
        event = make_event(causation_id=None)

        restored = from_record(dict(to_record(event, RECORDED_AT)))

        assert restored.event.causation_id is None
        assert restored.event.correlation_id == event.event_id


class TestCanonicalJson:
    def test_keys_are_sorted_and_compact(self) -> None:
        encoded = encode_json_object({"b": 1, "a": 2})

        assert encoded == '{"a":2,"b":1}'

    def test_unicode_is_not_escaped(self) -> None:
        assert encode_json_object({"k": "ação"}) == '{"k":"ação"}'

    def test_frozen_payload_is_serialisable(self) -> None:
        event = make_event(payload={"items": [1, 2], "nested": {"a": 1}})

        assert json.loads(encode_json_object(event.payload)) == {
            "items": [1, 2],
            "nested": {"a": 1},
        }

    def test_invalid_json_is_reported_as_read_error(self) -> None:
        with pytest.raises(EventReadError, match="payload"):
            decode_json_object("{not json", field_name="payload")

    def test_non_object_json_is_rejected(self) -> None:
        with pytest.raises(EventReadError, match="objeto JSON"):
            decode_json_object("[1, 2]", field_name="payload")


class TestTimestamps:
    def test_formats_in_utc(self) -> None:
        in_sao_paulo = datetime(2026, 8, 9, 9, 0, tzinfo=timezone(timedelta(hours=-3)))

        assert format_timestamp(in_sao_paulo) == "2026-08-09T12:00:00+00:00"

    def test_formatted_order_matches_temporal_order(self) -> None:
        earlier = format_timestamp(datetime(2026, 8, 9, 9, 59, tzinfo=UTC))
        later = format_timestamp(datetime(2026, 8, 9, 10, 0, tzinfo=UTC))

        assert earlier < later

    def test_malformed_timestamp_is_reported(self) -> None:
        with pytest.raises(EventReadError, match="occurred_at"):
            parse_timestamp("ontem", field_name="occurred_at")


class TestFingerprint:
    def test_is_stable_regardless_of_key_order(self) -> None:
        first = make_event(event_id="same", payload={"a": 1, "b": 2})
        second = make_event(event_id="same", payload={"b": 2, "a": 1})

        assert event_fingerprint(first) == event_fingerprint(second)

    def test_changes_with_content(self) -> None:
        original = make_event(event_id="same", payload={"a": 1})
        divergent = make_event(event_id="same", payload={"a": 2})

        assert event_fingerprint(original) != event_fingerprint(divergent)

    def test_ignores_the_event_id(self) -> None:
        assert event_fingerprint(make_event(event_id="one")) != event_fingerprint(
            make_event(event_id="two")
        )
        # `correlation_id` deriva do `event_id`, então ids diferentes divergem; com a
        # correlação fixada, o resumo depende só do conteúdo.
        assert event_fingerprint(
            make_event(event_id="one", correlation_id="c")
        ) == event_fingerprint(make_event(event_id="two", correlation_id="c"))


class TestCorruptRecords:
    @pytest.mark.parametrize(
        ("column", "value"),
        [("event_id", None), ("event_type", 1), ("schema_version", "um"), ("source", None)],
    )
    def test_wrong_column_types_are_read_errors(self, column: str, value: object) -> None:
        record: dict[str, object] = dict(to_record(make_event(), RECORDED_AT))
        record[column] = value

        with pytest.raises(EventReadError, match=column):
            from_record(record)

    def test_missing_column_is_a_read_error(self) -> None:
        record: dict[str, object] = dict(to_record(make_event(), RECORDED_AT))
        del record["payload"]

        with pytest.raises(EventReadError, match="payload"):
            from_record(record)
