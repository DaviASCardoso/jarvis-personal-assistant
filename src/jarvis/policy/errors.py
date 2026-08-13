"""Erros do Policy Engine.

Todos herdam de `PolicyDenied`, que herda de `DomainError`: uma negação nunca é
retryable, e insistir não muda o veredito.

A distinção que importa: **negar não levanta exceção.** O caminho normal de
`deny` e de `require_confirmation` devolve um `PolicyVerdict`, que o executor
transforma num `ExecutionOutcome` que o agente pode relatar
(`architecture-contracts.md §13`: "`PolicyDenied` não é uma falha — é uma negação
deliberada"). O que está aqui é a **guarda**: os casos em que alguém chegou perto
demais da execução sem ter direito — aprovação desconhecida, expirada, já usada,
ou emitida para outra coisa.
"""

from jarvis.errors import PolicyDenied


class PolicyError(PolicyDenied):
    """Raiz das falhas de autorização."""


class ApprovalError(PolicyError):
    """Uma `PolicyApproval` apresentada não é utilizável."""


class UnknownApprovalError(ApprovalError):
    """A aprovação não consta no ledger do engine que deveria tê-la emitido.

    É o que acontece com uma `PolicyApproval` construída à mão: ela tem todos os
    campos certos e nenhum valor, porque quem valida é o emissor.
    """


class ApprovalExpiredError(ApprovalError):
    """A aprovação venceu antes de ser usada."""


class ApprovalAlreadyUsedError(ApprovalError):
    """A aprovação já foi consumida.

    Uso único: uma autorização é para *uma* execução, não um passe reutilizável
    (`PHASE-5.md §9`).
    """


class ApprovalMismatchError(ApprovalError):
    """A aprovação não corresponde ao que está sendo executado.

    Tipicamente: os parâmetros mudaram depois da autorização, e o
    `parameters_fingerprint` deixou de bater. Autorizar "apagar A" nunca
    autoriza "apagar B".
    """
