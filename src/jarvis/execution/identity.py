"""Identidade de execução.

`PHASE-5.md §18`: cada execução tem identidade própria, e ela precisa correlacionar
decisão, veredito, aprovação, chamadas de tool, resultado, eventos e auditoria.
`PHASE-5.md §19`: repetir uma execução por retry, timeout, reconexão ou evento
duplicado não pode reexecutar a ação.

As duas exigências se resolvem com o mesmo mecanismo, e é o mesmo que o Event
System já usa para deduplicar evento (`deterministic_event_id`): derivar o
identificador de uma chave natural. Aqui a chave natural é
`(decision_id, skill, parameters_fingerprint)` — a mesma decisão, propondo a
mesma skill com os mesmos parâmetros, é a mesma execução. O repositório recusa
reexecutar o que já rodou, e o evento duplicado vira no-op em vez de segunda
mensagem enviada.

Sem `decision_id` (ação pedida à mão no CLI) o identificador é aleatório: pedir
duas vezes na mão é intenção, não duplicata.
"""

import uuid
from typing import Final

# NUNCA pode mudar: alterá-lo faria a mesma decisão gerar um `execution_id`
# diferente, e a garantia de idempotência de tudo que já foi executado iria
# junto. Mesma regra do namespace de `events/event.py`.
_EXECUTION_ID_NAMESPACE: Final = uuid.UUID("96f21a6c-27b6-53e8-9d50-35b3cbac8651")

# Separador improvável nas partes, para que ("a:b", "c") e ("a", "b:c") não
# colidam.
_SEPARATOR: Final = "\x1f"


def new_execution_id() -> str:
    return str(uuid.uuid4())


def deterministic_execution_id(*, decision_id: str, skill: str, parameters_fingerprint: str) -> str:
    name = _SEPARATOR.join((decision_id, skill, parameters_fingerprint))
    return str(uuid.uuid5(_EXECUTION_ID_NAMESPACE, name))
