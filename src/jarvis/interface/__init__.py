"""Painel de observabilidade: o estado interno do Jarvis, visível.

API pública do componente. Este pacote é uma **Interface** que só lê: monta view
models a partir das fontes de verdade (Event Store, Context Engine, Memory,
repositório de ações e a sessão de voz em curso) e os entrega a um servidor HTTP
local.

O que ele **não** conhece, e um teste arquitetural garante: `jarvis.agent`,
`jarvis.skills`, `jarvis.tools`, `jarvis.policy`, o orquestrador de execução,
qualquer `*.adapters` de outro componente, `jarvis.config` e `sqlite3`. Só tipos
de domínio atravessam a fronteira.
"""

from jarvis.interface.errors import InterfaceError, PanelAddressInUseError, PanelError
from jarvis.interface.live import LiveState
from jarvis.interface.service import ObservabilityService, memory_card_of
from jarvis.interface.viewmodel import (
    DEFAULT_TOAST_TYPES,
    ActionCard,
    ContextRow,
    ConversationEntry,
    DecisionCard,
    MemoryCard,
    PanelSnapshot,
    Severity,
    TimelineEntry,
    Toast,
    ToolCard,
    TurnTrace,
    VoiceStatusView,
    to_json_object,
)

__all__ = [
    "DEFAULT_TOAST_TYPES",
    "ActionCard",
    "ContextRow",
    "ConversationEntry",
    "DecisionCard",
    "InterfaceError",
    "LiveState",
    "MemoryCard",
    "ObservabilityService",
    "PanelAddressInUseError",
    "PanelError",
    "PanelSnapshot",
    "Severity",
    "TimelineEntry",
    "Toast",
    "ToolCard",
    "TurnTrace",
    "VoiceStatusView",
    "memory_card_of",
    "to_json_object",
]
