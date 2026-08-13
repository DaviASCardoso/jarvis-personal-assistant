"""A trilha de auditoria: os nove eventos, a cadeia causal e o que eles não contêm.

A pergunta que estes testes respondem é a da `PHASE-5.md §23`: dá para reconstruir
depois quem pediu, o que foi decidido, sob qual regra, com qual ferramenta e com
qual resultado — lendo só o Event Store.
"""

from datetime import UTC, datetime

import pytest

from jarvis.audit import AuditEntry, AuditKind
from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE, SqliteEventStore
from jarvis.events.bus import EventBus
from jarvis.events.publisher import EventPublisher
from jarvis.execution.adapters.event_audit import EventAuditLog
from jarvis.execution.events import (
    ACTION_EVENT_TYPES,
    CONFIRMATION_DENIED,
    CONFIRMATION_GRANTED,
    audit_event,
    confirmation_event,
    read_confirmation,
)

NOON = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def make_entry(**changes: object) -> AuditEntry:
    fields: dict[str, object] = {
        "kind": AuditKind.ACTION_REQUESTED,
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
        "occurred_at": NOON,
        "detail": {"skill": "file.read"},
    }
    fields.update(changes)
    return AuditEntry(**fields)  # type: ignore[arg-type]


class TestEventShape:
    def test_the_event_type_is_the_audit_kind(self) -> None:
        event = audit_event(make_entry(kind=AuditKind.POLICY_EVALUATED))

        assert event.event_type == "policy.evaluated"
        assert event.source == "jarvis-execution"

    def test_every_audit_kind_is_a_valid_event_type(self) -> None:
        """`Event` valida o formato do tipo; um marco novo não pode quebrá-lo."""
        for kind in AuditKind:
            assert audit_event(make_entry(kind=kind)).event_type == kind.value

    def test_the_execution_id_is_always_in_the_payload(self) -> None:
        event = audit_event(make_entry())

        assert event.payload["execution_id"] == "exec-1"

    def test_the_correlation_comes_from_the_entry(self) -> None:
        event = audit_event(make_entry(correlation_id="corr-42"))

        assert event.correlation_id == "corr-42"

    def test_the_causation_links_the_previous_step(self) -> None:
        event = audit_event(make_entry(causation_id="evt-origem"))

        assert event.causation_id == "evt-origem"

    def test_the_nine_event_types_are_declared(self) -> None:
        expected = {
            "action.requested",
            "policy.evaluated",
            "action.confirmation_requested",
            "action.confirmation_granted",
            "action.confirmation_denied",
            "tool.execution_completed",
            "tool.execution_failed",
            "action.completed",
            "action.failed",
        }

        assert set(ACTION_EVENT_TYPES) == expected


class TestDeterministicIdentity:
    def test_the_same_marker_produces_the_same_event_id(self) -> None:
        first = audit_event(make_entry())
        second = audit_event(make_entry())

        assert first.event_id == second.event_id

    def test_different_markers_produce_different_ids(self) -> None:
        requested = audit_event(make_entry(kind=AuditKind.ACTION_REQUESTED))
        completed = audit_event(make_entry(kind=AuditKind.ACTION_COMPLETED))

        assert requested.event_id != completed.event_id

    def test_the_ordinal_separates_repeated_markers(self) -> None:
        first = audit_event(make_entry(kind=AuditKind.TOOL_COMPLETED, ordinal=0))
        second = audit_event(make_entry(kind=AuditKind.TOOL_COMPLETED, ordinal=1))

        assert first.event_id != second.event_id

    def test_the_discriminator_separates_the_two_policy_evaluations(self) -> None:
        """Uma execução confirmada é avaliada duas vezes, e as duas contam.

        Sem o discriminador, o veredito que **autoriza** colidiria com o que
        pediu confirmação, e a trilha guardaria só o primeiro.
        """
        asked = audit_event(
            make_entry(kind=AuditKind.POLICY_EVALUATED, discriminator="require_confirmation")
        )
        allowed = audit_event(make_entry(kind=AuditKind.POLICY_EVALUATED, discriminator="allow"))

        assert asked.event_id != allowed.event_id

    def test_the_same_discriminator_still_deduplicates(self) -> None:
        first = audit_event(make_entry(kind=AuditKind.POLICY_EVALUATED, discriminator="allow"))
        second = audit_event(make_entry(kind=AuditKind.POLICY_EVALUATED, discriminator="allow"))

        assert first.event_id == second.event_id

    def test_different_executions_never_collide(self) -> None:
        first = audit_event(make_entry(execution_id="exec-1"))
        second = audit_event(make_entry(execution_id="exec-2"))

        assert first.event_id != second.event_id


class TestConfirmationEvents:
    def test_granting_and_denying_are_different_types(self) -> None:
        granted = confirmation_event(
            granted=True,
            execution_id="exec-1",
            parameters_fingerprint="f" * 64,
            correlation_id="corr-1",
            occurred_at=NOON,
        )
        denied = confirmation_event(
            granted=False,
            execution_id="exec-1",
            parameters_fingerprint="f" * 64,
            correlation_id="corr-1",
            occurred_at=NOON,
            reason="mudei de ideia",
        )

        assert granted.event_type == CONFIRMATION_GRANTED
        assert denied.event_type == CONFIRMATION_DENIED
        assert denied.payload["reason"] == "mudei de ideia"

    def test_the_answer_carries_the_fingerprint_not_the_parameters(self) -> None:
        event = confirmation_event(
            granted=True,
            execution_id="exec-1",
            parameters_fingerprint="f" * 64,
            correlation_id="corr-1",
            occurred_at=NOON,
        )

        assert set(event.payload) == {"execution_id", "parameters_fingerprint"}

    def test_confirming_twice_is_the_same_event(self) -> None:
        """`event_id` determinístico: reemitir é no-op no store."""
        args: dict[str, object] = {
            "granted": True,
            "execution_id": "exec-1",
            "parameters_fingerprint": "f" * 64,
            "correlation_id": "corr-1",
            "occurred_at": NOON,
        }

        assert confirmation_event(**args).event_id == confirmation_event(**args).event_id  # type: ignore[arg-type]

    def test_reading_a_payload_requires_both_fields(self) -> None:
        assert read_confirmation({"execution_id": "e", "parameters_fingerprint": "f"}) == (
            "e",
            "f",
            "",
        )
        with pytest.raises(ValueError):
            read_confirmation({"execution_id": "e"})
        with pytest.raises(ValueError):
            read_confirmation({"parameters_fingerprint": "f"})


class TestAuditLogAdapter:
    def test_a_marker_becomes_a_stored_event(self) -> None:
        with SqliteEventStore.open(IN_MEMORY_DATABASE) as store:
            EventAuditLog(EventPublisher(store=store, bus=EventBus())).record(make_entry())

            stored = store.read_by_type("action.requested")

            assert len(stored) == 1
            assert stored[0].event.payload["execution_id"] == "exec-1"

    def test_republishing_the_same_marker_is_a_no_op(self) -> None:
        with SqliteEventStore.open(IN_MEMORY_DATABASE) as store:
            audit = EventAuditLog(EventPublisher(store=store, bus=EventBus()))

            audit.record(make_entry())
            audit.record(make_entry())

            assert len(store.read_by_type("action.requested")) == 1

    def test_the_whole_chain_is_queryable_by_correlation(self) -> None:
        with SqliteEventStore.open(IN_MEMORY_DATABASE) as store:
            audit = EventAuditLog(EventPublisher(store=store, bus=EventBus()))
            for kind in (
                AuditKind.ACTION_REQUESTED,
                AuditKind.POLICY_EVALUATED,
                AuditKind.TOOL_COMPLETED,
                AuditKind.ACTION_COMPLETED,
            ):
                audit.record(make_entry(kind=kind, correlation_id="corr-42"))

            chain = store.read_by_correlation("corr-42")

            assert [item.event.event_type for item in chain] == [
                "action.requested",
                "policy.evaluated",
                "tool.execution_completed",
                "action.completed",
            ]
