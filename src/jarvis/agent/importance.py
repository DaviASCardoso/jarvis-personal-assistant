"""Importance Engine: decidir, sem gastar um token, se vale raciocinar.

`PHASE-4.md §14` pede filtro determinístico e barato antes do LLM, e `§14`
proíbe explicitamente criar "um AI importance model" nesta fase — o que faz
sentido além do custo: um filtro que chama o modelo não filtra chamadas ao
modelo.

As cinco grandezas que o [ROADMAP 4.4](../../../ROADMAP.md) nomeia estão aqui,
cada uma calculada sobre dado que o sistema **realmente tem**:

| grandeza | de onde sai |
|---|---|
| `urgency` | proximidade do próximo compromisso, ou recência do próprio evento |
| `personal_relevance` | melhor score do retrieval de memória (Fase 3) |
| `temporal_relevance` | fração de campos de contexto ainda frescos |
| `interruption_cost` | disponibilidade e atividade declaradas no contexto |
| `importance` | a combinação ponderada das quatro |

Explicável no mesmo espírito de `memory/ranking.py`: componentes nomeados,
total derivado deles e `reasons` em rótulos fechados — nunca conteúdo. Um
`ignore` precisa poder ser justificado depois.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from jarvis.agent.input import EventTrigger
from jarvis.context.model import ContextField, CurrentContext, iter_fields
from jarvis.context.observation import Freshness
from jarvis.memory.retrieval import RetrievalResult

# Meia-vida da recência do evento: um acontecimento de meia hora atrás pesa
# metade do que pesava quando aconteceu.
RECENCY_HALF_LIFE: Final = timedelta(minutes=30)

_IMMINENT: Final = timedelta(minutes=15)
_SOON: Final = timedelta(minutes=60)

# Rótulos são slugs fechados (`context/observation.py`), então estas tabelas são
# exaustivas por construção — não há texto livre para escapar delas.
_BUSY_LABELS: Final = frozenset({"busy", "do_not_disturb", "focus"})
_FREE_LABELS: Final = frozenset({"free", "available", "idle"})
_DEMANDING_ACTIVITIES: Final = frozenset({"meeting", "focus", "working", "call"})

_COST_WHEN_BUSY: Final = 0.9
_COST_WHEN_DEMANDING: Final = 0.7
_COST_WHEN_FREE: Final = 0.1
_COST_WHEN_UNKNOWN: Final = 0.3

_NEUTRAL_TEMPORAL_RELEVANCE: Final = 0.5


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportanceWeights:
    """`interruption_cost` entra **subtraindo**: interromper alguém ocupado tem
    de ser mais difícil, não mais fácil."""

    urgency: float = 0.30
    personal_relevance: float = 0.30
    temporal_relevance: float = 0.15
    interruption_cost: float = 0.25


DEFAULT_IMPORTANCE_WEIGHTS: Final = ImportanceWeights()


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportanceAssessment:
    total: float
    urgency: float
    personal_relevance: float
    temporal_relevance: float
    interruption_cost: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _recency_term(occurred_at: datetime, now: datetime) -> float:
    elapsed = (now - occurred_at).total_seconds()
    if elapsed <= 0:
        return 1.0
    return math.pow(0.5, elapsed / RECENCY_HALF_LIFE.total_seconds())


def _schedule_term(context: CurrentContext) -> tuple[float, str | None]:
    observation = context.schedule.next_entry_at
    if observation is None or observation.freshness(context.as_of) is Freshness.STALE:
        return 0.0, None
    remaining = observation.value - context.as_of
    if remaining < timedelta(0):
        return 0.0, "schedule_past"
    if remaining <= _IMMINENT:
        return 1.0, "schedule_imminent"
    if remaining <= _SOON:
        return 0.7, "schedule_soon"
    return 0.3, "schedule_known"


def _label(context: CurrentContext, wanted: ContextField) -> str | None:
    """Valor textual e **fresco** de um campo; vencido não vale como estado atual."""
    for field_name, observation in iter_fields(context):
        if field_name is not wanted:
            continue
        if observation is None or observation.freshness(context.as_of) is Freshness.STALE:
            return None
        return observation.value if isinstance(observation.value, str) else None
    return None


def _interruption_cost(context: CurrentContext) -> tuple[float, str]:
    availability = _label(context, ContextField.AVAILABILITY)
    activity = _label(context, ContextField.ACTIVITY)

    if availability in _BUSY_LABELS:
        return _COST_WHEN_BUSY, "user_busy"
    if activity in _DEMANDING_ACTIVITIES:
        return _COST_WHEN_DEMANDING, "activity_demanding"
    if availability in _FREE_LABELS:
        return _COST_WHEN_FREE, "user_free"
    return _COST_WHEN_UNKNOWN, "availability_unknown"


def _temporal_relevance(context: CurrentContext) -> float:
    observed = [observation for _, observation in iter_fields(context) if observation is not None]
    if not observed:
        # Sem nenhuma observação não há como afirmar que o contexto é atual nem
        # que está velho — neutro é a única resposta honesta.
        return _NEUTRAL_TEMPORAL_RELEVANCE
    fresh = sum(
        1 for observation in observed if observation.freshness(context.as_of) is Freshness.FRESH
    )
    return fresh / len(observed)


def assess(
    trigger: EventTrigger,
    *,
    context: CurrentContext,
    memories: tuple[RetrievalResult, ...] = (),
    now: datetime,
    weights: ImportanceWeights = DEFAULT_IMPORTANCE_WEIGHTS,
) -> ImportanceAssessment:
    """Avalia um gatilho de evento. Mensagem do usuário não passa por aqui —
    ver `should_reason` e `runtime.py`."""
    reasons: list[str] = []

    schedule, schedule_reason = _schedule_term(context)
    recency = _recency_term(trigger.occurred_at, now)
    urgency = max(schedule, recency)
    if schedule_reason is not None:
        reasons.append(schedule_reason)
    if recency > schedule:
        reasons.append("event_recent" if recency >= 0.5 else "event_old")

    personal_relevance = max((result.score.total for result in memories), default=0.0)
    if not memories:
        reasons.append("no_relevant_memory")

    temporal_relevance = _temporal_relevance(context)
    interruption_cost, cost_reason = _interruption_cost(context)
    reasons.append(cost_reason)

    total = _clamp(
        weights.urgency * urgency
        + weights.personal_relevance * personal_relevance
        + weights.temporal_relevance * temporal_relevance
        - weights.interruption_cost * interruption_cost
    )

    return ImportanceAssessment(
        total=total,
        urgency=urgency,
        personal_relevance=personal_relevance,
        temporal_relevance=temporal_relevance,
        interruption_cost=interruption_cost,
        reasons=tuple(reasons),
    )


def should_reason(assessment: ImportanceAssessment, *, threshold: float) -> bool:
    """Acima do limiar, vale uma chamada ao modelo. Abaixo, silêncio — e o
    silêncio é uma decisão, não uma falha."""
    return assessment.total >= threshold
