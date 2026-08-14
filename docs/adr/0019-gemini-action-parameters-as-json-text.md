# 0019. `action.parameters` transportado como texto JSON no adapter Gemini

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A Fase 5 fechou a cadeia `Decision.act → Policy Engine → Skill → Tool Router`.
A validação de ponta a ponta mostrou que ela nunca chegava ao fim para uma Skill
com parâmetro obrigatório: o agente pedia `file.write` e a execução falhava com
`invalid_parameters: campo obrigatório ausente: path`.

A causa não estava no Core nem no prompt, e sim no `responseSchema` enviado ao
Gemini ([ADR-0011](0011-gemini-rest-llm-adapter.md)). Ele declarava:

```json
"parameters": {"type": "object"}
```

O subconjunto OpenAPI aceito por `responseSchema` **não expressa "objeto de
forma livre"**: um `object` sem `properties` não tem campo algum que o modelo
possa preencher. Medido contra a API real, com o mesmo prompt e o mesmo modelo,
variando só o schema:

| `parameters` declarado como | o que o modelo devolveu |
|---|---|
| `{"type": "object"}` | `{}` — em toda chamada |
| `{"type": "string"}` | `"{\"path\":\"relatorio.txt\",\"content\":\"fase 5 ok\"}"` |

Não era o modelo se recusando a colaborar: era o schema tornando a colaboração
impossível. O efeito prático é que `act` só funcionava para Skills cujos campos
fossem todos opcionais — uma das quatro embutidas.

O aperto é estrutural, não um detalhe do vendor: os parâmetros de uma Skill são
conhecidos em runtime (o registry varia), enquanto o `responseSchema` é um
documento só, montado antes de saber qual Skill o modelo vai escolher.

## Decisão

`action.parameters` viaja **como texto JSON** no fio, declarado
`{"type": "string"}` com descrição e exemplo, e é decodificado de volta para
objeto em `_decode_action_parameters`, dentro do `GeminiLLMProvider`, antes de o
texto chegar ao Core.

O contrato do Core não muda: `ActionProposal.parameters` continua sendo
`Mapping[str, JsonValue]`, `parse_decision` continua recusando o que não for
objeto, e nenhum módulo fora do adapter sabe que houve transporte em texto.

A decodificação **nunca inventa parâmetro**. Quando o texto não é JSON, ele
segue intacto e quem recusa a proposta é o Core — errar para o lado da proposta
rejeitada é o desfecho seguro quando o assunto é o que será executado. Texto
vazio é lido como "sem parâmetros" (`{}`), e uma Skill com campo obrigatório
continua sendo barrada pela validação de schema, mais adiante.

## Alternativas consideradas

**Declarar os parâmetros de cada Skill no schema.** Exigiria um `oneOf` por
Skill registrada, montado a cada chamada — palavra-chave que o subconjunto
aceito por `responseSchema` não cobre. Além disso, faria o adapter conhecer o
Skill Registry, quebrando a fronteira que
[ADR-0005](0005-skill-tool-mcp-distinction.md) e os testes de arquitetura
protegem.

**Abandonar o `responseSchema` e ficar só com `responseMimeType`.** Foi o estado
anterior a `5367daf`, e ele voltava prosa em vez de decisão com frequência
suficiente para justificar aquele commit. Trocaria um modo de falha determinado
(parâmetro sempre vazio) por um probabilístico (formato às vezes errado) — pior
para depurar e mais caro, porque cada resposta malformada custa uma tentativa de
reparo.

**Usar tool-calling nativo do vendor.** É a superfície que
[ADR-0012](0012-core-owned-structured-decisions.md) recusou de propósito: ela
move a estrutura da decisão para dentro do fornecedor, que é exatamente o
acoplamento que o `LLMProvider` existe para evitar. Continua recusada.

## Consequências

- `act` passa a funcionar para Skills com parâmetro obrigatório — a capacidade
  central da Fase 5, verificada de ponta a ponta com `file.write`.
- A tradução é local ao adapter: um `LLMProvider` futuro cujo structured output
  expresse objeto livre simplesmente não implementa a codificação, sem tocar no
  Core. É o caso de uso que justifica o port existir.
- Um custo declarado: o modelo escreve JSON dentro de JSON, e escape errado
  vira proposta recusada em vez de execução torta. A troca é deliberada —
  recusar é reversível, executar não.
- `docs/agent-runtime.md` registra a codificação na tabela do adapter;
  `tests/test_agent_gemini.py` cobre o schema enviado e os quatro desfechos da
  decodificação (objeto, vazio, indecifrável, já-objeto).
