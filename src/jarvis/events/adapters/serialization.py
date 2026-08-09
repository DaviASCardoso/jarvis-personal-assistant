"""Tradução entre o `Event` do domínio e sua representação persistida.

O modelo de domínio e a representação armazenada são coisas separadas
(`PHASE-1.md §16`): o domínio não conhece colunas nem JSON, e o formato gravado é
canônico o suficiente para ser recuperado sem ambiguidade.

Nada aqui é específico de SQLite — `StoredEvent` descreve um registro plano, que
qualquer backend pode materializar como achar melhor.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, TypedDict

from jarvis.events.errors import EventReadError
from jarvis.events.event import Event, JsonValue, RecordedEvent

# Separador de campos no cálculo do fingerprint; não aparece em texto normal.
_FIELD_SEPARATOR: Final = "\x1f"


class StoredEvent(TypedDict):
    """Registro plano de um evento, na forma em que é persistido."""

    event_id: str
    event_type: str
    occurred_at: str
    recorded_at: str
    source: str
    schema_version: int
    correlation_id: str | None
    causation_id: str | None
    payload: str
    metadata: str


def format_timestamp(value: datetime) -> str:
    """ISO-8601 sempre em UTC, para que a ordem lexicográfica seja a ordem temporal."""
    return value.astimezone(UTC).isoformat()


def parse_timestamp(raw: object, *, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise EventReadError(f"{field_name} deveria ser texto, encontrado {type(raw).__name__}")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise EventReadError(f"{field_name} inválido: {raw!r}") from error


def _json_default(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{type(value).__name__} não é serializável em JSON")


def encode_json_object(value: Mapping[str, JsonValue]) -> str:
    """JSON canônico: chaves ordenadas e sem espaços supérfluos.

    A forma canônica é o que torna o fingerprint comparável e o round-trip estável.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def decode_json_object(raw: object, *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(raw, str):
        raise EventReadError(f"{field_name} deveria ser texto, encontrado {type(raw).__name__}")
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise EventReadError(f"{field_name} não é JSON válido") from error
    if not isinstance(decoded, dict):
        raise EventReadError(f"{field_name} deveria ser um objeto JSON")
    return decoded


def event_fingerprint(event: Event) -> str:
    """Resumo do conteúdo de um evento, sem expor o conteúdo em si.

    Usado para detectar que um `event_id` já registrado voltou com corpo diferente —
    ver `SqliteEventStore.append`. Nunca substitui o `event_id` como identidade.
    """
    canonical = _FIELD_SEPARATOR.join(
        (
            event.event_type,
            format_timestamp(event.occurred_at),
            event.source,
            str(event.schema_version),
            event.correlation_id or "",
            event.causation_id or "",
            encode_json_object(event.payload),
            encode_json_object(event.metadata),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def to_record(event: Event, recorded_at: datetime) -> StoredEvent:
    return StoredEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        occurred_at=format_timestamp(event.occurred_at),
        recorded_at=format_timestamp(recorded_at),
        source=event.source,
        schema_version=event.schema_version,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        payload=encode_json_object(event.payload),
        metadata=encode_json_object(event.metadata),
    )


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise EventReadError(f"{key} deveria ser texto, encontrado {type(value).__name__}")
    return value


def _optional_text(record: Mapping[str, object], key: str) -> str | None:
    value = record.get(key)
    if value is None or isinstance(value, str):
        return value
    raise EventReadError(f"{key} deveria ser texto ou nulo, encontrado {type(value).__name__}")


def _integer(record: Mapping[str, object], key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int):
        raise EventReadError(f"{key} deveria ser inteiro, encontrado {type(value).__name__}")
    return value


def from_record(record: Mapping[str, object]) -> RecordedEvent:
    """Reconstrói o evento a partir do registro persistido.

    Um registro corrompido vira `EventReadError` — nunca um `Event` meio preenchido.
    """
    event = Event(
        event_id=_text(record, "event_id"),
        event_type=_text(record, "event_type"),
        occurred_at=parse_timestamp(record.get("occurred_at"), field_name="occurred_at"),
        source=_text(record, "source"),
        payload=decode_json_object(record.get("payload"), field_name="payload"),
        schema_version=_integer(record, "schema_version"),
        correlation_id=_optional_text(record, "correlation_id"),
        causation_id=_optional_text(record, "causation_id"),
        metadata=decode_json_object(record.get("metadata"), field_name="metadata"),
    )
    return RecordedEvent(
        event=event,
        recorded_at=parse_timestamp(record.get("recorded_at"), field_name="recorded_at"),
    )
