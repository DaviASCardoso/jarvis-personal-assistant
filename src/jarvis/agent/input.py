"""As duas entradas do Agent Runtime, e o resumo de evento que vai no envelope.

Dois caminhos com regras diferentes:

- **`UserMessage`** — alguém falou com o agente. Sempre vale raciocinar: falar
  com o Jarvis é, por definição, relevante. Nunca passa pelo Importance Engine.
- **`EventTrigger`** — algo aconteceu no mundo. Passa pela triagem determinística
  antes de virar chamada ao LLM (`PHASE-4.md §14`), porque a maioria dos
  acontecimentos não merece resposta e silêncio é decisão válida.

`Event` é dependência legítima daqui: contracts §3.4 lista `Event` entre as
dependências permitidas do Agent Runtime. O que não é permitido — e não existe —
é depender do `EventStore`: quem lê o store é o composition root, que entrega o
dado pronto (ver `EventSummary`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jarvis.agent.errors import InvalidLLMRequestError
from jarvis.events.event import JsonValue, RecordedEvent

MAX_RETRIEVAL_TEXT_LENGTH = 400


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    if value.utcoffset() is None:
        raise InvalidLLMRequestError(f"{field_name} precisa ser timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class UserMessage:
    text: str
    at: datetime
    conversation_id: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidLLMRequestError("text não pode ser vazio")
        if not self.conversation_id.strip():
            raise InvalidLLMRequestError("conversation_id não pode ser vazio")
        object.__setattr__(self, "at", _require_aware(self.at, field_name="at"))

    @property
    def correlation_id(self) -> str:
        """A conversa inteira é uma cadeia causal só."""
        return self.conversation_id

    @property
    def occurred_at(self) -> datetime:
        return self.at

    def retrieval_text(self) -> str:
        return self.text[:MAX_RETRIEVAL_TEXT_LENGTH]


@dataclass(frozen=True, slots=True, kw_only=True)
class EventSummary:
    """Um evento recente, **sem payload**.

    A omissão é deliberada: o envelope vai para um serviço de nuvem, e mandar o
    conteúdo de N eventos "por contexto" é vazamento gratuito. O payload que
    importa — o do gatilho — vai inteiro, porque é o objeto do raciocínio.
    """

    event_id: str
    event_type: str
    source: str
    occurred_at: datetime

    @classmethod
    def from_recorded(cls, recorded: RecordedEvent) -> "EventSummary":
        event = recorded.event
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            occurred_at=event.occurred_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EventTrigger:
    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    correlation_id: str
    payload: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "occurred_at", _require_aware(self.occurred_at, field_name="occurred_at")
        )

    @classmethod
    def from_recorded(cls, recorded: RecordedEvent) -> "EventTrigger":
        event = recorded.event
        # `correlation_id` nunca é None depois da construção de `Event`; o
        # fallback existe só para satisfazer o tipo declarado.
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            source=event.source,
            occurred_at=event.occurred_at,
            correlation_id=event.correlation_id or event.event_id,
            payload=event.payload,
        )

    @property
    def causation_id(self) -> str:
        """O evento que causou a decisão é o próprio gatilho."""
        return self.event_id

    def retrieval_text(self) -> str:
        """Consulta semântica derivada do gatilho.

        Só os valores textuais do payload: números e flags não ajudam a busca
        semântica e poluiriam a consulta.
        """
        words = [self.event_type.replace(".", " ")]
        words.extend(value for value in self.payload.values() if isinstance(value, str))
        return " ".join(words)[:MAX_RETRIEVAL_TEXT_LENGTH]


type AgentInput = UserMessage | EventTrigger
