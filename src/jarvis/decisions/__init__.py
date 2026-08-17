"""Decision Log (Fase 7.4): a trilha consultável de decisões do agente, como
eventos — mesmo padrão do audit trail da Fase 5
([ADR-0017](../../../docs/adr/0017-audit-trail-as-events.md)).

Não depende de `jarvis.agent`: `decision_event` recebe primitivos, não
`Decision`/`AgentTurn`. Quem publica o evento é sempre o composition root.
"""

from jarvis.decisions.errors import DecisionLogError, InvalidDecisionRecordError
from jarvis.decisions.events import DECISION_RECORDED, decision_event, read_decision
from jarvis.decisions.query import project_decisions
from jarvis.decisions.record import DecisionRecord

__all__ = [
    "DECISION_RECORDED",
    "DecisionLogError",
    "DecisionRecord",
    "InvalidDecisionRecordError",
    "decision_event",
    "project_decisions",
    "read_decision",
]
