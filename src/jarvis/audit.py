"""Port de auditoria, compartilhado pela camada de ação.

Vive na raiz, ao lado de `errors.py`, por uma razão de dependência e não de
gosto: `jarvis.policy` registra vereditos, `jarvis.tools` registra execuções de
Tool e `jarvis.execution` registra desfechos — e nenhum desses três pode importar
os outros dois sem desfazer as fronteiras que a Fase 5 existe para criar. Um port
usado por vários componentes que não se conhecem pertence a nenhum deles.

O que **nunca** entra num `AuditEntry`: parâmetros de ação, conteúdo de arquivo,
resposta de tool, credencial. Só identidade, categoria, veredito e duração. É por
isso que `parameters_fingerprint` existe — a trilha prova *qual* execução
aconteceu sem precisar guardar *o que* ela dizia
([`architecture-contracts.md §14`](../../docs/architecture-contracts.md#14-observability-contract)).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from jarvis.events.event import JsonValue


class AuditKind(StrEnum):
    """Os marcos auditáveis. O valor é o `event_type` que o adapter publica.

    Não há `action.started` nem `tool.execution_started`: o primeiro é redundante
    com o par `requested`/`completed`, e o segundo não tem consumidor operacional
    — a duração já viaja no marco de término (`PHASE-5.md §22`).
    """

    ACTION_REQUESTED = "action.requested"
    POLICY_EVALUATED = "policy.evaluated"
    CONFIRMATION_REQUESTED = "action.confirmation_requested"
    TOOL_COMPLETED = "tool.execution_completed"
    TOOL_FAILED = "tool.execution_failed"
    ACTION_COMPLETED = "action.completed"
    ACTION_FAILED = "action.failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    """Um marco da trilha.

    Dois campos desempatam marcos que se repetem dentro da mesma execução, e a
    distinção entre eles importa:

    - `ordinal` conta repetições **posicionais** — a primeira, a segunda e a
      terceira chamada de Tool de uma mesma execução;
    - `discriminator` distingue repetições **semânticas** — a mesma execução é
      avaliada pela política duas vezes (no pedido e depois da confirmação), e as
      duas avaliações produzem vereditos diferentes. Sem ele, o segundo
      `policy.evaluated` colidiria com o primeiro, e a trilha perderia
      justamente o veredito que autorizou a ação.

    É a combinação dos dois que permite ao adapter derivar um `event_id`
    determinístico por marco: republicar o **mesmo** marco é no-op, e registrar
    um marco **diferente** nunca é confundido com duplicata.
    """

    kind: AuditKind
    execution_id: str
    correlation_id: str
    occurred_at: datetime
    causation_id: str | None = None
    ordinal: int = 0
    discriminator: str = ""
    detail: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at precisa ser timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))

    @property
    def marker(self) -> str:
        """Chave natural do marco dentro da execução."""
        if self.discriminator:
            return f"{self.kind.value}:{self.ordinal}:{self.discriminator}"
        return f"{self.kind.value}:{self.ordinal}"


class AuditLog(Protocol):
    """Destino durável da trilha.

    `record` pode falhar, e a diferença importa: falha ao registrar
    `POLICY_EVALUATED` **aborta a execução** (sem trilha, sem ação); falha nos
    marcos posteriores é logada mas não desfaz o efeito já produzido, porque não
    existe compensação honesta para "o arquivo já foi escrito".
    """

    def record(self, entry: AuditEntry) -> None: ...
