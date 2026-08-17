"""`Decision`: as seis variantes, a matriz de validação e o parsing.

A propriedade mais importante testada aqui não é uma regra de campo: é que
`Decision` **não tem como executar nada**. Ver
`test_a_decision_carries_no_executable_behaviour`.
"""

import json
from datetime import UTC, datetime

import pytest

from jarvis.agent.decision import (
    ActionProposal,
    Decision,
    DecisionType,
    MemoryProposal,
    parse_decision,
)
from jarvis.agent.errors import InvalidDecisionError
from jarvis.memory.memory import MemoryType

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

MEMORY = MemoryProposal(type=MemoryType.PREFERENCE, content="prefere café sem açúcar")
ACTION = ActionProposal(skill="send_notification", parameters={"message": "pronto"})
REASONING = "a capacidade send_notification está disponível e resolve o pedido"


def make(**overrides: object) -> Decision:
    fields: dict[str, object] = {
        "decision_id": "dec-1",
        "type": DecisionType.IGNORE,
        "reason": "nada a fazer",
        "decided_at": NOW,
        "correlation_id": "corr-1",
    }
    fields.update(overrides)
    return Decision(**fields)  # type: ignore[arg-type]


# --- as seis variantes, no formato válido mínimo -----------------------------


@pytest.mark.parametrize(
    ("decision_type", "extra"),
    [
        (DecisionType.IGNORE, {}),
        (DecisionType.REMEMBER, {"memory": MEMORY}),
        (DecisionType.NOTIFY, {"message": "olá"}),
        (DecisionType.ASK, {"message": "qual horário?"}),
        (DecisionType.ACT, {"action": ACTION, "reasoning": REASONING}),
        (
            DecisionType.ACT_AND_NOTIFY,
            {"action": ACTION, "message": "feito", "reasoning": REASONING},
        ),
    ],
    ids=lambda value: value.value if isinstance(value, DecisionType) else "",
)
def test_each_variant_accepts_its_minimal_shape(
    decision_type: DecisionType, extra: dict[str, object]
) -> None:
    decision = make(type=decision_type, **extra)

    assert decision.type is decision_type


def test_every_decision_type_appears_in_the_validation_matrix() -> None:
    """Impede que uma variante nova entre sem regra de forma."""
    from jarvis.agent.decision import _FORBIDDEN, _REQUIRED

    assert set(_REQUIRED) == set(DecisionType)
    assert set(_FORBIDDEN) == set(DecisionType)


@pytest.mark.parametrize(
    ("decision_type", "extra"),
    [
        (DecisionType.REMEMBER, {}),
        (DecisionType.NOTIFY, {}),
        (DecisionType.ASK, {}),
        (DecisionType.ACT, {}),
        (DecisionType.ACT, {"action": ACTION}),
        (DecisionType.ACT_AND_NOTIFY, {"action": ACTION}),
        (DecisionType.ACT_AND_NOTIFY, {"action": ACTION, "message": "feito"}),
    ],
)
def test_a_variant_without_its_required_field_is_refused(
    decision_type: DecisionType, extra: dict[str, object]
) -> None:
    with pytest.raises(InvalidDecisionError, match="exige"):
        make(type=decision_type, **extra)


@pytest.mark.parametrize(
    ("decision_type", "extra"),
    [
        (DecisionType.IGNORE, {"message": "algo"}),
        (DecisionType.IGNORE, {"action": ACTION}),
        (DecisionType.REMEMBER, {"memory": MEMORY, "action": ACTION}),
        (DecisionType.NOTIFY, {"message": "olá", "action": ACTION}),
        (DecisionType.ACT, {"action": ACTION, "message": "olá", "reasoning": REASONING}),
    ],
)
def test_a_variant_with_a_forbidden_field_is_refused(
    decision_type: DecisionType, extra: dict[str, object]
) -> None:
    with pytest.raises(InvalidDecisionError, match="não admite"):
        make(type=decision_type, **extra)


def test_only_act_variants_propose_action() -> None:
    assert make(type=DecisionType.ACT, action=ACTION, reasoning=REASONING).proposes_action
    assert make(
        type=DecisionType.ACT_AND_NOTIFY, action=ACTION, message="x", reasoning=REASONING
    ).proposes_action
    assert not make().proposes_action
    assert not make(type=DecisionType.NOTIFY, message="x").proposes_action


# --- a garantia estrutural ---------------------------------------------------


def test_a_decision_carries_no_executable_behaviour() -> None:
    """O coração do ADR-0003: uma `Decision` é dado, não comando.

    Se algum dia alguém acrescentar `execute()`, um callback ou um campo
    `Callable`, este teste quebra antes de a Fase 5 existir.
    """
    decision = make(type=DecisionType.ACT, action=ACTION, reasoning=REASONING)

    public_callables = [
        name
        for name in dir(decision)
        if not name.startswith("_") and callable(getattr(decision, name))
    ]
    assert public_callables == []

    for value in (decision.action, decision.memory, decision.message, decision.reasoning):
        assert not callable(value)


def test_action_parameters_are_frozen() -> None:
    action = ActionProposal(skill="demo", parameters={"nested": {"a": [1, 2]}})

    with pytest.raises(TypeError):
        action.parameters["nested"] = {}  # type: ignore[index]


# --- validação de campo ------------------------------------------------------


def test_decided_at_must_be_timezone_aware() -> None:
    with pytest.raises(InvalidDecisionError, match="timezone-aware"):
        make(decided_at=datetime(2026, 8, 12, 12, 0))


def test_reason_is_always_required() -> None:
    with pytest.raises(InvalidDecisionError):
        make(reason="   ")


def test_an_overlong_message_is_refused() -> None:
    with pytest.raises(InvalidDecisionError, match="excede"):
        make(type=DecisionType.NOTIFY, message="x" * 5000)


def test_an_overlong_reasoning_is_refused() -> None:
    with pytest.raises(InvalidDecisionError, match="excede"):
        make(type=DecisionType.ACT, action=ACTION, reasoning="x" * 5000)


def test_reasoning_is_optional_outside_act_variants() -> None:
    decision = make(type=DecisionType.NOTIFY, message="oi")

    assert decision.reasoning is None


def test_a_skill_name_must_be_a_slug() -> None:
    with pytest.raises(InvalidDecisionError, match="casa com"):
        ActionProposal(skill="Enviar Email!")


def test_the_refused_skill_name_never_appears_in_the_message() -> None:
    """O nome vem do modelo, que pode ter ecoado conteúdo de um evento."""
    with pytest.raises(InvalidDecisionError) as error:
        ActionProposal(skill="Dra Marina 15h")

    assert "Marina" not in str(error.value)


@pytest.mark.parametrize("value", [-0.1, 1.1, "alto"])
def test_memory_scores_outside_the_unit_interval_are_refused(value: object) -> None:
    with pytest.raises(InvalidDecisionError):
        MemoryProposal(type=MemoryType.EPISODIC, content="x", importance=value)  # type: ignore[arg-type]


# --- parsing -----------------------------------------------------------------


def parse(text: str) -> Decision:
    return parse_decision(
        text, decision_id="dec-1", correlation_id="corr-1", decided_at=NOW, causation_id="evt-1"
    )


def test_parsing_a_clean_object() -> None:
    decision = parse('{"type": "notify", "reason": "responder", "message": "oi"}')

    assert decision.type is DecisionType.NOTIFY
    assert decision.message == "oi"
    assert decision.causation_id == "evt-1"


def test_identity_and_correlation_never_come_from_the_model() -> None:
    """Deixar o modelo escolher `correlation_id` seria deixá-lo reescrever a
    cadeia de observabilidade."""
    decision = parse(
        '{"type": "ignore", "reason": "nada", "decision_id": "forjado", '
        '"correlation_id": "sequestrado"}'
    )

    assert decision.decision_id == "dec-1"
    assert decision.correlation_id == "corr-1"


@pytest.mark.parametrize(
    "wrapper",
    [
        "```json\n{body}\n```",
        "```\n{body}\n```",
        "Claro! Aqui está:\n{body}",
        "{body}\n\nEspero ter ajudado.",
        "   {body}   ",
    ],
)
def test_parsing_survives_fences_and_surrounding_prose(wrapper: str) -> None:
    body = '{"type": "ignore", "reason": "nada a fazer"}'

    assert parse(wrapper.format(body=body)).type is DecisionType.IGNORE


def test_parsing_a_full_action_decision() -> None:
    decision = parse(
        json.dumps(
            {
                "type": "act_and_notify",
                "reason": "o usuário pediu",
                "message": "vou avisar",
                "action": {"skill": "send_notification", "parameters": {"to": "davi"}},
                "reasoning": "a capacidade send_notification atende o pedido diretamente",
            }
        )
    )

    assert decision.action is not None
    assert decision.action.skill == "send_notification"
    assert dict(decision.action.parameters) == {"to": "davi"}
    assert decision.reasoning == "a capacidade send_notification atende o pedido diretamente"


def test_parsing_a_memory_decision() -> None:
    decision = parse(
        json.dumps(
            {
                "type": "remember",
                "reason": "preferência declarada",
                "memory": {
                    "type": "preference",
                    "content": "café sem açúcar",
                    "subject": "cafe.acucar",
                    "confidence": 0.9,
                },
            }
        )
    )

    assert decision.memory is not None
    assert decision.memory.type is MemoryType.PREFERENCE
    assert decision.memory.confidence == 0.9


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("isto não é json", "texto solto"),
        ("[1, 2, 3]", "array em vez de objeto"),
        ('{"reason": "faltou o tipo"}', "sem type"),
        ('{"type": "explodir", "reason": "tipo inexistente"}', "type desconhecido"),
        ('{"type": "notify", "reason": "sem mensagem"}', "falta campo exigido"),
        ('{"type": "ignore"}', "sem reason"),
        ('{"type": "act", "reason": "x", "action": {"parameters": {}}}', "action sem skill"),
        (
            '{"type": "act", "reason": "x", "action": {"skill": "s", "parameters": {}}}',
            "act sem reasoning",
        ),
        ('{"type": "remember", "reason": "x", "memory": {"content": "y"}}', "memory sem type"),
    ],
)
def test_malformed_responses_are_refused(text: str, reason: str) -> None:
    with pytest.raises(InvalidDecisionError):
        parse(text)


def test_parsing_is_deterministic() -> None:
    text = '{"type": "notify", "reason": "responder", "message": "oi"}'

    first, second = parse(text), parse(text)

    assert first == second
