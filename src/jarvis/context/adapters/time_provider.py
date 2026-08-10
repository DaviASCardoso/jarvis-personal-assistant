"""Time Provider: o relógio local como fonte de contexto.

Não lê o relógio por conta própria — recebe `now` do agregador (o único dono do
clock no componente). Isso é o que permite testar a transição `fresh → stale` sem
esperar de verdade, e o que torna `jarvis context show` reproduzível.

O fuso é injetado; `None` significa "o fuso local do sistema". Nenhuma variável de
configuração nova foi criada para isso: o composition root passa o que quiser, e o
default já é o comportamento útil.
"""

from datetime import datetime, tzinfo

from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation


class SystemTimeProvider:
    def __init__(self, *, time_zone: tzinfo | None = None, name: str = "time") -> None:
        self._time_zone = time_zone
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        """`local_time` preserva o offset local; `observed_at` é normalizado para UTC."""
        local = now.astimezone(self._time_zone)
        return ContextUpdate(
            local_time=Observation(
                value=local,
                observed_at=now,
                source=f"provider:{self._name}",
            )
        )
