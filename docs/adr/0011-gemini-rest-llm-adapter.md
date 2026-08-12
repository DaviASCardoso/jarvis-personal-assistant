# 0011. Gemini em nuvem, via REST da stdlib, como primeiro `LLMProvider`

**Status:** Accepted
**Data:** 2026-08-12

## Contexto

A Fase 4 precisa de uma implementação concreta de `LLMProvider`
([ADR-0002](0002-llm-provider-abstraction.md)). Três forças em jogo:

1. **Custo e operação.** O Jarvis é um projeto pessoal rodando na máquina do
   usuário. Um modelo local consumiria RAM/VRAM, exigiria baixar e manter
   pesos, e tornaria o desenvolvimento dependente do hardware disponível.
2. **Dependências.** Até aqui o projeto tem **uma** dependência de runtime
   (`pydantic-settings`, com `pydantic`). O SDK oficial do Gemini traz
   `grpcio`, `protobuf`, `google-auth` e sua árvore transitiva — dezenas de
   megabytes e uma superfície de atualização que não controlamos, para uma
   necessidade que é um POST JSON.
3. **Verificabilidade da fronteira.** `test_agent_architecture.py` precisa
   conseguir afirmar "nenhum SDK de vendor entra aqui". Com um SDK instalado, a
   afirmação vira "nenhum SDK **além deste**", que é bem mais frágil.

## Decisão

1. O primeiro adapter concreto é **Google Gemini API, exclusivamente em
   nuvem**, usando a opção gratuita disponível. **Não** há modelo local nesta
   fase nem preparação para um.
2. O adapter fala com a API por **REST, usando `urllib.request` da biblioteca
   padrão**. Nenhum SDK de vendor e nenhum cliente HTTP de terceiros entra em
   `dependencies`.
3. O transporte é injetável (`opener`), o que permite testar corpo de
   requisição, parsing e mapeamento de erro sem rede.
4. A credencial viaja no header `x-goog-api-key`, **nunca** na query string.
5. O nome do modelo é **configuração** (`JARVIS_GEMINI_MODEL`), não constante
   de contrato.

## Alternativas consideradas

- **SDK oficial (`google-genai`/`google-generativeai`)**: descartada. Traria
  grpc/protobuf/google-auth para chamar um endpoint que aceita JSON puro;
  esconderia o corpo da requisição atrás de uma camada que teríamos de
  mockar de qualquer forma nos testes; e enfraqueceria o gate de arquitetura.
  Reversível a qualquer momento: trocar o transporte não muda o port.
- **`httpx`/`requests`**: descartada pelo mesmo motivo, em menor escala. O
  ganho sobre `urllib` seria conveniência de API para ~40 linhas de código.
- **Modelo local (Ollama, llama.cpp)**: descartada para esta fase. Custo de
  hardware, manutenção de pesos e latência de desenvolvimento incompatíveis
  com um projeto pessoal; e o ADR-0002 já garante que adicionar um adapter
  local depois não toca o Agent Runtime.
- **Múltiplos providers desde o início**: descartada — o ADR-0002 já torna a
  troca barata, e um segundo adapter sem uso real seria abstração
  especulativa (contracts §1).

## Consequências

- Zero dependência de runtime nova na Fase 4 (só a declaração explícita de
  `pydantic`, que já vinha por trânsito).
- O adapter carrega a tradução de wire à mão: `contents`/`parts`/
  `generationConfig` na ida, `candidates`/`finishReason`/`usageMetadata` na
  volta. Se o formato da API mudar, o custo cai inteiro sobre
  `agent/adapters/gemini.py` — que é exatamente onde deve cair.
- O parsing é tolerante de propósito (`finishReason` desconhecido vira `OTHER`,
  `usage` ausente vira ausente) para que uma adição de campo do provider não
  quebre o Jarvis.
- Depender de nuvem significa que texto do prompt sai do dispositivo. A
  contrapartida está registrada: `recent_events` viajam sem payload, secrets
  nunca entram no prompt, e o Policy Engine (Fase 5) continua sendo a única
  autoridade sobre ação.
- Não resolve, e não tenta resolver: streaming, tool-calling nativo e
  limitação de taxa client-side. Todos têm gatilho registrado em
  `docs/phase-4-plan.md §20`.
