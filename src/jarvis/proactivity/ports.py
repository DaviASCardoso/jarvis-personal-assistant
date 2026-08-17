"""Port do Proactivity para o único dado de memória que uma condição precisa.

`MemoryPresence` existe para que `jarvis.proactivity` nunca importe
`jarvis.memory` diretamente — mesma disciplina de `architecture-contracts.md`
para os demais componentes. Quem implementa é um bridge adapter no
composition root (`proactivity/adapters/memory_bridge.py`), no mesmo molde de
`memory/adapters/context_bridge.py` (Fase 3.7): um arquivo que conhece dois
componentes ao mesmo tempo mora em `adapters/`, nunca no Core de nenhum dos
dois (Fase 9.3, ver ADR-0032).
"""

from typing import Protocol


class MemoryPresence(Protocol):
    """Leitura, unidirecional, só isto: o conteúdo da memória ativa mais
    relevante para um `subject`, ou `None` se não houver nenhuma — ausente,
    ainda não válida, expirada ou invalidada contam igualmente como ausência.
    """

    def content_for(self, subject: str) -> str | None: ...
