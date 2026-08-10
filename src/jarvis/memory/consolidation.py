"""Deduplicação, contradição e promoção — três regras contáveis, nunca inferência.

`PHASE-3.md §24`: "o Memory System não deve tentar ser inteligente". As três
regras aqui são contagem e comparação de `fingerprint`/`subject`/proveniência —
nada de similaridade semântica ou julgamento.

Deduplicação e contradição são aplicadas **inline**, dentro de
`MemoryManager.remember`, porque só fazem sentido no momento em que existe uma
memória nova para comparar contra as já ativas. Promoção é **explícita**, via
`MemoryManager.consolidate`, porque depende de um padrão agregado — várias
memórias episódicas já existentes — que só um pedido deliberado deveria
disparar (`PHASE-3.md §5`: consolidação nunca é automática).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from jarvis.memory.memory import Memory, MemoryType, StoredMemory

MINIMUM_PROMOTION_OCCURRENCES: Final = 3
MINIMUM_PROMOTION_REFERENCES: Final = 2
MAXIMUM_PROMOTED_CONFIDENCE: Final = 0.95
PROMOTION_CONFIDENCE_STEP: Final = 0.05


def _same_subject(a: Memory, b: Memory) -> bool:
    """Tipo, `subject` e `scope` iguais — a identidade que a contradição usa.

    `scope` entra para que duas tarefas (`TASK`) diferentes que coincidam de
    usar o mesmo `subject` não se confundam uma com a outra.
    """
    return a.type == b.type and a.subject == b.subject and a.scope == b.scope


def find_duplicate(
    candidate: Memory, existing: Sequence[StoredMemory], *, now: datetime
) -> StoredMemory | None:
    """A **mesma origem** (`provenance.reference`) reafirmando o mesmo
    conteúdo — o caso de reprocessar um evento (`PHASE-3.md §16.2`).

    Reference é parte da chave, e não só tipo/`subject`/conteúdo: duas
    ocorrências **genuinamente distintas** do mesmo fato (ex. o padrão que
    justifica uma promoção, §16.4) têm referências diferentes e não devem
    colapsar numa só.
    """
    fingerprint = candidate.fingerprint()
    for item in existing:
        other = item.memory
        if not _same_subject(candidate, other):
            continue
        if other.provenance.reference != candidate.provenance.reference:
            continue
        if other.fingerprint() != fingerprint:
            continue
        if not item.is_active_at(now):
            continue
        return item
    return None


def find_contradiction(
    candidate: Memory, existing: Sequence[StoredMemory], *, now: datetime
) -> StoredMemory | None:
    """Mesmo `subject`, conteúdo **diferente**, ambas ativas — **qualquer**
    origem conta, ao contrário da duplicata: contradizer não exige vir da
    mesma fonte que a memória original.

    `subject is None` nunca contradiz nada: sem chave de contradição, dois
    conteúdos diferentes são só dois fatos independentes, não uma disputa sobre
    o mesmo assunto.
    """
    if candidate.subject is None:
        return None
    fingerprint = candidate.fingerprint()
    for item in existing:
        if not _same_subject(candidate, item.memory):
            continue
        if item.memory.fingerprint() == fingerprint:
            continue
        if not item.is_active_at(now):
            continue
        return item
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionCandidate:
    """Um padrão episódico repetido o suficiente para virar conhecimento
    consolidado."""

    subject: str
    content: str
    contributors: tuple[StoredMemory, ...]
    confidence: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsolidationReport:
    promoted: tuple[StoredMemory, ...]


def find_promotions(
    memories: Sequence[StoredMemory], *, now: datetime
) -> tuple[PromotionCandidate, ...]:
    """Agrupa episódicas ativas por `(subject, fingerprint)`; promove quando há
    ao menos `MINIMUM_PROMOTION_OCCURRENCES` ocorrências vindas de ao menos
    `MINIMUM_PROMOTION_REFERENCES` proveniências distintas.

    Idempotente por construção: se já existir uma `SEMANTIC` ativa com o mesmo
    `(subject, fingerprint)`, o grupo é ignorado — chamar `consolidate()` duas
    vezes não promove a mesma coisa duas vezes. `subject is None` nunca
    promove: não há chave para agrupar.
    """
    episodic_groups: dict[tuple[str, str], list[StoredMemory]] = {}
    already_promoted: set[tuple[str, str]] = set()

    for item in memories:
        memory = item.memory
        if not item.is_active_at(now):
            continue
        if memory.subject is None:
            continue

        key = (memory.subject, memory.fingerprint())
        if memory.type is MemoryType.SEMANTIC:
            already_promoted.add(key)
        elif memory.type is MemoryType.EPISODIC:
            episodic_groups.setdefault(key, []).append(item)

    promotions: list[PromotionCandidate] = []
    for key in sorted(episodic_groups):
        if key in already_promoted:
            continue
        group = episodic_groups[key]
        if len(group) < MINIMUM_PROMOTION_OCCURRENCES:
            continue

        references = {
            item.memory.provenance.reference
            for item in group
            if item.memory.provenance.reference is not None
        }
        if len(references) < MINIMUM_PROMOTION_REFERENCES:
            continue

        subject, _fingerprint = key
        average_confidence = sum(item.confidence for item in group) / len(group)
        confidence = min(
            MAXIMUM_PROMOTED_CONFIDENCE,
            average_confidence + PROMOTION_CONFIDENCE_STEP * (len(group) - 1),
        )
        contributors = tuple(sorted(group, key=lambda item: item.memory.memory_id))
        promotions.append(
            PromotionCandidate(
                subject=subject,
                content=group[0].memory.content,
                contributors=contributors,
                confidence=confidence,
            )
        )
    return tuple(promotions)
