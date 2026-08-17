"""Projeta uma sequência de eventos em `DecisionRecord`s.

Função pura — nenhum acesso a Event Store aqui. Quem lê o store e entrega a
sequência é o composition root (`ObservabilityService`, o comando
`jarvis decisions list`), mesmo desenho de `execution/consumer.py` e
`interface/service.py`.
"""

import logging
from collections.abc import Sequence

from jarvis.decisions.errors import InvalidDecisionRecordError
from jarvis.decisions.events import read_decision
from jarvis.decisions.record import DecisionRecord
from jarvis.events.event import RecordedEvent

logger = logging.getLogger(__name__)


def project_decisions(events: Sequence[RecordedEvent]) -> tuple[DecisionRecord, ...]:
    records: list[DecisionRecord] = []
    for recorded in events:
        try:
            record = read_decision(recorded)
        except InvalidDecisionRecordError as error:
            logger.warning(
                "decisions.event_invalid",
                extra={"event_id": recorded.event.event_id, "error_type": type(error).__name__},
            )
            continue
        if record is not None:
            records.append(record)
    return tuple(records)
