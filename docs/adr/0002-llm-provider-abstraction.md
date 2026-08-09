# 0002. Abstração de LLM Provider e separação de Embedding Provider

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

O Agent Runtime (Fase 4) precisa de um LLM para raciocinar. A regra 12 do
`ROADMAP.md` já declara: "não acoplar o sistema a um único fornecedor de
LLM". Sem um contrato explícito desde a 0.3, é fácil que a primeira
implementação da Fase 4 espalhe chamadas ao SDK de um vendor específico
(formato de mensagem, formato de tool-calling, formato de erro) por Agent
Runtime, PromptBuilder e Skills — tornando a troca de provider, ou o suporte
a múltiplos providers, uma reescrita em vez de uma troca de adapter.

Um segundo problema adjacente: a Memory System (Fase 3) precisa de busca
semântica, o que exige gerar embeddings — tecnicamente também "uma chamada
de modelo". Se Memory depender do mesmo `LLMProvider` usado pelo raciocínio
do Agent Runtime, ela fica acoplada a decisões de raciocínio (ex. troca de
modelo de chat) que não têm relação com a qualidade da busca semântica, e
vice-versa.

## Decisão

1. Definir um port `LLMProvider` no Core, com request/response
   vendor-agnósticos: mensagens, definições de tool em schema genérico,
   system prompt e parâmetros de geração na entrada; texto, tool-calls
   genéricos, stop-reason e uso de tokens na saída.
2. Prompt assembly, seleção de quais tools expor, e interpretação da
   resposta em `Decision` acontecem inteiramente no Core, sobre a
   representação genérica — nunca sobre o formato de wire de um vendor
   específico. A tradução para/do formato do vendor acontece só dentro do
   adapter correspondente em Infrastructure.
3. Erros de provider são mapeados pelo adapter para uma taxonomia própria do
   Core (`LLMTimeoutError`, `LLMRateLimitError`, `LLMProviderError`,
   `LLMInvalidResponseError`).
4. Memory depende de um port **separado**, `EmbeddingProvider`, mesmo que na
   prática o mesmo vendor implemente ambos os ports em algum momento.

Detalhamento em
[`architecture-contracts.md §4`](../architecture-contracts.md#4-llm-independence).

## Alternativas consideradas

- **Um único port genérico "ModelProvider" cobrindo chat e embeddings**:
  descartada — combinaria dois ciclos de vida e motivações de troca
  diferentes (trocar o modelo de raciocínio não deveria arriscar quebrar a
  busca semântica existente, e vice-versa) em uma única interface.
- **Acoplar diretamente ao SDK do vendor inicialmente e abstrair depois**
  ("YAGNI, abstrai quando precisar trocar"): descartada para este caso
  específico — trocar de vendor de LLM é uma necessidade conhecida e
  provável (custo, disponibilidade, qualidade), não hipotética, e o roadmap
  já declara essa não-negociação na regra 12. O custo de definir o port
  desde a Fase 4 é baixo comparado ao custo de desacoplar depois que Agent
  Runtime, PromptBuilder e Skills já dependerem do formato de um vendor.

## Consequências

- Trocar de provider de LLM = escrever um novo adapter + selecionar via
  configuração; zero mudança em Agent Runtime, PromptBuilder, `Decision` ou
  Skills.
- Fica mais fácil, no futuro, usar modelos diferentes para papéis diferentes
  (ex. um modelo mais barato para triagem de importância, um mais forte para
  raciocínio completo) sem redesenhar o port.
- Adiciona uma camada de tradução (Core ↔ formato do vendor) que não existe
  se o sistema chamar o SDK diretamente — custo aceito em troca da
  substituibilidade.
- Não define, nesta fase, o schema exato de `LLMRequest`/`LLMResponse` — são
  detalhes de contrato a refinar na implementação da 4.1, não decisões
  arquiteturais deste ADR.
