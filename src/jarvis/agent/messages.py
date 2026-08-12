"""Vocabulário vendor-agnóstico de conversa com um modelo.

Materializa a decisão 1 do
[ADR-0002](../../../docs/adr/0002-llm-provider-abstraction.md): o Core fala em
mensagens, formato de resposta e parâmetros de geração; nenhum campo aqui existe
porque um vendor específico o tem. A tradução para `contents`/`parts`/
`generationConfig` (ou o equivalente de outro fornecedor) acontece só dentro do
adapter.

O que **não** está aqui, deliberadamente: definição de tools expostas ao modelo.
Não existe Skill Registry até a Fase 5, e um campo de tools sem quem o preencha
seria a abstração especulativa que o contrato §1 proíbe — ver
[ADR-0012](../../../docs/adr/0012-core-owned-structured-decisions.md).
"""

import math
from dataclasses import dataclass, field
from enum import StrEnum

from jarvis.agent.errors import InvalidLLMRequestError

MAX_TEMPERATURE = 2.0


class Role(StrEnum):
    """Quem falou. A instrução de sistema não é um papel: é campo próprio de
    `LLMRequest`, porque não faz parte do diálogo e não pode ser truncada junto
    com ele."""

    USER = "user"
    ASSISTANT = "assistant"


class ResponseFormat(StrEnum):
    TEXT = "text"
    JSON_OBJECT = "json_object"


class StopReason(StrEnum):
    """Por que o modelo parou.

    `BLOCKED` cobre qualquer recusa do provider (filtro de segurança, recitação,
    conteúdo proibido): a distinção entre os motivos é específica de vendor e
    não muda o que o Core faz — não há resposta utilizável em nenhum deles.
    """

    COMPLETE = "complete"
    MAX_TOKENS = "max_tokens"
    BLOCKED = "blocked"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True)
class LLMModel:
    """Identidade do modelo, para log e para distinguir respostas de origens
    diferentes. Não carrega credencial nem endpoint."""

    vendor: str
    name: str

    def __str__(self) -> str:
        return f"{self.vendor}/{self.name}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Message:
    role: Role
    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise InvalidLLMRequestError("content de mensagem não pode ser vazio")


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenUsage:
    """Campos opcionais: nem todo provider informa uso, e inventar zero seria
    indistinguível de "não gastou nada"."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LLMRequest:
    """Tudo que o adapter precisa para fazer uma chamada — e nada além.

    `timeout_seconds` viaja na requisição, e não na configuração do adapter,
    porque o orçamento de tempo é decisão de quem raciocina: uma triagem barata
    e um raciocínio completo não merecem a mesma paciência.
    """

    system: str
    messages: tuple[Message, ...]
    response_format: ResponseFormat = ResponseFormat.TEXT
    temperature: float = 0.2
    max_output_tokens: int = 1024
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.system.strip():
            raise InvalidLLMRequestError("system não pode ser vazio")
        if not self.messages:
            raise InvalidLLMRequestError("messages precisa ter ao menos uma mensagem")
        if self.messages[-1].role is not Role.USER:
            # Pedir geração depois da própria fala do modelo não tem semântica
            # definida em nenhum provider — é bug de montagem, não uma escolha.
            raise InvalidLLMRequestError("a última mensagem precisa ser do usuário")
        if math.isnan(self.temperature) or not 0.0 <= self.temperature <= MAX_TEMPERATURE:
            raise InvalidLLMRequestError(f"temperature precisa estar entre 0.0 e {MAX_TEMPERATURE}")
        if self.max_output_tokens <= 0:
            raise InvalidLLMRequestError("max_output_tokens precisa ser positivo")
        if self.timeout_seconds <= 0:
            raise InvalidLLMRequestError("timeout_seconds precisa ser positivo")


@dataclass(frozen=True, slots=True, kw_only=True)
class LLMResponse:
    text: str
    stop_reason: StopReason
    model: LLMModel
    usage: TokenUsage = field(default_factory=TokenUsage)
