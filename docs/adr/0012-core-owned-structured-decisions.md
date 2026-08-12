# 0012. `Decision` como JSON validado no Core, sem tool-calling do vendor

**Status:** Accepted
**Data:** 2026-08-12

## Contexto

O Agent Runtime precisa transformar a resposta do modelo numa `Decision`
estruturada. Os provedores oferecem dois mecanismos para isso:

- **structured output** — enviar um JSON Schema e receber a resposta já
  conformada;
- **tool/function calling** — declarar funções e receber uma chamada tipada.

O [ADR-0002](0002-llm-provider-abstraction.md) já decidiu que a interpretação
da resposta acontece no Core, sobre representação genérica. O que **não**
estava decidido é se o port `LLMProvider` carregaria uma superfície de tools e
de schema — e essa escolha molda o contrato do port, que atravessa componentes.

Há também um fato de escopo: não existe Skill Registry até a Fase 5. Um campo
de tool definitions no port não teria hoje quem o preenchesse.

## Decisão

1. **O Core é a autoridade sobre a forma da decisão.** `parse_decision` valida
   tipo, campos exigidos e campos proibidos por variante, e recusa qualquer
   coisa fora disso. A validação do provider, se existir, é conveniência —
   nunca a garantia.
2. **O port pede formato, não schema.** `LLMRequest.response_format`
   (`TEXT | JSON_OBJECT`) é o quanto o Core diz ao adapter. Nenhum JSON Schema
   é enviado ao vendor nesta fase.
3. **O port não tem superfície de tool-calling.** Capacidades disponíveis são
   descritas no envelope, em texto; uma proposta de ação volta como o campo
   `action` do JSON, validada apenas quanto à forma (`skill` é slug,
   `parameters` é JSON) — nunca resolvida contra um objeto executável.
4. Identidade e correlação (`decision_id`, `correlation_id`, `causation_id`)
   são atribuídas por quem chama, **nunca** lidas da resposta do modelo.

## Alternativas consideradas

- **Enviar `responseSchema` (JSON Schema) ao provider**: descartada por ora.
  Exigiria uma camada de tradução Core → dialeto de schema por vendor, e o
  Core teria de validar de novo mesmo assim, porque o ADR-0003 não permite
  tratar saída de LLM como confiável. Ganho marginal sobre pedir
  `application/json` + validar. Gatilho para reconsiderar: taxa de resposta
  malformada que a tentativa única de reparo não resolva.
- **Usar tool-calling nativo para `Decision.act`**: descartada para esta fase.
  Sem Skill Registry, as definições de tool seriam inventadas — abstração
  especulativa (contracts §1). Gatilho concreto: a subfase 5.2, quando existir
  registry real de capacidades.
- **Deixar o modelo devolver texto livre e interpretar por heurística**:
  descartada — é o oposto de uma decisão estruturada validável, e tornaria
  impossível afirmar o que o agente decidiu.

## Consequências

- Trocar de provider não muda nada em `decision.py`: a validação é nossa e
  funciona igual sobre a saída de qualquer modelo que consiga emitir JSON.
- Funciona com provedores que não suportem schema nem tool-calling.
- O Core precisa tolerar cerca markdown e prosa em volta do objeto — resolvido
  de forma limitada e determinística (`_json_candidates`), sem tentar consertar
  JSON malformado.
- Uma resposta inválida custa **uma** tentativa extra de reparo e depois falha
  explicitamente, em vez de degradar para uma decisão inventada.
- O campo `action.skill` fica sem validação semântica até a Fase 5. Isso é
  seguro precisamente porque nada o executa: o nome viaja como dado até o
  Policy Engine existir.
