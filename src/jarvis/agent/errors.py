"""Erros do Agent Runtime.

Duas famílias, com origens diferentes e tratamento diferente:

- **Domínio** (`DomainError`) — a requisição ou a resposta violam uma invariante
  nossa. Nunca retryable: reapresentar a mesma entrada produz o mesmo erro.
- **Provider** (`ProviderError`) — o serviço externo falhou. A subclasse declara
  se insistir faz sentido, e é essa declaração que a `LLMRetryPolicy` consulta
  ([`architecture-contracts.md §13`](../../../docs/architecture-contracts.md#13-error-contract)).

Os quatro nomes previstos no
[ADR-0002](../../../docs/adr/0002-llm-provider-abstraction.md)
(`LLMTimeoutError`, `LLMRateLimitError`, `LLMProviderError`,
`LLMInvalidResponseError`) estão todos aqui. `LLMAuthenticationError` é um
acréscimo: sem ele, credencial errada seria indistinguível de indisponibilidade
transitória e o retry insistiria num erro que nunca vai passar.

**Nenhuma mensagem de erro aqui pode conter prompt, resposta do modelo,
credencial ou payload de evento** — elas viram log com stack trace, e o caminho
de erro é o jeito mais fácil de vazar dado pessoal.
"""

from typing import ClassVar

from jarvis.errors import DomainError, ProviderError


class InvalidLLMRequestError(DomainError):
    """Uma `LLMRequest` ou `Message` viola uma invariante do contrato do port."""


class InvalidDecisionError(DomainError):
    """A resposta do modelo não é uma `Decision` válida.

    Distinta de `LLMInvalidResponseError`: aqui houve resposta utilizável, mas o
    conteúdo não satisfaz o schema de decisão. É falha de raciocínio, não de
    infraestrutura.
    """


class PromptTooLargeError(DomainError):
    """O envelope excede o orçamento mesmo depois de todos os cortes previstos.

    Falhar é deliberado: enviar um prompt mutilado em silêncio produziria uma
    decisão pior sem que nada indicasse o porquê.
    """


class LLMProviderError(ProviderError):
    """Falha declarada por um adapter de `LLMProvider`.

    Base de todos os erros de LLM e também o erro concreto das falhas
    transitórias sem subclasse própria: 5xx, conexão recusada, transporte.
    `retryable` continua sendo atributo de **classe**, como no resto da
    taxonomia — quem precisa da distinção ganha uma subclasse, e não uma flag
    por instância que obrigaria cada `except` a inspecionar o objeto.
    """


class LLMRequestRejectedError(LLMProviderError):
    """O provider recusou a requisição (4xx que não é credencial nem quota).

    Permanente: reenviar exatamente o mesmo corpo produz a mesma recusa.
    """

    retryable: ClassVar[bool] = False


class LLMTimeoutError(LLMProviderError):
    """O provider não respondeu dentro de `LLMRequest.timeout_seconds`."""


class LLMRateLimitError(LLMProviderError):
    """Limite de requisições ou quota do provider atingido.

    `retry_after` é o que o provider pediu que esperássemos, quando informa —
    respeitá-lo é mais barato e mais educado que o backoff cego da política.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMAuthenticationError(LLMProviderError):
    """Credencial ausente, inválida ou sem permissão para o modelo pedido."""

    retryable: ClassVar[bool] = False


class LLMInvalidResponseError(LLMProviderError):
    """O provider respondeu algo que não dá para interpretar como `LLMResponse`.

    Corpo não-JSON, sem candidatos, ou texto vazio num encerramento normal.
    Permanente: repetir a mesma chamada tende a produzir o mesmo lixo.
    """

    retryable: ClassVar[bool] = False
