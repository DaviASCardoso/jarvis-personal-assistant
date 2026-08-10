import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest

from jarvis.events.event import JsonValue
from jarvis.events.ports import EventConsumer
from jarvis.memory.adapters.event_consumer import MEMORY_EVENT_TYPES, MemoryEventConsumer
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, deterministic_memory_id
from jarvis.memory.ports import MemoryCriteria
from tests.factories import make_event, make_recorded_event
from tests.memory_doubles import FakeMemoryRepository, frozen_clock

NOON = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
LATER = NOON + timedelta(hours=1)


def build() -> tuple[MemoryEventConsumer, MemoryManager, FakeMemoryRepository]:
    repository = FakeMemoryRepository()
    manager = MemoryManager(repository=repository, clock=frozen_clock(NOON, LATER, NOON, LATER))
    return MemoryEventConsumer(manager), manager, repository


def deliver(
    consumer: MemoryEventConsumer,
    event_type: str,
    payload: Mapping[str, JsonValue] | None = None,
    *,
    occurred_at: datetime = NOON,
    schema_version: int = 1,
    event_id: str = "e-1",
) -> None:
    consumer.handle(
        make_recorded_event(
            make_event(
                event_id=event_id,
                event_type=event_type,
                occurred_at=occurred_at,
                payload={} if payload is None else payload,
                schema_version=schema_version,
            ),
            recorded_at=NOON,
        )
    )


def test_the_subscribed_types_are_exactly_what_can_be_translated() -> None:
    assert set(MEMORY_EVENT_TYPES) == {"user.stated_preference", "user.noted_fact"}


def test_it_satisfies_the_event_consumer_port_structurally() -> None:
    consumer, _, _ = build()
    accepted: EventConsumer = consumer
    assert accepted.name == "memory"


class TestStatedPreference:
    def test_creates_a_preference_memory(self) -> None:
        consumer, _, repository = build()

        deliver(
            consumer,
            "user.stated_preference",
            {"subject": "preference.language", "content": "prefere python"},
        )

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.PREFERENCE})))
        assert len(found) == 1
        memory = found[0].memory
        assert memory.content == "prefere python"
        assert memory.subject == "preference.language"
        assert memory.provenance.origin is MemoryOrigin.USER
        assert memory.provenance.reference == "e-1"

    def test_observed_at_comes_from_occurred_at(self) -> None:
        consumer, _, repository = build()

        deliver(
            consumer,
            "user.stated_preference",
            {"subject": "preference.language", "content": "prefere python"},
            occurred_at=NOON,
        )

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.PREFERENCE})))
        assert found[0].memory.created_at == NOON

    def test_optional_confidence_is_honoured(self) -> None:
        consumer, _, repository = build()

        deliver(
            consumer,
            "user.stated_preference",
            {"subject": "preference.language", "content": "prefere python", "confidence": 0.95},
        )

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.PREFERENCE})))
        assert found[0].memory.confidence == 0.95

    def test_a_contradicting_preference_supersedes_the_previous_one(self) -> None:
        consumer, _, repository = build()
        deliver(
            consumer,
            "user.stated_preference",
            {"subject": "preference.language", "content": "prefere python"},
            occurred_at=NOON,
            event_id="e-1",
        )

        deliver(
            consumer,
            "user.stated_preference",
            {"subject": "preference.language", "content": "prefere rust"},
            occurred_at=LATER,
            event_id="e-2",
        )

        active = repository.search(MemoryCriteria(types=frozenset({MemoryType.PREFERENCE})))
        assert [item.memory.content for item in active] == ["prefere rust"]


class TestNotedFact:
    def test_creates_an_episodic_memory(self) -> None:
        consumer, _, repository = build()

        deliver(consumer, "user.noted_fact", {"content": "chegou atrasado hoje"})

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.EPISODIC})))
        assert len(found) == 1
        assert found[0].memory.content == "chegou atrasado hoje"
        assert found[0].memory.provenance.origin is MemoryOrigin.EVENT

    def test_optional_fields_are_applied(self) -> None:
        consumer, _, repository = build()

        deliver(
            consumer,
            "user.noted_fact",
            {
                "content": "chegou atrasado",
                "subject": "pattern.lateness",
                "entities": ["joão"],
                "tags": ["trabalho"],
            },
        )

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.EPISODIC})))
        memory = found[0].memory
        assert memory.subject == "pattern.lateness"
        assert memory.entities == ("joão",)
        assert memory.tags == ("trabalho",)

    def test_subject_is_optional(self) -> None:
        consumer, _, repository = build()

        deliver(consumer, "user.noted_fact", {"content": "algo aconteceu"})

        found = repository.search(MemoryCriteria(types=frozenset({MemoryType.EPISODIC})))
        assert found[0].memory.subject is None


class TestFiltering:
    def test_an_unsubscribed_type_is_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        consumer, _, repository = build()

        with caplog.at_level(logging.DEBUG, logger="jarvis.memory.adapters.event_consumer"):
            deliver(consumer, "email.received", {"subject": "reunião"})

        assert repository.search(MemoryCriteria()) == []
        record = next(item for item in caplog.records if item.message == "memory.event_ignored")
        assert record.reason == "unsubscribed_type"  # type: ignore[attr-defined]

    def test_an_unknown_schema_version_is_ignored_explicitly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        consumer, _, repository = build()

        with caplog.at_level(logging.INFO, logger="jarvis.memory.adapters.event_consumer"):
            deliver(
                consumer,
                "user.noted_fact",
                {"content": "algo"},
                schema_version=2,
            )

        assert repository.search(MemoryCriteria()) == []
        record = next(item for item in caplog.records if item.message == "memory.event_ignored")
        assert record.reason == "unsupported_schema_version"  # type: ignore[attr-defined]


class TestInvalidPayload:
    @pytest.mark.parametrize(
        ("event_type", "payload"),
        [
            ("user.stated_preference", {}),
            ("user.stated_preference", {"content": "x"}),
            ("user.stated_preference", {"subject": "Not A Slug", "content": "x"}),
            ("user.noted_fact", {}),
            ("user.noted_fact", {"content": "x", "entities": "not-a-list"}),
        ],
    )
    def test_a_malformed_payload_is_a_permanent_domain_error(
        self, event_type: str, payload: Mapping[str, JsonValue]
    ) -> None:
        from jarvis.errors import DomainError

        consumer, _, _ = build()

        with pytest.raises(InvalidMemoryError) as exc_info:
            deliver(consumer, event_type, payload)

        assert isinstance(exc_info.value, DomainError)
        assert exc_info.value.retryable is False

    def test_a_refused_payload_never_creates_a_memory(self) -> None:
        consumer, _, repository = build()

        with pytest.raises(InvalidMemoryError):
            deliver(consumer, "user.noted_fact", {})

        assert repository.search(MemoryCriteria()) == []


class TestIdempotence:
    def test_the_memory_id_is_deterministic_from_the_event_id(self) -> None:
        consumer, _, repository = build()

        deliver(consumer, "user.noted_fact", {"content": "algo"}, event_id="evt-42")

        expected_id = deterministic_memory_id(source="event", natural_key="evt-42")
        assert repository.get(expected_id) is not None

    def test_redelivering_the_same_event_reinforces_instead_of_duplicating(self) -> None:
        consumer, _, repository = build()
        recorded = make_recorded_event(
            make_event(
                event_id="evt-1",
                event_type="user.noted_fact",
                occurred_at=NOON,
                payload={"content": "algo aconteceu"},
            ),
            recorded_at=NOON,
        )

        consumer.handle(recorded)
        consumer.handle(recorded)
        consumer.handle(recorded)

        found = repository.search(MemoryCriteria())
        assert len(found) == 1
        assert found[0].reinforced_count == 2


def test_handle_never_touches_a_repository_it_was_not_given() -> None:
    """`handle` faz I/O deliberadamente aqui (ao contrário do Context), mas
    só através do MemoryManager injetado — nunca de um segundo repositório."""
    primary = FakeMemoryRepository()
    manager = MemoryManager(repository=primary, clock=frozen_clock(NOON))
    consumer = MemoryEventConsumer(manager)

    consumer.handle(
        make_recorded_event(
            make_event(
                event_type="user.noted_fact",
                occurred_at=NOON,
                payload={"content": "algo"},
            ),
            recorded_at=NOON,
        )
    )

    assert len(primary.search(MemoryCriteria())) == 1
