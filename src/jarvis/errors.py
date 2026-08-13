"""Taxonomia de erros compartilhada pelo Core.

Ver [`docs/architecture-contracts.md §13`](../../docs/architecture-contracts.md#13-error-contract):
toda categoria de erro declara se é `retryable` (transitória) ou permanente, para
que a lógica de retry consulte essa classificação em vez de cada componente
inventar o próprio critério.

Só as categorias com consumidor real existem aqui. `UserFacingError`, prevista no
contrato, segue sem consumidor e por isso sem código.
"""

from typing import ClassVar


class JarvisError(Exception):
    """Raiz de toda exceção levantada deliberadamente pelo Jarvis."""

    retryable: ClassVar[bool] = False


class DomainError(JarvisError):
    """Violação de uma regra de domínio.

    Nunca é retryable: reapresentar a mesma entrada produz exatamente o mesmo erro.
    """


class PolicyDenied(DomainError):
    """Uma execução foi barrada pela fronteira de autorização.

    **Não é uma falha** — é uma negação deliberada
    ([`architecture-contracts.md §13`](../../docs/architecture-contracts.md#13-error-contract)).
    Por isso o caminho normal de negação devolve um `ExecutionOutcome`, não
    levanta: esta exceção é a *guarda* dos caminhos que não podem prosseguir de
    jeito nenhum (aprovação forjada, expirada, já usada, ou uma Tool fora do que
    a Skill declarou precisar).
    """


class InfrastructureError(JarvisError):
    """Falha em um adapter de infraestrutura (banco, filesystem, rede).

    Retryable por padrão: a causa costuma ser transitória (lock, indisponibilidade
    momentânea). Subclasses podem sobrescrever quando souberem que não é.
    """

    retryable: ClassVar[bool] = True


class ProviderError(InfrastructureError):
    """Falha declarada por um provider externo ao Core (LLM, embedding, MCP, API).

    A categoria existe a partir da Fase 4, quando passou a haver mais de um tipo
    de provider: sem ela, lógica de retry teria de enumerar erros de cada
    componente em vez de perguntar "isto é falha de provider e é transitória?".
    """
