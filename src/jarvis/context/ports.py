"""Ports do Context Engine.

`ContextProvider` é port porque há várias fontes independentes e o agregador não
pode conhecer implementações concretas
([contracts §3.2](../../../docs/architecture-contracts.md#32-context-engine)).
`ContextSnapshotRepository` é port porque
[contracts §11](../../../docs/architecture-contracts.md#11-persistence-boundary)
o nomeia explicitamente e proíbe o domínio de conhecer a tecnologia de
persistência.

O agregador, a projeção, o consumer e o engine **não** são ports: cada um tem uma
implementação única e nenhum substituto real, e um `Protocol` para eles seria a
abstração especulativa que o contrato §1 proíbe — mesma assimetria de `EventBus`
vs. `EventStore` na Fase 1.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from jarvis.context.model import ContextUpdate
from jarvis.context.snapshot import ContextSnapshot


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


class ContextSnapshotRepository(Protocol):
    """Registro durável e consultável de capturas de contexto.

    Expiração é **lógica**: `expire_before` marca, não apaga. Um snapshot é
    evidência de o que o sistema sabia, e apagá-lo destruiria a resposta da
    pergunta que ele existe para responder — por isso o registro continua legível
    com `include_expired=True`, mesmo depois de expirado.

    Toda leitura devolve em ordem de captura ascendente.
    """

    def save(self, snapshot: ContextSnapshot) -> None: ...

    def latest(self) -> ContextSnapshot | None:
        """A captura vigente mais recente, ou `None` se não houver nenhuma."""
        ...

    def read_captured_between(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]:
        """Capturas com `captured_at` no intervalo semiaberto `[start, end)`."""
        ...

    def expire_before(self, cutoff: datetime) -> int:
        """Marca como expiradas as capturas anteriores a `cutoff`; devolve quantas."""
        ...
