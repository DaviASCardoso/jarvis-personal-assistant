"""Identidade de tarefa: sempre aleatória.

Ao contrário de `execution/identity.py`, não há chave natural para derivar
determinismo aqui — uma tarefa em background é sempre uma intenção nova de
quem a submeteu (o composition root), nunca a reapresentação de um evento já
visto. A idempotência de *execução* continua sendo responsabilidade do
`ActionExecutor`, via `decision_id` da `ActionRequest` embutida, se houver.
"""

import uuid


def new_task_id() -> str:
    return str(uuid.uuid4())
