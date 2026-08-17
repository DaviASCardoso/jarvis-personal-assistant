"""`MemoryPresenceBridge` (Fase 9.3) — ponte Proactivity → Memory.

Mesmo espírito de `memory/adapters/context_bridge.py`: um componente
consultando o outro através de um adapter em `adapters/`, nunca via import
direto do Core. Repositório real, em memória — não vale um double aqui: é
exatamente a tradução `subject` → `RetrievalQuery` que este teste prova.
"""

from datetime import UTC, datetime, timedelta

from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE, SqliteMemoryRepository
from jarvis.memory.manager import MemoryManager
from jarvis.memory.memory import MemoryOrigin, MemoryType, Provenance
from jarvis.proactivity.adapters.memory_bridge import MemoryPresenceBridge

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
PROVENANCE = Provenance(origin=MemoryOrigin.USER)


def _manager(repository: SqliteMemoryRepository) -> MemoryManager:
    return MemoryManager(repository=repository, clock=lambda: NOW)


def test_returns_none_for_an_absent_subject() -> None:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        bridge = MemoryPresenceBridge(_manager(repository), clock=lambda: NOW)
        assert bridge.content_for("quiet_hours_preference") is None


def test_returns_the_content_of_an_active_memory() -> None:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        manager = _manager(repository)
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="não notificar depois das 22h",
            provenance=PROVENANCE,
            subject="quiet_hours_preference",
        )
        bridge = MemoryPresenceBridge(manager, clock=lambda: NOW)
        assert bridge.content_for("quiet_hours_preference") == "não notificar depois das 22h"


def test_an_expired_memory_counts_as_absent() -> None:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        manager = _manager(repository)
        manager.remember(
            type=MemoryType.PREFERENCE,
            content="promoção só até ontem",
            provenance=PROVENANCE,
            subject="quiet_hours_preference",
            valid_from=NOW - timedelta(hours=2),
            valid_until=NOW - timedelta(hours=1),
        )
        bridge = MemoryPresenceBridge(manager, clock=lambda: NOW)
        assert bridge.content_for("quiet_hours_preference") is None


def test_a_malformed_subject_is_treated_as_absent_not_a_crash() -> None:
    with SqliteMemoryRepository.open(IN_MEMORY_DATABASE) as repository:
        bridge = MemoryPresenceBridge(_manager(repository), clock=lambda: NOW)
        assert bridge.content_for("Not A Valid Slug!") is None
