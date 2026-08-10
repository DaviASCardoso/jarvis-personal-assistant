"""Ponte Context → Memory: traduz `CurrentContext` numa `RetrievalQuery`.

Fica em `adapters/`, não no Core, porque conhece dois componentes ao mesmo
tempo — Context Engine e Memory System — e nenhum dos dois Cores pode saber
disso um do outro (contracts §3.2, §3.3: nenhum dos dois lista o outro entre
as dependências permitidas).
"""

from jarvis.context.model import ContextField, CurrentContext, iter_fields
from jarvis.context.observation import Freshness
from jarvis.memory.ports import MemoryCriteria
from jarvis.memory.retrieval import RetrievalQuery

# Só os campos de **estado do usuário** viram tag — os exemplos do plano
# (`place:home`, `activity:working`) e o análogo direto, `availability`.
# `device_id`/`utc_offset` são identidade técnica do dispositivo, não algo que
# uma memória algum dia teria como tag; incluí-los tornaria `--from-context`
# vazio na prática, já que `MemoryCriteria.tags` exige **todas** as tags
# presentes (AND) — um campo que nenhuma memória jamais marcaria bastaria para
# zerar qualquer busca.
_TAGGABLE_FIELDS = frozenset({ContextField.PLACE, ContextField.ACTIVITY, ContextField.AVAILABILITY})


def context_to_query(
    context: CurrentContext, *, text: str | None = None, limit: int = 10
) -> RetrievalQuery:
    """Campos de estado do usuário, observados e frescos, viram tags
    `campo:valor` (ex. `place:home`, `activity:working`); ausentes ou vencidos
    (`stale`) são ignorados — o Memory System nunca herda uma suposição velha
    do Context Engine.
    """
    tags: set[str] = set()
    for field, observation in iter_fields(context):
        if field not in _TAGGABLE_FIELDS:
            continue
        if observation is None or observation.value is None:
            continue
        if observation.freshness(context.as_of) is Freshness.STALE:
            continue
        if not isinstance(observation.value, str):
            continue
        tags.add(f"{field.value}:{observation.value}")

    criteria = MemoryCriteria(tags=frozenset(tags)) if tags else MemoryCriteria()
    return RetrievalQuery(text=text, criteria=criteria, limit=limit)
