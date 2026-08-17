"""Traduz uma decisão em `Event`, e de volta.

Generaliza o padrão de auditoria da Fase 5 (`execution/events.py`,
[ADR-0017](../../../docs/adr/0017-audit-trail-as-events.md)) para o Agent
Runtime, com uma diferença deliberada: `decision_event` recebe **primitivos**
(`str`, `float`, `datetime`), nunca `Decision`/`AgentTurn`. É essa escolha que
mantém `jarvis.decisions` sem importar `jarvis.agent` — o composition root
extrai os campos de um `AgentTurn` antes de chamar este módulo, mesma
disciplina que já valia para `voice_session_event` em `cli.py` (que também
evita um import que a arquitetura não quer).

`event_id` é determinístico a partir de `decision_id`: reapresentar o mesmo
turno (retry, reconexão) é no-op no Event Store, nunca uma segunda linha na
trilha.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from jarvis.decisions.errors import InvalidDecisionRecordError
from jarvis.decisions.record import DecisionRecord
from jarvis.events.event import Event, JsonValue, RecordedEvent, deterministic_event_id

DECISION_RECORDED: Final = "agent.decision_recorded"
SUPPORTED_SCHEMA_VERSION: Final = 1


def decision_event(
    *,
    decision_id: str,
    decision_type: str,
    reason: str,
    message: str | None = None,
    decided_at: datetime,
    correlation_id: str,
    causation_id: str | None = None,
    consulted_llm: bool,
    importance: float | None = None,
    used_memory_ids: Sequence[str] = (),
    context_as_of: datetime | None = None,
    action_skill: str | None = None,
    source: str,
) -> Event:
    payload: dict[str, JsonValue] = {
        "decision_id": decision_id,
        "decision_type": decision_type,
        "reason": reason,
        "consulted_llm": consulted_llm,
        "used_memory_ids": list(used_memory_ids),
    }
    if message is not None:
        payload["message"] = message
    if importance is not None:
        payload["importance"] = importance
    if context_as_of is not None:
        payload["context_as_of"] = context_as_of.astimezone(UTC).isoformat()
    if action_skill is not None:
        payload["action_skill"] = action_skill

    return Event(
        event_id=deterministic_event_id(source=source, natural_key=decision_id),
        event_type=DECISION_RECORDED,
        source=source,
        occurred_at=decided_at,
        payload=payload,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _optional_str(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _optional_float(payload: dict[str, JsonValue], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def read_decision(recorded: RecordedEvent) -> DecisionRecord | None:
    """Traduz um `RecordedEvent` de volta a `DecisionRecord`, ou `None` se o
    evento não for um deste tipo/versão que este código entende."""
    event = recorded.event
    if event.event_type != DECISION_RECORDED:
        return None
    if event.schema_version != SUPPORTED_SCHEMA_VERSION:
        # Contrato §5: versão desconhecida é tratada explicitamente, nunca
        # assumida como a mais recente.
        return None

    payload = dict(event.payload)
    decision_id = _optional_str(payload, "decision_id")
    decision_type = _optional_str(payload, "decision_type")
    reason = _optional_str(payload, "reason")
    if decision_id is None or decision_type is None or reason is None:
        raise InvalidDecisionRecordError(
            f"{event.event_id}: payload sem decision_id/decision_type/reason"
        )

    consulted_llm = payload.get("consulted_llm")
    if not isinstance(consulted_llm, bool):
        raise InvalidDecisionRecordError(f"{event.event_id}: consulted_llm ausente ou inválido")

    raw_memory_ids = payload.get("used_memory_ids", ())
    if not isinstance(raw_memory_ids, tuple) or not all(
        isinstance(item, str) for item in raw_memory_ids
    ):
        raise InvalidDecisionRecordError(f"{event.event_id}: used_memory_ids inválido")

    context_as_of_raw = _optional_str(payload, "context_as_of")
    context_as_of = None
    if context_as_of_raw is not None:
        try:
            context_as_of = datetime.fromisoformat(context_as_of_raw)
        except ValueError as error:
            raise InvalidDecisionRecordError(
                f"{event.event_id}: context_as_of não é ISO-8601 válido"
            ) from error

    return DecisionRecord(
        decision_id=decision_id,
        decision_type=decision_type,
        reason=reason,
        message=_optional_str(payload, "message"),
        decided_at=event.occurred_at,
        correlation_id=event.correlation_id or event.event_id,
        causation_id=event.causation_id,
        consulted_llm=consulted_llm,
        importance=_optional_float(payload, "importance"),
        used_memory_ids=tuple(raw_memory_ids),
        context_as_of=context_as_of,
        action_skill=_optional_str(payload, "action_skill"),
    )
