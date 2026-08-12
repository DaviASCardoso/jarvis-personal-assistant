"""Prompt assembly: o que entra no envelope, o que é marcado e o que é cortado.

Duas garantias que este arquivo protege e que não são cosméticas:

- dado `stale` entra **marcado**, nunca omitido nem apresentado como certeza
  (contracts §6: quem decide se aceita é o consumidor);
- o corte é determinístico e nunca sacrifica o gatilho.
"""

import json
from datetime import timedelta
from typing import Any

import pytest

from jarvis.agent.conversation import Conversation, ConversationTurn
from jarvis.agent.errors import PromptTooLargeError
from jarvis.agent.input import EventSummary
from jarvis.agent.messages import ResponseFormat, Role
from jarvis.agent.prompt import (
    Capability,
    PromptBudget,
    PromptBuilder,
    ReasoningEnvelope,
)
from tests.agent_doubles import (
    NOON,
    make_context,
    make_event_trigger,
    make_retrieval_result,
    make_user_message,
)


def envelope(**overrides: Any) -> ReasoningEnvelope:
    fields: dict[str, Any] = {
        "now": NOON,
        "trigger": make_user_message(),
        "context": make_context(as_of=NOON, availability="free", place="home"),
    }
    fields.update(overrides)
    return ReasoningEnvelope(**fields)


def rendered(request_content: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(request_content)
    return decoded


def build(envelope_: ReasoningEnvelope, *, budget: PromptBudget | None = None) -> dict[str, Any]:
    builder = PromptBuilder(budget=budget) if budget is not None else PromptBuilder()
    request = builder.build(envelope_)
    return rendered(request.messages[0].content)


# --- forma da requisição -----------------------------------------------------


def test_the_request_asks_for_json_and_ends_with_the_user() -> None:
    request = PromptBuilder().build(envelope())

    assert request.response_format is ResponseFormat.JSON_OBJECT
    assert request.messages[-1].role is Role.USER
    assert request.system.strip()


def test_the_system_instruction_states_that_the_agent_does_not_execute() -> None:
    request = PromptBuilder().build(envelope())

    assert "propõe" in request.system
    assert "act_and_notify" in request.system


def test_a_repair_hint_becomes_a_second_user_message() -> None:
    request = PromptBuilder().build(envelope(), repair_hint="responda só o objeto")

    assert len(request.messages) == 2
    assert request.messages[1].content == "responda só o objeto"


def test_generation_parameters_reach_the_request() -> None:
    request = PromptBuilder().build(
        envelope(), temperature=0.9, max_output_tokens=64, timeout_seconds=5.0
    )

    assert (request.temperature, request.max_output_tokens, request.timeout_seconds) == (
        0.9,
        64,
        5.0,
    )


# --- seções do envelope ------------------------------------------------------


def test_every_section_is_present_even_when_empty() -> None:
    payload = build(envelope())

    assert set(payload) == {
        "now",
        "trigger",
        "current_context",
        "relevant_memories",
        "recent_events",
        "conversation",
        "available_capabilities",
        "constraints",
    }


def test_a_user_message_trigger_carries_its_text() -> None:
    payload = build(envelope(trigger=make_user_message(text="o que houve enquanto saí?")))

    assert payload["trigger"]["kind"] == "user_message"
    assert payload["trigger"]["text"] == "o que houve enquanto saí?"


def test_an_event_trigger_carries_its_payload() -> None:
    """O payload do gatilho entra inteiro: é o objeto do raciocínio."""
    payload = build(envelope(trigger=make_event_trigger(payload={"detail": "a impressão acabou"})))

    assert payload["trigger"]["kind"] == "event"
    assert payload["trigger"]["payload"] == {"detail": "a impressão acabou"}


def test_recent_events_never_carry_payload() -> None:
    """Mandar o conteúdo de N eventos "por contexto" a um serviço de nuvem é
    vazamento gratuito — só o gatilho justifica o payload."""
    summary = EventSummary(
        event_id="evt-9", event_type="user.noted_fact", source="manual-cli", occurred_at=NOON
    )

    payload = build(envelope(recent_events=(summary,)))

    assert payload["recent_events"] == [
        {"event_type": "user.noted_fact", "source": "manual-cli", "occurred_at": NOON.isoformat()}
    ]


def test_an_absent_context_field_stays_out_of_the_envelope() -> None:
    payload = build(envelope(context=make_context(as_of=NOON, availability="free")))

    assert "availability" in payload["current_context"]
    assert "place" not in payload["current_context"]


def test_a_stale_field_is_included_and_marked() -> None:
    context = make_context(
        as_of=NOON,
        availability="busy",
        observed_at=NOON - timedelta(hours=2),
        ttl=timedelta(minutes=5),
    )

    payload = build(envelope(context=context))

    assert payload["current_context"]["availability"]["freshness"] == "stale"


def test_a_memory_arrives_with_its_score_and_identity() -> None:
    payload = build(envelope(memories=(make_retrieval_result(total=0.77, memory_id="mem-1"),)))

    (memory,) = payload["relevant_memories"]
    assert memory["memory_id"] == "mem-1"
    assert memory["score"] == 0.77


def test_the_conversation_keeps_its_order() -> None:
    conversation = (
        Conversation(conversation_id="c-1")
        .append(ConversationTurn(role=Role.USER, text="primeira", at=NOON))
        .append(ConversationTurn(role=Role.ASSISTANT, text="segunda", at=NOON))
    )

    payload = build(envelope(conversation=conversation))

    assert [turn["text"] for turn in payload["conversation"]] == ["primeira", "segunda"]


# --- capacidades e restrições ------------------------------------------------


def test_with_no_capabilities_the_model_is_told_not_to_propose_action() -> None:
    """Na Fase 4 não existe Skill Registry, e o modelo precisa saber disso."""
    payload = build(envelope())

    assert payload["available_capabilities"] == []
    assert payload["constraints"]["capabilities_available"] is False
    assert "não proponha act" in payload["constraints"]["execution_note"]


def test_declared_capabilities_change_the_constraint() -> None:
    payload = build(
        envelope(capabilities=(Capability(name="send_notification", summary="avisa o usuário"),))
    )

    assert payload["constraints"]["capabilities_available"] is True
    assert payload["available_capabilities"][0]["name"] == "send_notification"


def test_the_constraints_list_the_six_decision_types() -> None:
    payload = build(envelope())

    assert payload["constraints"]["decision_types"] == [
        "ignore",
        "remember",
        "notify",
        "ask",
        "act",
        "act_and_notify",
    ]


# --- orçamento ---------------------------------------------------------------


def test_the_number_of_memories_respects_the_budget() -> None:
    memories = tuple(
        make_retrieval_result(total=0.9 - index / 100, memory_id=f"mem-{index}")
        for index in range(20)
    )

    payload = build(envelope(memories=memories), budget=PromptBudget(max_memories=3))

    assert len(payload["relevant_memories"]) == 3


def test_only_the_most_recent_turns_are_kept() -> None:
    conversation = Conversation(conversation_id="c-1")
    for index in range(10):
        conversation = conversation.append(
            ConversationTurn(role=Role.USER, text=f"turno {index}", at=NOON)
        )

    payload = build(envelope(conversation=conversation), budget=PromptBudget(max_history_turns=2))

    assert [turn["text"] for turn in payload["conversation"]] == ["turno 8", "turno 9"]


def test_long_content_is_clipped_per_item() -> None:
    payload = build(
        envelope(memories=(make_retrieval_result(content="x" * 900),)),
        budget=PromptBudget(max_chars_per_item=50),
    )

    assert payload["relevant_memories"][0]["content"].endswith("…")
    assert len(payload["relevant_memories"][0]["content"]) == 51


def test_trimming_drops_conversation_before_events_and_memories() -> None:
    """A ordem de corte é contrato, não detalhe: turnos antigos primeiro,
    depois eventos, e só então memórias — as mais fracas."""
    conversation = Conversation(conversation_id="c-1")
    for index in range(6):
        conversation = conversation.append(
            ConversationTurn(role=Role.USER, text=f"turno longo {'y' * 200} {index}", at=NOON)
        )
    events = tuple(
        EventSummary(
            event_id=f"e-{index}", event_type="demo.happened", source="cli", occurred_at=NOON
        )
        for index in range(10)
    )
    memories = tuple(
        make_retrieval_result(total=0.9 - index / 100, memory_id=f"mem-{index}")
        for index in range(8)
    )

    payload = build(
        envelope(conversation=conversation, recent_events=events, memories=memories),
        budget=PromptBudget(max_envelope_chars=2200),
    )

    assert payload["conversation"] == []
    assert payload["relevant_memories"], "memórias são o último recurso a ser cortado"
    assert payload["constraints"]["omitted"]["conversation_turns"] == 6


def test_the_lowest_scored_memories_go_first() -> None:
    memories = tuple(
        make_retrieval_result(total=0.9 - index / 10, memory_id=f"mem-{index}", content="z" * 300)
        for index in range(8)
    )

    payload = build(envelope(memories=memories), budget=PromptBudget(max_envelope_chars=1500))

    kept = [memory["memory_id"] for memory in payload["relevant_memories"]]
    assert kept == sorted(kept, key=lambda name: int(name.split("-")[1]))
    assert "mem-7" not in kept


def test_the_trigger_is_never_sacrificed() -> None:
    """Se nem o gatilho couber, falhar é melhor que enviar um prompt mutilado."""
    trigger = make_user_message(text="p" * 5000)

    with pytest.raises(PromptTooLargeError):
        build(envelope(trigger=trigger), budget=PromptBudget(max_envelope_chars=1000))


def test_what_was_omitted_is_reported_to_the_model() -> None:
    conversation = Conversation(conversation_id="c-1")
    for index in range(4):
        conversation = conversation.append(
            ConversationTurn(role=Role.USER, text=f"turno {'w' * 300} {index}", at=NOON)
        )

    payload = build(
        envelope(conversation=conversation), budget=PromptBudget(max_envelope_chars=1200)
    )

    assert payload["constraints"]["omitted"]["conversation_turns"] > 0


def test_building_the_same_envelope_twice_gives_the_same_prompt() -> None:
    fixed = envelope(memories=(make_retrieval_result(memory_id="m-1"),))

    assert PromptBuilder().build(fixed) == PromptBuilder().build(fixed)
