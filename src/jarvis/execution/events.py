"""Os eventos da camada de ação.

Nove tipos, e a lista fecha aí. `PHASE-5.md §22` avisa para não criar evento
"porque parece legal", então cada um precisa responder a uma pergunta que a §23
faz sobre auditoria:

| evento | pergunta que ele responde |
|---|---|
| `action.requested` | quem solicitou, e qual era a intenção? |
| `policy.evaluated` | qual política foi aplicada, e qual foi o veredito? |
| `action.confirmation_requested` | foi pedida confirmação? |
| `action.confirmation_granted` / `_denied` | o usuário respondeu o quê? |
| `tool.execution_completed` / `_failed` | qual Tool, qual backend, quanto tempo? |
| `action.completed` / `action.failed` | qual foi o resultado, e quando? |

Não existe `action.started` (redundante com o par `requested`/`completed`) nem
`tool.execution_started` (sem consumidor operacional; a duração já vai no
término).

**Nenhum payload daqui carrega os parâmetros da ação** — só o
`parameters_fingerprint`. Quem guarda parâmetros é o `ActionRepository`, que é
apagável; um evento é para sempre
([ADR-0017](../../../docs/adr/0017-audit-trail-as-events.md)).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from jarvis.audit import AuditEntry, AuditKind
from jarvis.events.event import Event, JsonValue, deterministic_event_id

ACTION_SOURCE: Final = "jarvis-execution"
CONFIRMATION_SOURCE: Final = "jarvis-cli"

CONFIRMATION_GRANTED: Final = "action.confirmation_granted"
CONFIRMATION_DENIED: Final = "action.confirmation_denied"

CONFIRMATION_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {CONFIRMATION_GRANTED, CONFIRMATION_DENIED}
)

AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset(kind.value for kind in AuditKind)

ACTION_EVENT_TYPES: Final[frozenset[str]] = AUDIT_EVENT_TYPES | CONFIRMATION_EVENT_TYPES


def audit_event(entry: AuditEntry, *, source: str = ACTION_SOURCE) -> Event:
    """Traduz um marco de auditoria no `Event` correspondente.

    `event_id` determinístico a partir de `(execution_id, marco)`: republicar o
    mesmo marco é no-op no Event Store, e a trilha não ganha duplicata quando um
    retry reapresenta o mesmo passo (contrato §5).
    """
    payload: dict[str, JsonValue] = {"execution_id": entry.execution_id, **entry.detail}
    return Event(
        event_id=deterministic_event_id(
            source=source, natural_key=f"{entry.execution_id}:{entry.marker}"
        ),
        event_type=entry.kind.value,
        source=source,
        occurred_at=entry.occurred_at,
        payload=payload,
        correlation_id=entry.correlation_id,
        causation_id=entry.causation_id,
    )


def confirmation_event(
    *,
    granted: bool,
    execution_id: str,
    parameters_fingerprint: str,
    correlation_id: str,
    occurred_at: datetime,
    causation_id: str | None = None,
    reason: str = "",
) -> Event:
    """A resposta do usuário, como evento.

    `architecture-contracts.md §10.2` diz que a confirmação chega ao sistema como
    evento — é o que este construtor produz. Quem o publica é a interface (o CLI
    nesta fase, o Notification System na 7.3); quem o projeta em estado é o
    `ActionEventConsumer`. A interface **não** executa a ação: ela responde, e a
    retomada é um passo separado que volta a passar pelo Policy Engine.
    """
    event_type = CONFIRMATION_GRANTED if granted else CONFIRMATION_DENIED
    payload: dict[str, JsonValue] = {
        "execution_id": execution_id,
        "parameters_fingerprint": parameters_fingerprint,
    }
    if reason:
        payload["reason"] = reason
    return Event(
        event_id=deterministic_event_id(
            source=CONFIRMATION_SOURCE, natural_key=f"{execution_id}:{event_type}"
        ),
        event_type=event_type,
        source=CONFIRMATION_SOURCE,
        occurred_at=occurred_at,
        payload=payload,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def read_confirmation(payload: Mapping[str, JsonValue]) -> tuple[str, str, str]:
    """Extrai `(execution_id, parameters_fingerprint, reason)` de um payload.

    Devolve tupla em vez de um objeto novo: o consumer é a única coisa que lê
    isso, e um value object com um consumidor só seria peso sem uso.
    """
    execution_id = payload.get("execution_id")
    fingerprint = payload.get("parameters_fingerprint")
    reason = payload.get("reason", "")
    if not isinstance(execution_id, str) or not execution_id:
        raise ValueError("execution_id ausente ou inválido")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("parameters_fingerprint ausente ou inválido")
    return execution_id, fingerprint, reason if isinstance(reason, str) else ""
