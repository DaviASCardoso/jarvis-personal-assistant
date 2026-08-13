"""Erros da camada de execução.

A regra que organiza a taxonomia: **um desfecho previsto não é uma exceção.**
Negação, confirmação pendente, expiração e duplicata voltam como
`ExecutionOutcome`, porque o agente precisa poder relatá-los ao usuário e a
auditoria precisa registrá-los. O que está aqui é o que não tem desfecho: entrada
que nem chega a formar um pedido, e falha de persistência.
"""

from jarvis.errors import DomainError, InfrastructureError


class ExecutionError(DomainError):
    """Raiz das falhas de domínio da camada de execução."""


class InvalidActionRequestError(ExecutionError):
    """O pedido de execução é malformado antes mesmo de virar uma execução."""


class InvalidActionEventError(ExecutionError):
    """Um evento de confirmação não tem a forma esperada.

    Vira dead-letter no bus, sem desfazer o evento já gravado — e sem repetir o
    payload na mensagem.
    """


class ActionRepositoryError(InfrastructureError):
    """Falha na persistência de ações."""


class ActionWriteError(ActionRepositoryError):
    """Falha ao gravar ou atualizar uma ação."""


class ActionReadError(ActionRepositoryError):
    """Falha ao ler ou decodificar uma ação."""


class UnknownExecutionError(ExecutionError):
    """Nenhuma ação registrada com esse `execution_id`."""
