"""`DecisionRecord`: uma decisão do agente, projetada para consulta.

Dado plano, como `interface/viewmodel.py`. Não carrega parâmetros de ação nem
conteúdo de memória — mesma disciplina de privacidade do `AuditEntry`
([ADR-0017](../../../docs/adr/0017-audit-trail-as-events.md)): a trilha prova
*que* decisão foi tomada e *com que* insumos, não repete o conteúdo deles.
"Registrar ações" (item do roadmap 7.4) não duplica a auditoria da Fase 5 — a
ligação é `correlation_id`, que `ActionRequest` já herda de `Decision`.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionRecord:
    decision_id: str
    decision_type: str
    reason: str
    message: str | None = None
    decided_at: datetime
    correlation_id: str
    causation_id: str | None = None
    consulted_llm: bool = False
    importance: float | None = None
    used_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    context_as_of: datetime | None = None
    action_skill: str | None = None
    reasoning: str | None = None
