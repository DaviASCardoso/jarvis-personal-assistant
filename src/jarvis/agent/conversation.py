"""Histórico conversacional — a quarta fonte de informação do agente.

`PHASE-4.md §15` exige que quatro coisas não sejam confundidas numa estrutura só:

| o quê | onde vive | natureza |
|---|---|---|
| estado atual do mundo | `CurrentContext` | projeção derivada, com TTL por campo |
| conhecimento durável | `Memory` | fonte de verdade, com ciclo de vida |
| histórico da conversa | `Conversation` (aqui) | efêmero, ordenado, do turno atual |
| mensagem atual | `UserMessage` | a entrada sendo processada |

`Conversation` é imutável e vive em memória. Persistir sessão é escopo de
Voice Sessions (6.4): guardar diálogo em disco sem política de retenção seria
criar um repositório de dado pessoal sem quem responda por ele.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jarvis.agent.errors import InvalidLLMRequestError
from jarvis.agent.messages import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationTurn:
    role: Role
    text: str
    at: datetime

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidLLMRequestError("texto de turno não pode ser vazio")
        if self.at.utcoffset() is None:
            raise InvalidLLMRequestError("at precisa ser timezone-aware")
        object.__setattr__(self, "at", self.at.astimezone(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class Conversation:
    conversation_id: str
    turns: tuple[ConversationTurn, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise InvalidLLMRequestError("conversation_id não pode ser vazio")

    def append(self, turn: ConversationTurn) -> "Conversation":
        """Devolve uma conversa nova: nenhum turno já dito é reescrito."""
        return Conversation(conversation_id=self.conversation_id, turns=(*self.turns, turn))

    def last(self, count: int) -> Sequence[ConversationTurn]:
        if count <= 0:
            return ()
        return self.turns[-count:]
