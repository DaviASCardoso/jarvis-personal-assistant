"""Checkpoint/resume do Goal Pursuit Loop (Fase 10.5): onde um `agent pursue`
parou, para retomar sem re-perguntar ao usuário.

API pública do componente. Não depende de `jarvis.agent`: `PursuitState`
guarda `last_action_result`/`previous_proposal` como documentos JSON soltos,
não tipados — só `cli._agent_pursue` sabe a forma exata deles.
"""

from jarvis.pursuits.errors import (
    PursuitError,
    PursuitReadError,
    PursuitRepositoryError,
    PursuitWriteError,
    UnknownPursuitError,
)
from jarvis.pursuits.identity import new_pursuit_id
from jarvis.pursuits.model import PursuitState, PursuitStatus
from jarvis.pursuits.ports import PursuitRepository

__all__ = [
    "PursuitError",
    "PursuitReadError",
    "PursuitRepository",
    "PursuitRepositoryError",
    "PursuitState",
    "PursuitStatus",
    "PursuitWriteError",
    "UnknownPursuitError",
    "new_pursuit_id",
]
