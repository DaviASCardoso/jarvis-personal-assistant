"""Observação contextual: um valor com a sua própria proveniência e validade.

Materializa o contrato de
[`architecture-contracts.md §6`](../../../docs/architecture-contracts.md#6-context-contract):
"cada campo carrega valor, `observed_at`, `source`, `confidence`". O TTL é
carimbado pela projeção (a política é por campo, não por observação) e o estado
`fresh`/`stale` é **derivado** na leitura, nunca armazenado — um valor vencido
continua acessível, só deixa de ser fresco.

`observed_at` é um terceiro tempo, distinto dos dois do Event System: `occurred_at`
diz quando o fato aconteceu, `recorded_at` quando ele foi registrado, e
`observed_at` quando a observação incorporada ao contexto foi feita.
"""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from jarvis.context.errors import InvalidContextError

# Rótulos são fechados o suficiente para não admitirem texto livre: contexto é
# persistido em snapshot, e um campo que aceita frase aceita dado pessoal.
MAX_LABEL_LENGTH: Final = 32
_LABEL_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


def require_label(value: object, *, field_name: str) -> str:
    """Um rótulo curto e fechado (ex. `busy`, `working`, `home`).

    Nenhuma mensagem repete o valor recusado. Ele costuma vir de um payload de
    evento, e uma falha de validação vira log com stack trace no bus — seria a
    forma mais fácil de vazar dado pessoal justamente no caminho de erro.
    """
    if not isinstance(value, str):
        raise InvalidContextError(
            f"{field_name} precisa ser texto, recebido {type(value).__name__}"
        )
    if len(value) > MAX_LABEL_LENGTH:
        raise InvalidContextError(
            f"{field_name} excede {MAX_LABEL_LENGTH} caracteres: {len(value)}"
        )
    if not _LABEL_PATTERN.fullmatch(value):
        raise InvalidContextError(f"{field_name} não casa com {_LABEL_PATTERN.pattern}")
    return value


def require_identifier(value: object, *, field_name: str) -> str:
    """Um identificador opaco de origem (ex. `conversation_id`)."""
    if not isinstance(value, str):
        raise InvalidContextError(
            f"{field_name} precisa ser texto, recebido {type(value).__name__}"
        )
    if not value.strip():
        raise InvalidContextError(f"{field_name} não pode ser vazio")
    return value


def require_aware(value: object, *, field_name: str) -> datetime:
    """Todo datetime do contexto é timezone-aware, como no Event System."""
    if not isinstance(value, datetime):
        raise InvalidContextError(
            f"{field_name} precisa ser um datetime, recebido {type(value).__name__}"
        )
    if value.utcoffset() is None:
        raise InvalidContextError(f"{field_name} precisa ser timezone-aware, recebido {value!r}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation[T]:
    """O que uma fonte afirmou sobre um campo, e quando.

    `value=None` num tipo `T | None` é uma **ausência observada** (alguém afirmou
    que não há valor) — diferente de o campo inteiro ser `None`, que é ausência de
    qualquer observação. O Context Engine nunca infere a segunda a partir da
    primeira nem vice-versa.
    """

    value: T
    observed_at: datetime
    source: str
    confidence: float = 1.0
    ttl: timedelta | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        observed_at = require_aware(self.observed_at, field_name="observed_at")
        overwrite(self, "observed_at", observed_at.astimezone(UTC))

        if not self.source.strip():
            raise InvalidContextError("source não pode ser vazio")

        if math.isnan(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise InvalidContextError(
                f"confidence precisa estar entre 0.0 e 1.0, recebido {self.confidence!r}"
            )

        if self.ttl is not None and self.ttl <= timedelta(0):
            raise InvalidContextError(f"ttl precisa ser positivo, recebido {self.ttl!r}")

    def expires_at(self) -> datetime | None:
        """Quando esta observação deixa de ser fresca; `None` = não expira por tempo."""
        return None if self.ttl is None else self.observed_at + self.ttl

    def freshness(self, now: datetime) -> Freshness:
        expires_at = self.expires_at()
        if expires_at is None or now < expires_at:
            return Freshness.FRESH
        return Freshness.STALE

    def is_stale(self, now: datetime) -> bool:
        return self.freshness(now) is Freshness.STALE
