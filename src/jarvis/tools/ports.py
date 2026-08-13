"""Ports da camada de Tools.

`ToolBackend` é o único port aqui. `ToolRouter`, `ToolRegistry` e `ToolAccess`
**não** são ports: cada um tem implementação única e nenhum substituto real —
mesma assimetria de `EventBus`/`EventStore` na Fase 1 e de
`MemoryManager`/`MemoryRepository` na Fase 3.

Que exista mais de um backend (`local`, MCP) não é acidente de teste: é a prova
executável de que o contrato de `Tool` não é o formato de wire do MCP disfarçado
([ADR-0005](../../../docs/adr/0005-skill-tool-mcp-distinction.md)). Um backend
futuro que não seja MCP entra implementando este Protocol, sem tocar em Skill,
Policy ou Router.
"""

from collections.abc import Sequence
from typing import Protocol

from jarvis.tools.tool import ToolCall, ToolDescriptor, ToolResult


class ToolBackend(Protocol):
    """Onde uma Tool efetivamente mora.

    Contrato que todo adapter precisa cumprir:

    - **não** conhece Skill, Policy, Agent Runtime nem o motivo da chamada —
      recebe um `ToolCall` técnico e nada mais;
    - traduz toda exceção nativa (SDK, `subprocess`, `OSError`, JSON-RPC) para a
      taxonomia de `tools/errors.py`; nenhuma exceção crua chega ao router;
    - respeita `timeout_seconds` como orçamento da chamada;
    - `discover()` pode falhar com `ToolUnavailableError` sem derrubar o
      processo: o registry marca o backend como degradado.
    """

    @property
    def backend_id(self) -> str: ...

    def discover(self) -> Sequence[ToolDescriptor]: ...

    def invoke(self, call: ToolCall, *, timeout_seconds: float) -> ToolResult: ...

    def close(self) -> None: ...
