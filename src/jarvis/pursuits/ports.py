"""Port de persistência de checkpoints do Goal Pursuit Loop (Fase 10.5).

Um método só de transição — `advance` — porque há uma única coisa que
acontece a um `PursuitState` depois de criado: registrar o desfecho do passo
mais recente. Ao contrário de `TaskRepository` (que tem `mark_succeeded`/
`mark_failed`/`schedule_retry` distintos), aqui todo passo muda o mesmo
conjunto de campos junto — `step`, `status`, `last_action_result` e
`previous_proposal` sempre avançam como uma coisa só.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from jarvis.events.event import JsonValue
from jarvis.pursuits.model import PursuitState, PursuitStatus


class PursuitRepository(Protocol):
    def put(self, pursuit: PursuitState) -> None:
        """Grava o checkpoint pela primeira vez. Reescrever um `pursuit_id`
        existente é erro, não upsert."""
        ...

    def get(self, pursuit_id: str) -> PursuitState | None: ...

    def advance(
        self,
        pursuit_id: str,
        *,
        step: int,
        status: PursuitStatus,
        last_action_result: Mapping[str, JsonValue] | None,
        previous_proposal: Mapping[str, JsonValue] | None,
        moment: datetime,
    ) -> PursuitState:
        """Registra o desfecho do passo `step` — a única transição que existe."""
        ...
