"""View models e a serialização que vira `/api/state`."""

import json
from datetime import UTC, datetime

import pytest

from jarvis.interface.viewmodel import (
    MAX_MEMORY_CHARS,
    ConversationEntry,
    MemoryCard,
    PanelSnapshot,
    Severity,
    TimelineEntry,
    Toast,
    VoiceStatusView,
    entries_of,
    safe_summary,
    severity_of,
    to_json_object,
    truncate,
)
from tests.interface_doubles import PANEL_NOW, audit_event, external_event


def test_truncate_keeps_short_text_and_marks_what_it_cut() -> None:
    assert truncate("curto", limit=10) == "curto"
    assert truncate("a" * 20, limit=10) == "aaaaaaa..."


def test_a_trusted_event_shows_its_identity_fields() -> None:
    entry = TimelineEntry.from_recorded(
        audit_event("action.completed", payload={"skill": "file.write", "status": "ok"})
    )

    assert "action.completed" in entry.summary
    assert "skill=file.write" in entry.summary


def test_an_external_event_shows_only_its_type() -> None:
    # A regra que impede o painel de ecoar corpo de e-mail ou trecho de arquivo.
    recorded = external_event()

    summary = safe_summary(recorded)

    assert summary == "email.received"
    assert "secreto" not in summary
    assert "confidencial" not in summary


def test_an_external_event_with_a_key_from_the_allowlist_is_still_not_echoed() -> None:
    recorded = external_event(payload={"skill": "coisa vinda de fora", "status": "x"})

    assert safe_summary(recorded) == "email.received"


@pytest.mark.parametrize(
    ("event_type", "payload", "expected"),
    [
        ("action.completed", {}, Severity.SUCCESS),
        ("action.failed", {}, Severity.DANGER),
        ("action.confirmation_requested", {}, Severity.WARNING),
        ("policy.evaluated", {"decision": "deny"}, Severity.DANGER),
        ("policy.evaluated", {"decision": "allow"}, Severity.INFO),
        ("demo.happened", {}, Severity.INFO),
    ],
)
def test_severity_follows_what_the_event_means(
    event_type: str, payload: dict[str, str], expected: Severity
) -> None:
    assert severity_of(event_type, payload) is expected


def test_a_toast_id_is_deterministic_so_the_browser_can_deduplicate() -> None:
    entry = TimelineEntry.from_recorded(audit_event("action.failed"))

    assert Toast.from_entry(entry).toast_id == entry.event_id


def test_entries_preserve_the_order_they_came_in() -> None:
    events = [audit_event("action.requested"), audit_event("action.completed")]

    assert [entry.event_type for entry in entries_of(events)] == [
        "action.requested",
        "action.completed",
    ]


def test_the_json_contract_is_serializable_and_uses_iso_dates() -> None:
    snapshot = PanelSnapshot(
        revision=7,
        as_of=PANEL_NOW,
        voice=VoiceStatusView(state="speaking", session_id="s-1", at=PANEL_NOW),
        timeline=entries_of([audit_event("action.completed")]),
        memories=(
            MemoryCard(
                memory_id="m", type="preference", content="c", importance=0.5, confidence=0.9
            ),
        ),
        conversation=(ConversationEntry(role="user", text="oi", at=PANEL_NOW, session_id="s-1"),),
    )

    body = json.loads(json.dumps(to_json_object(snapshot)))

    assert body["revision"] == 7
    assert body["as_of"] == PANEL_NOW.isoformat()
    assert body["voice"]["state"] == "speaking"
    assert body["timeline"][0]["severity"] == "success"
    assert body["conversation"][0]["text"] == "oi"
    assert body["memories"][0]["score"] is None


def test_absent_values_are_null_not_an_empty_string() -> None:
    body = to_json_object(PanelSnapshot(revision=1, as_of=PANEL_NOW))

    assert body["voice"] == {
        "state": "idle",
        "session_id": None,
        "detail": "",
        "last_transcript": "",
        "last_reply": "",
        "at": None,
    }


def test_an_empty_snapshot_still_serializes_every_block() -> None:
    body = to_json_object(PanelSnapshot(revision=0, as_of=datetime.now(UTC)))

    for block in ("timeline", "context", "memories", "decisions", "actions", "tools"):
        assert body[block] == []


def test_long_memory_content_is_cut_before_it_reaches_the_page() -> None:
    assert len(truncate("x" * 500, limit=MAX_MEMORY_CHARS)) == MAX_MEMORY_CHARS
