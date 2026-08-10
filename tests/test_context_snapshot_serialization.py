import json
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.context.adapters.snapshot_serialization import (
    SNAPSHOT_SCHEMA_VERSION,
    decode_context,
    encode_context,
    from_record,
    to_record,
)
from jarvis.context.errors import ContextSnapshotReadError
from jarvis.context.model import (
    ActivityContext,
    ContextField,
    ConversationContext,
    CurrentContext,
    DeviceContext,
    EnvironmentContext,
    ScheduleContext,
    TaskContext,
    UserContext,
    iter_fields,
)
from jarvis.context.snapshot import ContextSnapshot
from tests.context_doubles import make_observation

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def fully_populated() -> CurrentContext:
    """Todos os campos preenchidos, incluindo a ausência observada de atividade."""
    return CurrentContext(
        as_of=NOON,
        user=UserContext(
            availability=make_observation(
                "busy",
                observed_at=NOON - timedelta(minutes=5),
                source="event:user.availability_changed",
                confidence=0.75,
                ttl=timedelta(hours=4),
            )
        ),
        environment=EnvironmentContext(
            utc_offset=make_observation("-03:00", ttl=timedelta(hours=12)),
            place=make_observation("home", ttl=timedelta(minutes=15)),
        ),
        device=DeviceContext(device_id=make_observation("notebook")),
        activity=ActivityContext(
            current=make_observation(None, source="event:user.activity_ended")
        ),
        schedule=ScheduleContext(next_entry_at=make_observation(NOON + timedelta(hours=2))),
        conversation=ConversationContext(active_id=make_observation("conv-1")),
        task=TaskContext(active_id=make_observation("task-1")),
    )


class TestRoundTrip:
    def test_every_field_survives_intact(self) -> None:
        context = fully_populated()

        assert decode_context(encode_context(context)) == context

    def test_covers_every_context_field(self) -> None:
        populated = {
            field
            for field, observation in iter_fields(fully_populated())
            if observation is not None
        }

        assert populated == set(ContextField)

    def test_absent_fields_stay_absent(self) -> None:
        context = CurrentContext(as_of=NOON)

        decoded = decode_context(encode_context(context))

        assert all(observation is None for _, observation in iter_fields(decoded))

    def test_observed_absence_is_not_confused_with_absence(self) -> None:
        context = CurrentContext(
            as_of=NOON,
            activity=ActivityContext(
                current=make_observation(None, source="event:user.activity_ended")
            ),
        )

        decoded = decode_context(encode_context(context))

        assert decoded.activity.current is not None
        assert decoded.activity.current.value is None
        assert decoded.activity.current.source == "event:user.activity_ended"

    def test_snapshot_record_round_trip(self) -> None:
        snapshot = ContextSnapshot(snapshot_id="s-1", captured_at=NOON, context=fully_populated())

        record = to_record(snapshot)

        assert record["schema_version"] == SNAPSHOT_SCHEMA_VERSION
        assert record["fingerprint"] == snapshot.fingerprint()
        assert from_record(dict(record)) == snapshot


class TestCanonicalDocument:
    def test_keys_are_sorted_and_compact(self) -> None:
        document = encode_context(fully_populated())

        assert '{"as_of"' in document
        assert ", " not in document
        assert json.loads(document)["fields"]["availability"]["confidence"] == 0.75

    def test_absent_fields_are_omitted_from_the_document(self) -> None:
        document = json.loads(encode_context(CurrentContext(as_of=NOON)))

        assert document["fields"] == {}


class TestCorruption:
    def test_invalid_json_is_reported(self) -> None:
        with pytest.raises(ContextSnapshotReadError, match="JSON"):
            decode_context("{quebrado")

    def test_missing_fields_object_is_reported(self) -> None:
        with pytest.raises(ContextSnapshotReadError, match="fields"):
            decode_context(json.dumps({"as_of": NOON.isoformat()}))

    def test_wrong_value_type_is_reported(self) -> None:
        document = json.dumps(
            {
                "as_of": NOON.isoformat(),
                "fields": {
                    "next_entry_at": {
                        "value": "ontem",
                        "observed_at": NOON.isoformat(),
                        "source": "s",
                        "confidence": 1.0,
                        "ttl_seconds": None,
                    }
                },
            }
        )

        with pytest.raises(ContextSnapshotReadError, match=r"next_entry_at\.value"):
            decode_context(document)

    def test_non_numeric_confidence_is_reported(self) -> None:
        document = json.dumps(
            {
                "as_of": NOON.isoformat(),
                "fields": {
                    "place": {
                        "value": "home",
                        "observed_at": NOON.isoformat(),
                        "source": "s",
                        "confidence": "alta",
                        "ttl_seconds": None,
                    }
                },
            }
        )

        with pytest.raises(ContextSnapshotReadError, match="confidence"):
            decode_context(document)

    def test_unknown_schema_version_is_refused(self) -> None:
        record = dict(
            to_record(
                ContextSnapshot(snapshot_id="s-1", captured_at=NOON, context=fully_populated())
            )
        )
        record["schema_version"] = 99

        with pytest.raises(ContextSnapshotReadError, match="schema_version"):
            from_record(record)
