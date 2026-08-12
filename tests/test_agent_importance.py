"""Importance Engine: cada dimensão isolada, o total e o limiar.

A propriedade que este arquivo mais protege: a avaliação é **determinística e
não chama o LLM**. É o que torna o filtro capaz de reduzir chamadas ao modelo em
vez de multiplicá-las — nenhum double de provider aparece neste arquivo, porque
não há provider nenhum envolvido.
"""

from datetime import datetime, timedelta

import pytest

from jarvis.agent.importance import (
    DEFAULT_IMPORTANCE_WEIGHTS,
    ImportanceAssessment,
    assess,
    should_reason,
)
from jarvis.context.model import CurrentContext
from jarvis.memory.retrieval import RetrievalResult
from tests.agent_doubles import NOON, make_context, make_event_trigger, make_retrieval_result


def evaluate(
    *,
    context: CurrentContext | None = None,
    memories: tuple[RetrievalResult, ...] = (),
    occurred_at: datetime = NOON,
    now: datetime = NOON,
) -> ImportanceAssessment:
    return assess(
        make_event_trigger(occurred_at=occurred_at),
        context=context if context is not None else make_context(as_of=now),
        memories=memories,
        now=now,
    )


# --- urgency -----------------------------------------------------------------


def test_a_brand_new_event_is_maximally_recent() -> None:
    assert evaluate(occurred_at=NOON, now=NOON).urgency == pytest.approx(1.0)


def test_recency_halves_every_thirty_minutes() -> None:
    assessment = evaluate(occurred_at=NOON, now=NOON + timedelta(minutes=30))

    assert assessment.urgency == pytest.approx(0.5)


@pytest.mark.parametrize(("minutes_ahead", "expected"), [(10, 1.0), (45, 0.7), (600, 0.3)])
def test_an_upcoming_entry_raises_urgency(minutes_ahead: int, expected: float) -> None:
    """Evento velho, mas compromisso próximo: a urgência vem da agenda."""
    context = make_context(as_of=NOON, next_entry_at=NOON + timedelta(minutes=minutes_ahead))

    assessment = evaluate(context=context, occurred_at=NOON - timedelta(hours=6), now=NOON)

    assert assessment.urgency == pytest.approx(expected)


def test_a_stale_schedule_does_not_count_as_urgency() -> None:
    """Contracts §6: dado vencido não vira certeza sobre o presente."""
    context = make_context(
        as_of=NOON,
        next_entry_at=NOON + timedelta(minutes=5),
        observed_at=NOON - timedelta(hours=2),
        ttl=timedelta(minutes=10),
    )

    assessment = evaluate(context=context, occurred_at=NOON - timedelta(hours=6), now=NOON)

    assert assessment.urgency < 0.1


# --- personal relevance ------------------------------------------------------


def test_personal_relevance_is_the_best_retrieval_score() -> None:
    memories = (
        make_retrieval_result(total=0.4, memory_id="m-1"),
        make_retrieval_result(total=0.82, memory_id="m-2"),
        make_retrieval_result(total=0.1, memory_id="m-3"),
    )

    assert evaluate(memories=memories).personal_relevance == pytest.approx(0.82)


def test_without_memory_personal_relevance_is_zero_and_is_explained() -> None:
    assessment = evaluate()

    assert assessment.personal_relevance == 0.0
    assert "no_relevant_memory" in assessment.reasons


# --- temporal relevance ------------------------------------------------------


def test_temporal_relevance_is_the_fraction_of_fresh_fields() -> None:
    context = make_context(as_of=NOON, availability="free", place="home")

    assert evaluate(context=context).temporal_relevance == pytest.approx(1.0)


def test_a_context_with_no_observation_is_neutral_rather_than_zero() -> None:
    """Sem observação nenhuma não dá para afirmar que o contexto é atual nem
    que está velho."""
    assessment = evaluate(context=CurrentContext(as_of=NOON))

    assert assessment.temporal_relevance == pytest.approx(0.5)


def test_stale_fields_lower_temporal_relevance() -> None:
    context = make_context(
        as_of=NOON,
        availability="free",
        place="home",
        observed_at=NOON - timedelta(hours=3),
        ttl=timedelta(minutes=10),
    )

    assert evaluate(context=context).temporal_relevance == pytest.approx(0.0)


# --- interruption cost -------------------------------------------------------


@pytest.mark.parametrize(
    ("availability", "activity", "expected", "reason"),
    [
        ("busy", None, 0.9, "user_busy"),
        ("do_not_disturb", None, 0.9, "user_busy"),
        (None, "meeting", 0.7, "activity_demanding"),
        ("free", None, 0.1, "user_free"),
        (None, None, 0.3, "availability_unknown"),
    ],
)
def test_interruption_cost_reads_availability_then_activity(
    availability: str | None, activity: str | None, expected: float, reason: str
) -> None:
    context = make_context(as_of=NOON, availability=availability, activity=activity)

    assessment = evaluate(context=context)

    assert assessment.interruption_cost == pytest.approx(expected)
    assert reason in assessment.reasons


def test_interrupting_a_busy_user_scores_lower_than_interrupting_a_free_one() -> None:
    busy = evaluate(context=make_context(as_of=NOON, availability="busy"))
    free = evaluate(context=make_context(as_of=NOON, availability="free"))

    assert busy.total < free.total


# --- total e limiar ----------------------------------------------------------


def test_the_total_stays_inside_the_unit_interval() -> None:
    """O custo de interrupção entra subtraindo e poderia empurrar abaixo de 0."""
    assessment = evaluate(
        context=make_context(as_of=NOON, availability="busy"),
        occurred_at=NOON - timedelta(days=2),
    )

    assert 0.0 <= assessment.total <= 1.0


def test_the_total_is_the_weighted_combination_of_the_components() -> None:
    weights = DEFAULT_IMPORTANCE_WEIGHTS
    assessment = evaluate(context=make_context(as_of=NOON, availability="free"))

    expected = (
        weights.urgency * assessment.urgency
        + weights.personal_relevance * assessment.personal_relevance
        + weights.temporal_relevance * assessment.temporal_relevance
        - weights.interruption_cost * assessment.interruption_cost
    )
    assert assessment.total == pytest.approx(expected)


def test_the_assessment_is_deterministic() -> None:
    context = make_context(as_of=NOON, availability="free")

    assert evaluate(context=context) == evaluate(context=context)


def test_should_reason_compares_against_the_threshold() -> None:
    assessment = evaluate(context=make_context(as_of=NOON, availability="free"))

    assert should_reason(assessment, threshold=0.0)
    assert not should_reason(assessment, threshold=1.0)


def test_reasons_are_closed_labels_never_content() -> None:
    """`reasons` vai para log estruturado; conteúdo de evento não pode entrar."""
    assessment = evaluate(context=make_context(as_of=NOON, availability="busy"))

    assert assessment.reasons
    assert all(" " not in reason for reason in assessment.reasons)
