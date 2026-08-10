"""Tradução entre `ContextSnapshot` e sua representação persistida.

Codec **explícito por campo**: cada `ContextField` declara como o seu valor vira
JSON e como volta. Reflexão economizaria linhas e devolveria `Any`; pior, faria um
campo novo atravessar a fronteira sem ninguém decidir o seu formato.

Campo ausente é **omitido** do documento; campo com ausência observada aparece com
`"value": null`. A distinção é o que faz `user.activity_ended` sobreviver ao
round-trip como fato, e não como silêncio.

Nada aqui é específico de SQLite — `StoredSnapshot` descreve um registro plano.
"""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Final, TypedDict

from jarvis.context.errors import ContextSnapshotReadError
from jarvis.context.model import (
    ActivityContext,
    ContextField,
    ConversationContext,
    CurrentContext,
    DeviceContext,
    EnvironmentContext,
    ScheduleContext,
    TaskContext,
    UserContext,
    iter_fields,
)
from jarvis.context.observation import Observation
from jarvis.context.snapshot import ContextSnapshot, context_fingerprint

SNAPSHOT_SCHEMA_VERSION: Final = 1


class StoredSnapshot(TypedDict):
    """Registro plano de um snapshot, na forma em que é persistido."""

    snapshot_id: str
    captured_at: str
    schema_version: int
    fingerprint: str
    document: str


def format_timestamp(value: datetime) -> str:
    """ISO-8601 em UTC, para que a ordem lexicográfica seja a ordem temporal."""
    return value.astimezone(UTC).isoformat()


def parse_timestamp(raw: object, *, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise ContextSnapshotReadError(
            f"{field_name} deveria ser texto, encontrado {type(raw).__name__}"
        )
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise ContextSnapshotReadError(f"{field_name} inválido: {raw!r}") from error


def _encode_text(value: object) -> str:
    return str(value)


def _decode_text(raw: object, *, field: ContextField) -> str:
    if not isinstance(raw, str):
        raise ContextSnapshotReadError(
            f"{field.value}.value deveria ser texto, encontrado {type(raw).__name__}"
        )
    return raw


def _encode_moment(value: object) -> str:
    if not isinstance(value, datetime):  # pragma: no cover - garantido pelo domínio
        raise ContextSnapshotReadError(f"{value!r} não é um datetime")
    return value.isoformat()


def _decode_moment(raw: object, *, field: ContextField) -> datetime:
    return parse_timestamp(raw, field_name=f"{field.value}.value")


# Um par (encode, decode) por campo — a lista completa de formatos, num lugar só.
_TEXT_CODEC: Final = (_encode_text, _decode_text)
_MOMENT_CODEC: Final = (_encode_moment, _decode_moment)

_CODECS: Final[Mapping[ContextField, tuple[Callable[[object], str], Callable[..., object]]]] = {
    ContextField.AVAILABILITY: _TEXT_CODEC,
    ContextField.LOCAL_TIME: _MOMENT_CODEC,
    ContextField.PLACE: _TEXT_CODEC,
    ContextField.DEVICE_ID: _TEXT_CODEC,
    ContextField.ACTIVITY: _TEXT_CODEC,
    ContextField.NEXT_ENTRY_AT: _MOMENT_CODEC,
    ContextField.CONVERSATION: _TEXT_CODEC,
    ContextField.TASK: _TEXT_CODEC,
}


def _encode_observation(field: ContextField, observation: Observation[object]) -> dict[str, object]:
    encode, _ = _CODECS[field]
    return {
        "value": None if observation.value is None else encode(observation.value),
        "observed_at": format_timestamp(observation.observed_at),
        "source": observation.source,
        "confidence": observation.confidence,
        "ttl_seconds": None if observation.ttl is None else observation.ttl.total_seconds(),
    }


def encode_context(context: CurrentContext) -> str:
    """Documento JSON canônico: chaves ordenadas, sem espaços supérfluos."""
    document = {
        "as_of": format_timestamp(context.as_of),
        "fields": {
            field.value: _encode_observation(field, observation)
            for field, observation in iter_fields(context)
            if observation is not None
        },
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _decoded_field(field: ContextField, raw: object) -> Observation[object]:
    if not isinstance(raw, dict):
        raise ContextSnapshotReadError(f"{field.value} deveria ser um objeto JSON")

    _, decode = _CODECS[field]
    value = raw.get("value")
    confidence = raw.get("confidence")
    if not isinstance(confidence, int | float) or isinstance(confidence, bool):
        raise ContextSnapshotReadError(f"{field.value}.confidence deveria ser numérico")

    ttl_seconds = raw.get("ttl_seconds")
    if ttl_seconds is not None and (
        not isinstance(ttl_seconds, int | float) or isinstance(ttl_seconds, bool)
    ):
        raise ContextSnapshotReadError(f"{field.value}.ttl_seconds deveria ser numérico ou nulo")

    source = raw.get("source")
    if not isinstance(source, str):
        raise ContextSnapshotReadError(f"{field.value}.source deveria ser texto")

    return Observation(
        value=None if value is None else decode(value, field=field),
        observed_at=parse_timestamp(
            raw.get("observed_at"), field_name=f"{field.value}.observed_at"
        ),
        source=source,
        confidence=float(confidence),
        ttl=None if ttl_seconds is None else timedelta(seconds=float(ttl_seconds)),
    )


def decode_context(raw: object) -> CurrentContext:
    if not isinstance(raw, str):
        raise ContextSnapshotReadError(
            f"document deveria ser texto, encontrado {type(raw).__name__}"
        )
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ContextSnapshotReadError("document não é JSON válido") from error
    if not isinstance(decoded, dict):
        raise ContextSnapshotReadError("document deveria ser um objeto JSON")

    raw_fields = decoded.get("fields")
    if not isinstance(raw_fields, dict):
        raise ContextSnapshotReadError("document.fields deveria ser um objeto JSON")

    found = {
        field: _decoded_field(field, raw_fields[field.value])
        for field in ContextField
        if field.value in raw_fields
    }

    return CurrentContext(
        as_of=parse_timestamp(decoded.get("as_of"), field_name="as_of"),
        user=UserContext(availability=_as_text(found.get(ContextField.AVAILABILITY))),
        environment=EnvironmentContext(
            local_time=_as_moment(found.get(ContextField.LOCAL_TIME)),
            place=_as_text(found.get(ContextField.PLACE)),
        ),
        device=DeviceContext(device_id=_as_text(found.get(ContextField.DEVICE_ID))),
        activity=ActivityContext(current=_as_optional_text(found.get(ContextField.ACTIVITY))),
        schedule=ScheduleContext(next_entry_at=_as_moment(found.get(ContextField.NEXT_ENTRY_AT))),
        conversation=ConversationContext(active_id=_as_text(found.get(ContextField.CONVERSATION))),
        task=TaskContext(active_id=_as_text(found.get(ContextField.TASK))),
    )


def _as_text(observation: Observation[object] | None) -> Observation[str] | None:
    if observation is None:
        return None
    value = observation.value
    if not isinstance(value, str):
        raise ContextSnapshotReadError("valor de campo textual não pode ser nulo")
    return Observation(
        value=value,
        observed_at=observation.observed_at,
        source=observation.source,
        confidence=observation.confidence,
        ttl=observation.ttl,
    )


def _as_optional_text(observation: Observation[object] | None) -> Observation[str | None] | None:
    if observation is None:
        return None
    value = observation.value
    if value is not None and not isinstance(value, str):  # pragma: no cover - codec já garante
        raise ContextSnapshotReadError("valor de campo textual inválido")
    return Observation(
        value=value,
        observed_at=observation.observed_at,
        source=observation.source,
        confidence=observation.confidence,
        ttl=observation.ttl,
    )


def _as_moment(observation: Observation[object] | None) -> Observation[datetime] | None:
    if observation is None:
        return None
    value = observation.value
    if not isinstance(value, datetime):
        raise ContextSnapshotReadError("valor de campo temporal não pode ser nulo")
    return Observation(
        value=value,
        observed_at=observation.observed_at,
        source=observation.source,
        confidence=observation.confidence,
        ttl=observation.ttl,
    )


def to_record(snapshot: ContextSnapshot) -> StoredSnapshot:
    return StoredSnapshot(
        snapshot_id=snapshot.snapshot_id,
        captured_at=format_timestamp(snapshot.captured_at),
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        fingerprint=context_fingerprint(snapshot.context),
        document=encode_context(snapshot.context),
    )


def from_record(record: Mapping[str, object]) -> ContextSnapshot:
    """Reconstrói a captura; registro corrompido vira erro, nunca snapshot parcial."""
    schema_version = record.get("schema_version")
    if schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ContextSnapshotReadError(
            f"schema_version {schema_version!r} não é suportado "
            f"(esperado {SNAPSHOT_SCHEMA_VERSION})"
        )

    snapshot_id = record.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        raise ContextSnapshotReadError("snapshot_id deveria ser texto")

    return ContextSnapshot(
        snapshot_id=snapshot_id,
        captured_at=parse_timestamp(record.get("captured_at"), field_name="captured_at"),
        context=decode_context(record.get("document")),
    )
