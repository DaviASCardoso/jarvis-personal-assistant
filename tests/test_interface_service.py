"""`ObservabilityService`: os seis blocos do painel, montados a partir do Core."""

from datetime import timedelta

from jarvis.interface.service import ObservabilityService, memory_card_of
from jarvis.interface.viewmodel import TurnTrace
from jarvis.voice.session import TurnRole, VoiceSession, VoiceState, VoiceStatus, VoiceTurn
from tests.interface_doubles import (
    PANEL_NOW,
    FakeReaders,
    audit_event,
    current_context,
    external_event,
    frozen_clock,
    pending_action,
    stored_memory,
)


def service(readers: FakeReaders, **kwargs: object) -> ObservabilityService:
    return ObservabilityService(
        read_events=readers.read_events,
        read_context=readers.read_context,
        read_memories=readers.read_memories,
        read_pending=readers.read_pending,
        clock=frozen_clock(),
        **kwargs,  # type: ignore[arg-type]
    )


def _session() -> VoiceSession:
    return (
        VoiceSession(session_id="s-1", started_at=PANEL_NOW)
        .append(VoiceTurn(role=TurnRole.USER, text="que horas são", at=PANEL_NOW))
        .append(
            VoiceTurn(
                role=TurnRole.ASSISTANT,
                text="nove e vinte",
                at=PANEL_NOW + timedelta(seconds=1),
                latency_ms=900.0,
                decision_type="notify",
                correlation_id="s-1",
            )
        )
    )


# --- blocos ------------------------------------------------------------------


def test_an_empty_system_produces_an_empty_but_valid_snapshot() -> None:
    snapshot = service(FakeReaders()).snapshot(revision=3)

    assert snapshot.revision == 3
    assert snapshot.as_of == PANEL_NOW
    assert snapshot.timeline == ()
    assert snapshot.degraded == ()
    assert snapshot.voice.state == "idle"


def test_the_timeline_comes_from_the_event_store() -> None:
    readers = FakeReaders(events=[audit_event("action.requested"), external_event()])

    snapshot = service(readers).snapshot()

    assert [entry.event_type for entry in snapshot.timeline] == [
        "action.requested",
        "email.received",
    ]


def test_the_timeline_respects_the_configured_limit() -> None:
    readers = FakeReaders(
        events=[audit_event("action.requested", execution_id=f"e{i}") for i in range(9)]
    )

    snapshot = service(readers, timeline_limit=4).snapshot()

    assert len(snapshot.timeline) == 4


def test_the_context_block_distinguishes_never_seen_from_observed_absence() -> None:
    snapshot = service(FakeReaders(context=current_context())).snapshot()

    rows = {row.field: row for row in snapshot.context}
    assert rows["utc_offset"].value == "-03:00"
    assert rows["utc_offset"].source == "system-time"
    assert rows["activity"].value == "-"


def test_memories_used_in_the_turn_come_first_and_carry_their_score() -> None:
    stored = stored_memory()
    trace = TurnTrace(
        decision_type="notify",
        decided_at=PANEL_NOW,
        memories=(memory_card_of(stored, score=0.71, used=True),),
    )
    readers = FakeReaders(memories=[stored_memory(memory_id="mem-2", content="outra")])

    snapshot = service(readers).snapshot(trace=trace)

    assert snapshot.memories[0].used_in_turn is True
    assert snapshot.memories[0].score == 0.71
    assert snapshot.memories[1].memory_id == "mem-2"


def test_a_memory_used_in_the_turn_is_not_listed_twice() -> None:
    stored = stored_memory()
    trace = TurnTrace(
        decision_type="notify",
        decided_at=PANEL_NOW,
        memories=(memory_card_of(stored, score=0.5, used=True),),
    )

    snapshot = service(FakeReaders(memories=[stored])).snapshot(trace=trace)

    assert [card.memory_id for card in snapshot.memories] == ["mem-1"]


def test_decisions_show_the_current_turn_and_the_ones_before_it() -> None:
    trace = TurnTrace(
        decision_type="act_and_notify",
        decided_at=PANEL_NOW,
        reason="o usuário pediu",
        consulted_llm=True,
        importance=0.62,
    )

    snapshot = service(FakeReaders()).snapshot(session=_session(), trace=trace)

    assert snapshot.decisions[0].decision_type == "act_and_notify"
    assert snapshot.decisions[0].consulted_llm is True
    assert snapshot.decisions[1].message == "nove e vinte"


def test_actions_are_aggregated_by_execution_id_across_the_audit_trail() -> None:
    readers = FakeReaders(
        events=[
            audit_event("action.requested", payload={"skill": "file.write", "actor": "user"}),
            audit_event("policy.evaluated", payload={"decision": "allow", "rule_id": "granted"}),
            audit_event("action.completed", payload={"duration_ms": 12.5}),
        ]
    )

    snapshot = service(readers).snapshot()

    assert len(snapshot.actions) == 1
    action = snapshot.actions[0]
    assert action.skill == "file.write"
    assert action.verdict == "allow"
    assert action.rule_id == "granted"
    assert action.status == "completed"
    assert action.duration_ms == 12.5


def test_a_pending_action_appears_even_without_events() -> None:
    snapshot = service(FakeReaders(pending=[pending_action()])).snapshot()

    assert [card.execution_id for card in snapshot.actions] == ["exec-9"]
    assert snapshot.actions[0].status == "awaiting_confirmation"


def test_an_action_already_in_the_trail_is_not_duplicated_by_the_pending_list() -> None:
    readers = FakeReaders(
        events=[audit_event("action.requested", execution_id="exec-9", payload={"skill": "s"})],
        pending=[pending_action(execution_id="exec-9")],
    )

    snapshot = service(readers).snapshot()

    assert len(snapshot.actions) == 1


def test_tools_come_from_the_execution_events() -> None:
    readers = FakeReaders(
        events=[
            audit_event(
                "tool.execution_completed",
                payload={"tool_id": "local.fs.write", "backend_id": "local", "duration_ms": 4.0},
            ),
            audit_event("tool.execution_failed", payload={"tool_id": "mcp.printer.status"}),
        ]
    )

    snapshot = service(readers).snapshot()

    assert [card.status for card in snapshot.tools] == ["failed", "completed"]
    assert snapshot.tools[1].backend_id == "local"


def test_the_conversation_block_mirrors_the_session() -> None:
    snapshot = service(FakeReaders()).snapshot(session=_session())

    assert [entry.role for entry in snapshot.conversation] == ["user", "assistant"]
    assert snapshot.conversation[1].latency_ms == 900.0


def test_the_voice_block_shows_the_live_state() -> None:
    status = VoiceStatus(
        state=VoiceState.SPEAKING, at=PANEL_NOW, session_id="s-1", last_reply="nove e vinte"
    )

    snapshot = service(FakeReaders()).snapshot(voice=status)

    assert snapshot.voice.state == "speaking"
    assert snapshot.voice.last_reply == "nove e vinte"


# --- toasts ------------------------------------------------------------------


def test_only_the_closed_list_of_events_becomes_a_toast() -> None:
    readers = FakeReaders(
        events=[
            audit_event("action.failed"),
            audit_event("action.requested"),
            external_event(),
        ]
    )

    snapshot = service(readers).snapshot()

    assert [toast.title for toast in snapshot.toasts] == ["Ação falhou"]


def test_an_allowed_policy_verdict_is_not_a_toast() -> None:
    # O painel não é um Notification System: ele mostra o que merece atenção,
    # e uma ação autorizada não interrompe ninguém.
    readers = FakeReaders(events=[audit_event("policy.evaluated", payload={"decision": "allow"})])

    assert service(readers).snapshot().toasts == ()


def test_a_denial_is_a_toast() -> None:
    readers = FakeReaders(events=[audit_event("policy.evaluated", payload={"decision": "deny"})])

    assert [toast.severity.value for toast in service(readers).snapshot().toasts] == ["danger"]


# --- degradação --------------------------------------------------------------


def test_a_failing_store_degrades_one_block_not_the_whole_panel() -> None:
    readers = FakeReaders(
        events=[audit_event("action.completed")],
        memories=[stored_memory()],
        failing=frozenset({"memory"}),
    )

    snapshot = service(readers).snapshot()

    assert snapshot.degraded == ("memory",)
    assert snapshot.memories == ()
    assert len(snapshot.timeline) == 1


def test_every_store_failing_still_produces_a_snapshot() -> None:
    readers = FakeReaders(failing=frozenset({"events", "context", "memory", "actions"}))

    snapshot = service(readers).snapshot()

    assert set(snapshot.degraded) == {"events", "context", "memory", "actions"}
    assert snapshot.as_of == PANEL_NOW
