"""Entidade `Event` e seu envelope.

Materializa o contrato de
[`architecture-contracts.md §5`](../../../docs/architecture-contracts.md#5-event-contract)
e [ADR-0004](../../../docs/adr/0004-event-immutability-and-timestamps.md). Dois tipos
distintos, e não um só com campo opcional:

- `Event` é o que um producer cria — não tem, e não pode ter, `recorded_at`;
- `RecordedEvent` é `Event` + `recorded_at`, e só o Event Store o constrói.

Isso torna estruturalmente impossível o producer definir o tempo de persistência,
em vez de depender de disciplina de código.
"""

import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

from jarvis.events.errors import InvalidEventError

type JsonValue = str | int | float | bool | Sequence[JsonValue] | Mapping[str, JsonValue] | None

# Namespace fixo para `deterministic_event_id`. NUNCA pode mudar: alterá-lo faria o
# mesmo acontecimento gerar um `event_id` diferente, quebrando a deduplicação de
# tudo que já foi registrado.
_EVENT_ID_NAMESPACE: Final = uuid.UUID("d3678b04-52c5-549c-bb2b-79fbf3693876")

# Separador improvável em chaves naturais, para que ("a:b", "c") e ("a", "b:c") não
# colidam.
_NATURAL_KEY_SEPARATOR: Final = "\x1f"

_SEGMENT = r"[a-z0-9]+(?:_[a-z0-9]+)*"
_EVENT_TYPE_PATTERN: Final = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT})+$")
_SOURCE_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def new_event_id() -> str:
    """Identificador aleatório, para eventos sem chave natural na origem."""
    return str(uuid.uuid4())


def deterministic_event_id(*, source: str, natural_key: str) -> str:
    """Identificador derivado de uma chave natural da source.

    Reobservar o mesmo acontecimento (ex. o mesmo `Message-ID` de email) produz o
    mesmo `event_id`, o que faz o Event Store tratar a reinserção como no-op —
    a forma preferida de idempotência segundo o contrato §5.
    """
    name = f"{source}{_NATURAL_KEY_SEPARATOR}{natural_key}"
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, name))


def _require_text(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise InvalidEventError(f"{field_name} não pode ser vazio")
    return value


def _require_pattern(value: str, *, field_name: str, pattern: re.Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise InvalidEventError(f"{field_name} inválido: {value!r} não casa com {pattern.pattern}")
    return value


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise InvalidEventError(f"{field_name} precisa ser timezone-aware, recebido {value!r}")
    return value.astimezone(UTC)


def _freeze_json(value: object, *, path: str) -> JsonValue:
    """Congela recursivamente um valor JSON, rejeitando o que não for serializável.

    `dict` vira `MappingProxyType` e `list` vira `tuple`, de modo que o payload de um
    evento já construído não possa ser alterado nem pelo próprio producer.
    """
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise InvalidEventError(f"{path}: {value!r} não é representável em JSON")
        return value
    if isinstance(value, bytes | bytearray):
        raise InvalidEventError(f"{path}: bytes não são um tipo JSON")
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_json_key(key, path=path): _freeze_json(item, path=f"{path}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, Sequence):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)
        )
    raise InvalidEventError(f"{path}: {type(value).__name__} não é um tipo JSON")


def _require_json_key(key: object, *, path: str) -> str:
    if not isinstance(key, str):
        raise InvalidEventError(f"{path}: chave {key!r} não é uma string")
    return key


def _freeze_mapping(value: object, *, field_name: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise InvalidEventError(
            f"{field_name} precisa ser um mapping, recebido {type(value).__name__}"
        )
    frozen = _freeze_json(value, path=field_name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - garantido pelo ramo acima
        raise InvalidEventError(f"{field_name} precisa ser um mapping")
    return frozen


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Um fato: algo que aconteceu, com identidade própria.

    `correlation_id` ausente significa "este é um evento raiz" e passa a valer o
    próprio `event_id` (contrato §5) — depois da construção nunca é `None`.
    """

    event_id: str
    event_type: str
    occurred_at: datetime
    source: str
    payload: Mapping[str, JsonValue]
    schema_version: int = 1
    correlation_id: str | None = None
    causation_id: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        overwrite(self, "event_id", _require_text(self.event_id, field_name="event_id"))
        overwrite(
            self,
            "event_type",
            _require_pattern(self.event_type, field_name="event_type", pattern=_EVENT_TYPE_PATTERN),
        )
        overwrite(
            self,
            "source",
            _require_pattern(self.source, field_name="source", pattern=_SOURCE_PATTERN),
        )
        overwrite(self, "occurred_at", _require_utc(self.occurred_at, field_name="occurred_at"))

        if self.schema_version < 1:
            raise InvalidEventError(
                f"schema_version precisa ser >= 1, recebido {self.schema_version}"
            )

        overwrite(self, "payload", _freeze_mapping(self.payload, field_name="payload"))
        overwrite(self, "metadata", _freeze_mapping(self.metadata, field_name="metadata"))

        if self.correlation_id is None:
            overwrite(self, "correlation_id", self.event_id)
        else:
            overwrite(
                self,
                "correlation_id",
                _require_text(self.correlation_id, field_name="correlation_id"),
            )

        if self.causation_id is not None:
            overwrite(
                self, "causation_id", _require_text(self.causation_id, field_name="causation_id")
            )


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """Um `Event` já persistido, com o tempo de registro atribuído pelo Event Store."""

    event: Event
    recorded_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recorded_at", _require_utc(self.recorded_at, field_name="recorded_at")
        )
