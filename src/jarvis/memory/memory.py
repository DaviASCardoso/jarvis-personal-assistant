"""O domínio de memória: a afirmação imutável e o seu ciclo de vida.

Dois tipos, como `Event`/`RecordedEvent` na Fase 1:

- **`Memory`** é o que um produtor afirma — conteúdo, tipo, proveniência,
  validade, importância. **Imutável** depois de construída, e sem estado de
  ciclo de vida.
- **`StoredMemory`** é `Memory` + o estado mutável que só o repositório atribui
  (`recorded_at`, `confidence` corrente, acesso, reforço, supersessão,
  invalidação).

Não existe `update(memory)` genérico: `PHASE-3.md §7` proíbe explicitamente
`UPDATE memory SET content = ...` sem semântica definida, e a ausência de um
método genérico torna essa proibição estrutural, não uma convenção de código.
Correção e contradição criam uma memória **nova**, que supersede a anterior — a
anterior nunca é reescrita (ver `memory/consolidation.py`).
"""

import hashlib
import math
import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from jarvis.memory.embedding import MemoryEmbedding, require_aware
from jarvis.memory.errors import InvalidMemoryError

# Namespace fixo para `deterministic_memory_id`. NUNCA pode mudar: alterá-lo faria
# a mesma origem gerar um `memory_id` diferente, quebrando a idempotência do
# consumer de eventos (`memory/adapters/event_consumer.py`).
_MEMORY_ID_NAMESPACE: Final = uuid.UUID("610e3d21-3b19-45b1-acbe-32e22a04dc46")

_NATURAL_KEY_SEPARATOR: Final = "\x1f"

MAX_SUBJECT_LENGTH: Final = 64
_SLUG_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"
    WORKING = "working"
    TASK = "task"


class MemoryOrigin(StrEnum):
    USER = "user"
    EVENT = "event"
    AGENT = "agent"
    SYSTEM = "system"
    IMPORTED = "imported"


def new_memory_id() -> str:
    """Identificador aleatório, para memórias sem chave natural na origem."""
    return str(uuid.uuid4())


def deterministic_memory_id(*, source: str, natural_key: str) -> str:
    """Identificador derivado de uma chave natural (ex. `event_id`).

    Reobservar a mesma origem produz o mesmo `memory_id` — é o que torna o
    consumer de eventos idempotente sem estado auxiliar: reentregar o mesmo
    evento tenta criar "a mesma" memória, e a deduplicação por fingerprint
    (`memory/consolidation.py`) a converte em reforço, não em linha nova.
    """
    name = f"{source}{_NATURAL_KEY_SEPARATOR}{natural_key}"
    return str(uuid.uuid5(_MEMORY_ID_NAMESPACE, name))


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise InvalidMemoryError(f"{field_name} precisa ser texto, recebido {type(value).__name__}")
    return value


def require_identifier(value: object, *, field_name: str) -> str:
    """Um identificador opaco (ex. `scope`, `superseded_by`) — texto não vazio."""
    text = _require_text(value, field_name=field_name)
    if not text.strip():
        raise InvalidMemoryError(f"{field_name} não pode ser vazio")
    return text


def require_slug(value: object, *, field_name: str, max_length: int = MAX_SUBJECT_LENGTH) -> str:
    """Um identificador curto e fechado, usado como chave de contradição."""
    text = _require_text(value, field_name=field_name)
    if len(text) > max_length:
        raise InvalidMemoryError(f"{field_name} excede {max_length} caracteres: {len(text)}")
    if not _SLUG_PATTERN.fullmatch(text):
        raise InvalidMemoryError(f"{field_name} não casa com {_SLUG_PATTERN.pattern}")
    return text


def require_unit_interval(value: object, *, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidMemoryError(
            f"{field_name} precisa ser numérico, recebido {type(value).__name__}"
        )
    number = float(value)
    if math.isnan(number) or not 0.0 <= number <= 1.0:
        raise InvalidMemoryError(f"{field_name} precisa estar entre 0.0 e 1.0, recebido {number!r}")
    return number


def _normalize_tags(values: object, *, field_name: str) -> tuple[str, ...]:
    """Aceita qualquer sequência de strings; devolve uma tupla ordenada e sem
    duplicatas — ordem não carrega significado aqui, e a normalização torna
    `Memory` comparável e o fingerprint estável."""
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise InvalidMemoryError(f"{field_name} precisa ser uma sequência de strings")
    cleaned: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise InvalidMemoryError(f"{field_name} contém um valor vazio ou não textual")
        cleaned.add(item)
    return tuple(sorted(cleaned))


def normalize_content(text: str) -> str:
    """Minúsculas, sem acento, espaços colapsados — a base do fingerprint."""
    folded = unicodedata.normalize("NFKD", text.strip().lower())
    without_accents = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents)


def content_fingerprint(content: str) -> str:
    """Resumo do conteúdo normalizado — usado para deduplicação, nunca para log."""
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """De onde a informação veio — o suficiente para responder "de onde isto
    veio?" sem inventar uma estrutura sem consumidor nesta fase."""

    origin: MemoryOrigin
    reference: str | None = None

    def __post_init__(self) -> None:
        if self.reference is not None:
            object.__setattr__(
                self,
                "reference",
                require_identifier(self.reference, field_name="provenance.reference"),
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class Memory:
    """A afirmação. Imutável: nenhum campo muda depois da construção."""

    memory_id: str
    type: MemoryType
    content: str
    provenance: Provenance
    created_at: datetime
    importance: float = 0.5
    confidence: float = 0.8
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    subject: str | None = None
    scope: str | None = None
    entities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()
    embedding: MemoryEmbedding | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        overwrite(self, "memory_id", require_identifier(self.memory_id, field_name="memory_id"))

        content = _require_text(self.content, field_name="content")
        if not content.strip():
            raise InvalidMemoryError("content não pode ser vazio")
        overwrite(self, "content", content)

        overwrite(
            self, "importance", require_unit_interval(self.importance, field_name="importance")
        )
        overwrite(
            self, "confidence", require_unit_interval(self.confidence, field_name="confidence")
        )

        created_at = require_aware(self.created_at, field_name="created_at")
        overwrite(self, "created_at", created_at.astimezone(UTC))

        valid_from = self.valid_from if self.valid_from is not None else self.created_at
        valid_from = require_aware(valid_from, field_name="valid_from").astimezone(UTC)
        overwrite(self, "valid_from", valid_from)

        if self.valid_until is not None:
            valid_until = require_aware(self.valid_until, field_name="valid_until").astimezone(UTC)
            if valid_until <= valid_from:
                raise InvalidMemoryError("valid_until precisa ser posterior a valid_from")
            overwrite(self, "valid_until", valid_until)

        if self.subject is not None:
            overwrite(self, "subject", require_slug(self.subject, field_name="subject"))

        if self.scope is not None:
            overwrite(self, "scope", require_identifier(self.scope, field_name="scope"))

        overwrite(self, "entities", _normalize_tags(self.entities, field_name="entities"))
        overwrite(self, "tags", _normalize_tags(self.tags, field_name="tags"))
        overwrite(
            self,
            "derived_from",
            tuple(
                sorted(
                    {
                        require_identifier(item, field_name="derived_from")
                        for item in self.derived_from
                    }
                )
            ),
        )

        if self.provenance.origin is MemoryOrigin.AGENT and self.confidence >= 1.0:
            raise InvalidMemoryError("uma inferência do agente não pode alegar confidence == 1.0")
        if self.type is MemoryType.WORKING and self.valid_until is None:
            raise InvalidMemoryError("working memory precisa de valid_until")
        if self.type is MemoryType.TASK and self.scope is None:
            raise InvalidMemoryError("task memory precisa de scope")
        if self.type is MemoryType.PREFERENCE and self.subject is None:
            raise InvalidMemoryError("preference memory precisa de subject")

    def fingerprint(self) -> str:
        return content_fingerprint(self.content)

    def is_valid_at(self, moment: datetime) -> bool:
        """Intervalo semiaberto `[valid_from, valid_until)`.

        `valid_from` é sempre preenchido no `__post_init__` (default:
        `created_at`); a assinatura permanece `datetime | None` só para aceitar
        `None` como "usa o default" na construção.
        """
        assert self.valid_from is not None
        if moment < self.valid_from:
            return False
        return self.valid_until is None or moment < self.valid_until


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredMemory:
    """`Memory` + o estado de ciclo de vida, atribuído apenas pelo repositório.

    `confidence` aparece nos dois tipos de propósito: em `Memory` é o valor
    **inicial** afirmado (parte da evidência histórica, imutável); aqui é o
    valor **corrente** (reforço o altera). `importance` não se repete porque
    não muda depois da criação.
    """

    memory: Memory
    recorded_at: datetime
    updated_at: datetime
    confidence: float
    last_accessed_at: datetime | None = None
    access_count: int = 0
    reinforced_count: int = 0
    superseded_by: str | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        recorded_at = require_aware(self.recorded_at, field_name="recorded_at")
        overwrite(self, "recorded_at", recorded_at.astimezone(UTC))

        updated_at = require_aware(self.updated_at, field_name="updated_at")
        overwrite(self, "updated_at", updated_at.astimezone(UTC))

        overwrite(
            self, "confidence", require_unit_interval(self.confidence, field_name="confidence")
        )

        if self.last_accessed_at is not None:
            last_accessed_at = require_aware(self.last_accessed_at, field_name="last_accessed_at")
            overwrite(self, "last_accessed_at", last_accessed_at.astimezone(UTC))

        if self.access_count < 0:
            raise InvalidMemoryError(
                f"access_count não pode ser negativo, recebido {self.access_count}"
            )
        if self.reinforced_count < 0:
            raise InvalidMemoryError(
                f"reinforced_count não pode ser negativo, recebido {self.reinforced_count}"
            )

        if self.superseded_by is not None:
            overwrite(
                self,
                "superseded_by",
                require_identifier(self.superseded_by, field_name="superseded_by"),
            )

        if self.invalidated_at is not None:
            invalidated_at = require_aware(self.invalidated_at, field_name="invalidated_at")
            overwrite(self, "invalidated_at", invalidated_at.astimezone(UTC))

        if self.invalidation_reason is not None:
            overwrite(
                self,
                "invalidation_reason",
                require_identifier(self.invalidation_reason, field_name="invalidation_reason"),
            )

    def is_active_at(self, moment: datetime) -> bool:
        """Vigente = válida por tempo, não invalidada e não superada."""
        if self.invalidated_at is not None:
            return False
        if self.superseded_by is not None:
            return False
        return self.memory.is_valid_at(moment)
