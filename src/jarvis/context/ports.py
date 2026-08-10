"""Ports do Context Engine.

`ContextProvider` é port porque há várias fontes independentes e o agregador não
pode conhecer implementações concretas
([contracts §3.2](../../../docs/architecture-contracts.md#32-context-engine)).

O agregador, a projeção, o consumer e o engine **não** são ports: cada um tem uma
implementação única e nenhum substituto real, e um `Protocol` para eles seria a
abstração especulativa que o contrato §1 proíbe — mesma assimetria de `EventBus`
vs. `EventStore` na Fase 1.
"""

from datetime import datetime
from typing import Protocol

from jarvis.context.model import ContextUpdate


class ContextProvider(Protocol):
    """Fonte de observações contextuais.

    `now` é **injetado**: um provider que lesse o relógio por conta própria
    tornaria impossível testar a transição `fresh → stale` sem esperar de verdade.
    O provider ainda decide o `observed_at` de cada observação, que pode ser
    anterior a `now`.

    Ausência de dado é um `ContextUpdate` vazio. Falha é `ContextProviderError` —
    o adapter traduz a exceção nativa e nunca a deixa vazar.
    """

    @property
    def name(self) -> str: ...

    def observe(self, now: datetime) -> ContextUpdate: ...
