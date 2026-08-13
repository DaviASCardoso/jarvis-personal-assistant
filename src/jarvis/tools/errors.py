"""Erros da camada de Tools.

Duas famílias, com tratamento diferente:

- **domínio** — a chamada está errada e continuará errada (`ToolNotFoundError`,
  `ToolInvalidInputError`, `ToolNotPermittedError`);
- **provider** — o backend falhou (`ToolTimeoutError`, `ToolUnavailableError`,
  `ToolExecutionError`, `ToolProtocolError`).

`ToolError` é o marcador comum, herdado **junto** com a categoria do contrato
(`architecture-contracts.md §13`). A herança dupla existe para que
`except ToolError` capture a camada inteira e, ao mesmo tempo, `retryable`
continue vindo da categoria certa sem cada subclasse redeclará-lo: a MRO resolve
`ToolTimeoutError → ToolError → ProviderError → InfrastructureError`, e é de lá
que sai `retryable = True`.

**Nenhuma mensagem aqui pode conter parâmetro, conteúdo de arquivo, resposta de
tool ou valor de variável de ambiente** — elas viram log e evento de auditoria.
Nomeie o campo e a restrição; nunca o valor.
"""

from typing import ClassVar

from jarvis.errors import DomainError, JarvisError, PolicyDenied, ProviderError


class ToolError(JarvisError):
    """Marcador comum de toda falha da camada de Tools."""


class ToolNotFoundError(ToolError, DomainError):
    """O `tool_id` não existe no registry, ou o backend deixou de expô-lo."""


class ToolInvalidInputError(ToolError, DomainError):
    """Os parâmetros não satisfazem o schema anunciado pela Tool."""


class ToolConfigurationError(ToolError, DomainError):
    """A configuração de um backend é inválida.

    Falha alta e cedo: um `mcp.json` malformado que fosse ignorado em silêncio
    viraria "o servidor sumiu" bem depois, longe da causa.
    """


class ToolNotPermittedError(ToolError, PolicyDenied):
    """A Skill pediu uma Tool fora do conjunto que declarou precisar.

    Menor privilégio por execução: o `ToolAccess` recusa antes de o router entrar
    na jogada, mesmo com aprovação válida em mãos.
    """


class ToolExecutionError(ToolError, ProviderError):
    """A Tool foi executada e falhou por conta própria.

    Permanente: o backend respondeu, entendeu o pedido e recusou o resultado.
    Repetir tende a produzir a mesma recusa.
    """

    retryable: ClassVar[bool] = False


class ToolTimeoutError(ToolError, ProviderError):
    """O backend não respondeu dentro do orçamento da chamada.

    Retryable **como erro**; se a execução pode ou não ser repetida é outra
    pergunta, respondida pela `Idempotency` declarada na Skill (ver
    `tools/router.py`): um timeout não prova que a operação não aconteceu.
    """


class ToolUnavailableError(ToolError, ProviderError):
    """O backend não está acessível: processo caído, conexão recusada, handshake
    que não completou."""


class ToolProtocolError(ToolError, ProviderError):
    """O backend respondeu algo que não dá para interpretar.

    Corpo não-JSON, identificador de resposta que não casa com o da requisição,
    envelope sem `result` nem `error`, EOF no meio da leitura. Permanente:
    repetir a mesma chamada tende a produzir o mesmo lixo.
    """

    retryable: ClassVar[bool] = False
