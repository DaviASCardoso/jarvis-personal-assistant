"""Ponte Proactivity → Memory: traduz um `subject` de condição numa consulta.

Fica em `adapters/`, não no Core, porque conhece dois componentes ao mesmo
tempo — Proactivity e Memory System — e nenhum dos dois Cores pode saber
disso um do outro (`architecture-contracts.md §3.3`, §3.17; ADR-0032). Mesmo
padrão de `memory/adapters/context_bridge.py` (Fase 3.7), na direção oposta.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from jarvis.memory.errors import InvalidMemoryError
from jarvis.memory.manager import MemoryManager
from jarvis.memory.ports import MemoryCriteria
from jarvis.memory.retrieval import RetrievalQuery

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryPresenceBridge:
    """Implementa `jarvis.proactivity.ports.MemoryPresence` estruturalmente
    (Protocol — sem herança). `active_at=agora` e `limit=1`: a condição só
    precisa saber se existe uma memória vigente, não rankear várias.
    """

    def __init__(self, manager: MemoryManager, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._manager = manager
        self._clock = clock

    def content_for(self, subject: str) -> str | None:
        now = self._clock()
        try:
            criteria = MemoryCriteria(subject=subject, active_at=now, limit=1)
        except InvalidMemoryError:
            # Um `subject` malformado numa regra é engano de configuração, não
            # motivo para derrubar a avaliação da condição — vira ausência,
            # com o aviso indo para o log, não para uma exceção que
            # atravessaria o Trigger Engine.
            logger.warning(
                "proactivity.memory_condition_invalid_subject", extra={"subject": subject}
            )
            return None
        outcome = self._manager.retrieve(RetrievalQuery(criteria=criteria, now=now))
        if not outcome.results:
            return None
        return outcome.results[0].memory.memory.content
