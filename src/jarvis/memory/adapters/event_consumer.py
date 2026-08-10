"""O Memory System como consumidor do Event System — direção única: entrada.

Contracts §3.3 não lista o Event System entre as dependências permitidas do
Memory Core (ao contrário de contracts §3.2, que lista Event System como
dependência legítima do Context Engine). Por isso a integração vive inteiramente
aqui, num adapter de Infrastructure: `memory.py`, `manager.py`, `retrieval.py`
etc. nunca importam `jarvis.events`. O Memory System também **não emite**
eventos nesta fase — ver `docs/memory-system.md`.

Ao contrário do `ContextEventConsumer` (que só muta estado em memória),
`handle()` aqui **faz I/O deliberadamente**: gravar uma memória é o efeito
pretendido do evento, não um efeito colateral. O bus é síncrono (ADR-0008) e a
escrita é local em SQLite — sub-milissegundo nesta escala. Aceitável enquanto o
único produtor for o CLI; o gatilho de revisão é o mesmo do ADR-0008 (watchers
contínuos de alto volume), não uma introdução local de `asyncio`.

Dois tipos de evento, o menor conjunto que demonstra o fluxo e cobre os dois
papéis que importam: uma preferência (que contradiz e supersede) e um fato
episódico (que consolida por repetição). Fontes reais (email, calendário)
pertencem às fases das capacidades correspondentes.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Final

from jarvis.events.event import Event, RecordedEvent
from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import (
    MemoryOrigin,
    MemoryType,
    Provenance,
    deterministic_memory_id,
    require_slug,
)

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION: Final = 1
_DEFAULT_STATED_CONFIDENCE: Final = 0.8


def _require_text(payload: Mapping[str, object], key: str, *, field_name: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidMemoryError(f"{field_name} precisa ser texto não vazio")
    return value


def _optional_confidence(payload: Mapping[str, object], key: str, *, field_name: str) -> float:
    value = payload.get(key)
    if value is None:
        return _DEFAULT_STATED_CONFIDENCE
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidMemoryError(f"{field_name} precisa ser numérico")
    return float(value)


def _optional_strings(
    payload: Mapping[str, object], key: str, *, field_name: str
) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    # `Event.payload` já congela listas em tuplas (events/event.py:_freeze_json).
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise InvalidMemoryError(f"{field_name} precisa ser uma lista de strings")
    return value


def _stated_preference(event: Event) -> dict[str, object]:
    payload = event.payload
    subject = require_slug(
        _require_text(payload, "subject", field_name="payload.subject"),
        field_name="payload.subject",
    )
    return {
        "type": MemoryType.PREFERENCE,
        "content": _require_text(payload, "content", field_name="payload.content"),
        "provenance": Provenance(origin=MemoryOrigin.USER, reference=event.event_id),
        "subject": subject,
        "confidence": _optional_confidence(payload, "confidence", field_name="payload.confidence"),
    }


def _noted_fact(event: Event) -> dict[str, object]:
    payload = event.payload
    kwargs: dict[str, object] = {
        "type": MemoryType.EPISODIC,
        "content": _require_text(payload, "content", field_name="payload.content"),
        "provenance": Provenance(origin=MemoryOrigin.EVENT, reference=event.event_id),
        "entities": _optional_strings(payload, "entities", field_name="payload.entities"),
        "tags": _optional_strings(payload, "tags", field_name="payload.tags"),
    }
    if payload.get("subject") is not None:
        kwargs["subject"] = require_slug(
            _require_text(payload, "subject", field_name="payload.subject"),
            field_name="payload.subject",
        )
    return kwargs


_TRANSLATIONS: Final[Mapping[str, Callable[[Event], dict[str, object]]]] = {
    "user.stated_preference": _stated_preference,
    "user.noted_fact": _noted_fact,
}

MEMORY_EVENT_TYPES: Final = frozenset(_TRANSLATIONS)


class MemoryEventConsumer:
    def __init__(self, manager: MemoryManager, *, name: str = "memory") -> None:
        self._manager = manager
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def handle(self, event: RecordedEvent) -> None:
        fact = event.event

        translate = _TRANSLATIONS.get(fact.event_type)
        if translate is None:
            # O bus filtra por tipo, então isto só ocorre em chamada direta —
            # vale a checagem, não vale um log ruidoso.
            logger.debug("memory.event_ignored", extra=_ignored(fact, "unsubscribed_type"))
            return

        if fact.schema_version != SUPPORTED_SCHEMA_VERSION:
            # contracts §5: versão desconhecida é tratada explicitamente, nunca
            # assumida como a mais recente.
            logger.info("memory.event_ignored", extra=_ignored(fact, "unsupported_schema_version"))
            return

        kwargs = translate(fact)
        # Tempo de domínio, não de processamento — o mesmo papel que
        # `observed_at = event.occurred_at` tem no Context Engine. Sem isto,
        # dois eventos processados no mesmo instante de relógio produziriam
        # memórias com o mesmo `created_at`, e uma contradição entre elas não
        # teria como decidir qual vigência fecha a outra.
        kwargs["created_at"] = fact.occurred_at
        memory_id = deterministic_memory_id(source="event", natural_key=fact.event_id)
        stored = self._manager.remember(memory_id=memory_id, **kwargs)  # type: ignore[arg-type]

        logger.debug(
            "memory.event_applied",
            extra={
                "event_id": fact.event_id,
                "event_type": fact.event_type,
                "correlation_id": fact.correlation_id,
                "causation_id": fact.causation_id,
                "memory_id": stored.memory.memory_id,
            },
        )


def _ignored(event: Event, reason: str) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "reason": reason,
    }
