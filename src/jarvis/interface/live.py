"""O último snapshot publicado, com revisão monotônica.

É a única estrutura compartilhada entre a thread principal (que fala, lê banco e
monta snapshots) e as threads do servidor HTTP (que só leem)
([ADR-0023](../../../docs/adr/0023-single-resident-process.md)).

A regra de concorrência do processo residente cai daqui: **nenhuma thread além da
principal toca SQLite.** O servidor nunca precisa — ele lê um objeto imutável já
montado. Isso resolve de uma vez o `check_same_thread` do driver e a regra
arquitetural de que a interface não acessa banco, e é bom sinal que as duas
coisas tenham a mesma solução.

`wait_for` existe para o SSE: em vez de girar em `sleep`, o handler dorme até a
próxima revisão ou até o timeout do heartbeat.
"""

import threading

from jarvis.interface.viewmodel import PanelSnapshot


class LiveState:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._snapshot: PanelSnapshot | None = None
        self._revision = 0

    @property
    def revision(self) -> int:
        with self._condition:
            return self._revision

    def publish(self, snapshot: PanelSnapshot) -> int:
        """Publica e acorda quem espera. Devolve a revisão atribuída."""
        with self._condition:
            self._revision += 1
            # A revisão é do `LiveState`, não de quem monta: assim duas fontes
            # (status de voz e snapshot completo) nunca disputam o contador.
            self._snapshot = PanelSnapshot(
                revision=self._revision,
                as_of=snapshot.as_of,
                voice=snapshot.voice,
                timeline=snapshot.timeline,
                context=snapshot.context,
                memories=snapshot.memories,
                decisions=snapshot.decisions,
                actions=snapshot.actions,
                tools=snapshot.tools,
                conversation=snapshot.conversation,
                toasts=snapshot.toasts,
                degraded=snapshot.degraded,
            )
            self._condition.notify_all()
            return self._revision

    def current(self) -> PanelSnapshot | None:
        with self._condition:
            return self._snapshot

    def wait_for(self, *, after: int, timeout: float) -> PanelSnapshot | None:
        """O snapshot seguinte a `after`, ou `None` se o tempo acabar antes."""
        with self._condition:
            if self._revision > after:
                return self._snapshot
            self._condition.wait(timeout=timeout)
            return self._snapshot if self._revision > after else None
