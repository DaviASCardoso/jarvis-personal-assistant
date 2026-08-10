"""Tradução entre `StoredMemory` e sua representação persistida.

O modelo de domínio e a representação armazenada são coisas separadas, como nos
dois adapters SQLite anteriores: o domínio não conhece coluna nem JSON, e o
formato gravado é canônico o suficiente para ser recuperado sem ambiguidade.

O vetor de embedding é serializado como `float32` little-endian — formato
compacto e de tamanho previsível (`4 * dimensions` bytes), validado na leitura
antes de ser decodificado.
"""

import json
import sys
from array import array
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final, TypedDict

from jarvis.memory.embedding import EmbeddingModel, MemoryEmbedding
from jarvis.memory.errors import MemoryReadError
from jarvis.memory.memory import Memory, MemoryOrigin, MemoryType, Provenance, StoredMemory

SCHEMA_VERSION: Final = 1


class StoredMemoryRecord(TypedDict):
    """Registro plano de uma memória, na forma em que é persistido."""

    memory_id: str
    type: str
    content: str
    content_fingerprint: str
    subject: str | None
    scope: str | None
    origin: str
    provenance_reference: str | None
    created_at: str
    recorded_at: str
    valid_from: str
    valid_until: str | None
    importance: float
    initial_confidence: float
    confidence: float
    entities: str
    tags: str
    derived_from: str
    embedding: bytes | None
    embedding_provider: str | None
    embedding_model: str | None
    embedding_dimensions: int | None
    embedding_created_at: str | None
    updated_at: str
    last_accessed_at: str | None
    access_count: int
    reinforced_count: int
    superseded_by: str | None
    invalidated_at: str | None
    invalidation_reason: str | None


def format_timestamp(value: datetime) -> str:
    """ISO-8601 sempre em UTC, para que a ordem lexicográfica seja a ordem temporal."""
    return value.astimezone(UTC).isoformat()


def parse_timestamp(raw: object, *, field_name: str) -> datetime:
    if not isinstance(raw, str):
        raise MemoryReadError(f"{field_name} deveria ser texto, encontrado {type(raw).__name__}")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise MemoryReadError(f"{field_name} inválido: {raw!r}") from error


def _optional_timestamp(raw: object, *, field_name: str) -> datetime | None:
    return None if raw is None else parse_timestamp(raw, field_name=field_name)


def encode_tags(values: Sequence[str]) -> str:
    """JSON canônico de um array já ordenado — `Memory` garante a ordenação."""
    return json.dumps(list(values), separators=(",", ":"), ensure_ascii=False)


def decode_tags(raw: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw, str):
        raise MemoryReadError(f"{field_name} deveria ser texto, encontrado {type(raw).__name__}")
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MemoryReadError(f"{field_name} não é JSON válido") from error
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise MemoryReadError(f"{field_name} deveria ser um array JSON de strings")
    return tuple(decoded)


def encode_vector(vector: Sequence[float]) -> bytes:
    """`float32` little-endian — compacto e com tamanho previsível na leitura."""
    values = array("f", vector)
    if sys.byteorder == "big":
        values.byteswap()
    return values.tobytes()


def decode_vector(blob: bytes, *, dimensions: int, field_name: str) -> tuple[float, ...]:
    expected_bytes = dimensions * 4
    if len(blob) != expected_bytes:
        raise MemoryReadError(
            f"{field_name} tem {len(blob)} bytes, esperado {expected_bytes} "
            f"para {dimensions} dimensões"
        )
    values = array("f")
    values.frombytes(blob)
    if sys.byteorder == "big":
        values.byteswap()
    return tuple(values)


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise MemoryReadError(f"{key} deveria ser texto, encontrado {type(value).__name__}")
    return value


def _optional_text(record: Mapping[str, object], key: str) -> str | None:
    value = record.get(key)
    if value is None or isinstance(value, str):
        return value
    raise MemoryReadError(f"{key} deveria ser texto ou nulo, encontrado {type(value).__name__}")


def _number(record: Mapping[str, object], key: str) -> float:
    value = record.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise MemoryReadError(f"{key} deveria ser numérico, encontrado {type(value).__name__}")
    return float(value)


def _integer(record: Mapping[str, object], key: str) -> int:
    value = record.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MemoryReadError(f"{key} deveria ser inteiro, encontrado {type(value).__name__}")
    return value


def _memory_type(record: Mapping[str, object]) -> MemoryType:
    raw = _text(record, "type")
    try:
        return MemoryType(raw)
    except ValueError as error:
        raise MemoryReadError(f"type desconhecido: {raw!r}") from error


def _memory_origin(record: Mapping[str, object]) -> MemoryOrigin:
    raw = _text(record, "origin")
    try:
        return MemoryOrigin(raw)
    except ValueError as error:
        raise MemoryReadError(f"origin desconhecido: {raw!r}") from error


def _embedding_from(record: Mapping[str, object]) -> MemoryEmbedding | None:
    blob = record.get("embedding")
    if blob is None:
        return None
    if not isinstance(blob, bytes):
        raise MemoryReadError(f"embedding deveria ser bytes, encontrado {type(blob).__name__}")

    dimensions = _integer(record, "embedding_dimensions")
    model = EmbeddingModel(
        provider=_text(record, "embedding_provider"),
        model=_text(record, "embedding_model"),
        dimensions=dimensions,
    )
    vector = decode_vector(blob, dimensions=dimensions, field_name="embedding")
    created_at = parse_timestamp(
        record.get("embedding_created_at"), field_name="embedding_created_at"
    )
    return MemoryEmbedding(vector=vector, model=model, created_at=created_at)


def to_record(stored: StoredMemory) -> StoredMemoryRecord:
    memory = stored.memory
    embedding = memory.embedding
    return StoredMemoryRecord(
        memory_id=memory.memory_id,
        type=memory.type.value,
        content=memory.content,
        content_fingerprint=memory.fingerprint(),
        subject=memory.subject,
        scope=memory.scope,
        origin=memory.provenance.origin.value,
        provenance_reference=memory.provenance.reference,
        created_at=format_timestamp(memory.created_at),
        recorded_at=format_timestamp(stored.recorded_at),
        valid_from=format_timestamp(memory.valid_from) if memory.valid_from else "",
        valid_until=format_timestamp(memory.valid_until) if memory.valid_until else None,
        importance=memory.importance,
        initial_confidence=memory.confidence,
        confidence=stored.confidence,
        entities=encode_tags(memory.entities),
        tags=encode_tags(memory.tags),
        derived_from=encode_tags(memory.derived_from),
        embedding=encode_vector(embedding.vector) if embedding else None,
        embedding_provider=embedding.model.provider if embedding else None,
        embedding_model=embedding.model.model if embedding else None,
        embedding_dimensions=embedding.model.dimensions if embedding else None,
        embedding_created_at=format_timestamp(embedding.created_at) if embedding else None,
        updated_at=format_timestamp(stored.updated_at),
        last_accessed_at=(
            format_timestamp(stored.last_accessed_at) if stored.last_accessed_at else None
        ),
        access_count=stored.access_count,
        reinforced_count=stored.reinforced_count,
        superseded_by=stored.superseded_by,
        invalidated_at=format_timestamp(stored.invalidated_at) if stored.invalidated_at else None,
        invalidation_reason=stored.invalidation_reason,
    )


def from_record(record: Mapping[str, object]) -> StoredMemory:
    """Reconstrói a memória a partir do registro persistido.

    Um registro corrompido vira `MemoryReadError` — nunca uma `StoredMemory` meio
    preenchida.
    """
    memory = Memory(
        memory_id=_text(record, "memory_id"),
        type=_memory_type(record),
        content=_text(record, "content"),
        provenance=Provenance(
            origin=_memory_origin(record),
            reference=_optional_text(record, "provenance_reference"),
        ),
        created_at=parse_timestamp(record.get("created_at"), field_name="created_at"),
        importance=_number(record, "importance"),
        confidence=_number(record, "initial_confidence"),
        valid_from=parse_timestamp(record.get("valid_from"), field_name="valid_from"),
        valid_until=_optional_timestamp(record.get("valid_until"), field_name="valid_until"),
        subject=_optional_text(record, "subject"),
        scope=_optional_text(record, "scope"),
        entities=decode_tags(record.get("entities"), field_name="entities"),
        tags=decode_tags(record.get("tags"), field_name="tags"),
        derived_from=decode_tags(record.get("derived_from"), field_name="derived_from"),
        embedding=_embedding_from(record),
    )
    return StoredMemory(
        memory=memory,
        recorded_at=parse_timestamp(record.get("recorded_at"), field_name="recorded_at"),
        updated_at=parse_timestamp(record.get("updated_at"), field_name="updated_at"),
        confidence=_number(record, "confidence"),
        last_accessed_at=_optional_timestamp(
            record.get("last_accessed_at"), field_name="last_accessed_at"
        ),
        access_count=_integer(record, "access_count"),
        reinforced_count=_integer(record, "reinforced_count"),
        superseded_by=_optional_text(record, "superseded_by"),
        invalidated_at=_optional_timestamp(
            record.get("invalidated_at"), field_name="invalidated_at"
        ),
        invalidation_reason=_optional_text(record, "invalidation_reason"),
    )
