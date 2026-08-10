"""Time Provider: o fuso local como fonte de contexto.

Observa o **offset em vigor** (ex. `-03:00`), não o instante. O instante já é
`CurrentContext.as_of`: um campo `local_time` seria a mesma informação com outro
fuso, mudaria a cada leitura e tornaria todo snapshot diferente do anterior sem que
nada tivesse acontecido. O offset, ao contrário, é um fato ambiental estável — muda
com viagem ou horário de verão — e combinado com `as_of` reconstrói a hora local.

Não lê o relógio por conta própria: recebe `now` do agregador, o único dono do
clock no componente. É isso que permite testar a transição `fresh → stale` sem
esperar de verdade.
"""

from datetime import datetime, timedelta, tzinfo

from jarvis.context.model import ContextUpdate
from jarvis.context.observation import Observation


def format_utc_offset(offset: timedelta) -> str:
    """`±HH:MM`, a mesma forma que um datetime ISO-8601 usa."""
    total_minutes = round(offset.total_seconds() / 60)
    sign = "-" if total_minutes < 0 else "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


class SystemTimeProvider:
    def __init__(self, *, time_zone: tzinfo | None = None, name: str = "time") -> None:
        self._time_zone = time_zone
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def observe(self, now: datetime) -> ContextUpdate:
        local = now.astimezone(self._time_zone)
        offset = local.utcoffset()
        if offset is None:  # pragma: no cover - astimezone sempre devolve aware
            return ContextUpdate()

        return ContextUpdate(
            utc_offset=Observation(
                value=format_utc_offset(offset),
                observed_at=now,
                source=f"provider:{self._name}",
            )
        )
