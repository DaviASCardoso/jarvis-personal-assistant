"""Ports do Agent Runtime.

`LLMProvider` é o único port deste componente. `PromptBuilder`, `AgentRuntime` e
o Importance Engine **não** são ports: cada um tem implementação única e nenhum
substituto real — mesma assimetria de `EventBus`/`EventStore` na Fase 1,
`ContextAggregator`/`ContextSnapshotRepository` na Fase 2 e
`MemoryManager`/`MemoryRepository` na Fase 3.

`LLMProvider` é separado de `EmbeddingProvider`
([ADR-0002](../../../docs/adr/0002-llm-provider-abstraction.md)) para que trocar
o modelo de raciocínio nunca arrisque invalidar os vetores já indexados, e
vice-versa. Os dois podem, por coincidência, vir do mesmo fornecedor — nunca por
acoplamento.
"""

from typing import Protocol

from jarvis.agent.messages import LLMModel, LLMRequest, LLMResponse


class LLMProvider(Protocol):
    """Fonte de raciocínio textual.

    Contrato que todo adapter precisa cumprir:

    - **não** busca contexto, memória, eventos, capacidades ou configuração do
      Jarvis — recebe uma `LLMRequest` já pronta e nada mais;
    - **não** monta prompt e **não** interpreta a resposta como decisão: as duas
      coisas acontecem no Core (ADR-0002);
    - não guarda estado entre chamadas — nem histórico, nem cache;
    - traduz toda exceção nativa de SDK, HTTP ou rede para a taxonomia de
      `agent/errors.py`; nenhuma exceção de vendor chega ao Core;
    - respeita `request.timeout_seconds` como orçamento da chamada.
    """

    @property
    def model(self) -> LLMModel: ...

    def generate(self, request: LLMRequest) -> LLMResponse: ...
