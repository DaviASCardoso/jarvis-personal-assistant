"""`ContextSnapshot`: o que o sistema acreditava saber num instante do passado.

Serve à pergunta que só um registro datado responde: "o que o agente sabia quando
decidiu X?". Por isso preserva os metadados de cada campo — `source`,
`observed_at`, `confidence` e `ttl` —, e não só os valores.

`stale` **não** é gravado: é derivável de `observed_at + ttl` contra `captured_at`,
então um snapshot lido hoje reproduz exatamente a validade que valia na captura,
sem duplicar estado que poderia divergir.

O fingerprint deliberadamente ignora `as_of`: ele muda a cada leitura, e incluí-lo
faria toda captura parecer nova, esvaziando a regra de relevância do
`ContextEngine`.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from jarvis.context.errors import InvalidContextError
from jarvis.context.model import CurrentContext, iter_fields
from jarvis.context.observation import require_aware

# Separadores improváveis em texto normal, para que campos distintos não colidam
# ao serem concatenados.
_UNIT: Final = "\x1f"
_RECORD: Final = "\x1e"


def new_snapshot_id() -> str:
    return str(uuid.uuid4())


def _render(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def context_fingerprint(context: CurrentContext) -> str:
    """Resumo do conteúdo observado, sem expor o conteúdo em si."""
    records = []
    for field, observation in iter_fields(context):
        if observation is None:
            records.append(field.value)
            continue
        records.append(
            _UNIT.join(
                (
                    field.value,
                    _render(observation.value),
                    observation.observed_at.isoformat(),
                    observation.source,
                    repr(observation.confidence),
                    "" if observation.ttl is None else repr(observation.ttl.total_seconds()),
                )
            )
        )
    return hashlib.sha256(_RECORD.join(records).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSnapshot:
    """Captura imutável e datada da projeção.

    Sem `reason`: existe um único gatilho de captura nesta fase (pedido explícito
    do composition root). Sem `correlation_id`/`causation_id`: não há fluxo causal
    que dispare captura antes do Agent Runtime, e campo sem produtor é campo morto.
    """

    snapshot_id: str
    captured_at: datetime
    context: CurrentContext

    def __post_init__(self) -> None:
        overwrite = object.__setattr__

        if not self.snapshot_id.strip():
            raise InvalidContextError("snapshot_id não pode ser vazio")

        captured_at = require_aware(self.captured_at, field_name="captured_at")
        overwrite(self, "captured_at", captured_at.astimezone(UTC))

    def fingerprint(self) -> str:
        return context_fingerprint(self.context)
