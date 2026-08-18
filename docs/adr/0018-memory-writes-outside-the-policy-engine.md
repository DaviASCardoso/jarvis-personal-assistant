# 0018. Proposta de memória aplicada pelo composition root, fora do Policy Engine

**Status:** Accepted
**Data:** 2026-08-14

> **Exceção pontual (Fase 11.4):** este ADR governa criação/reforço de
> memória (`remember`, via `Decision.memory`) — continua exatamente como
> descrito abaixo. Esquecer uma memória por pedido do agente (`forget`) foi
> deliberadamente tratado diferente e passou a ser uma Skill sujeita ao
> Policy Engine, não uma extensão deste caminho ungated — ver
> [ADR-0034](0034-forget-memory-as-a-policy-gated-skill.md) para o porquê.

## Contexto

`Decision.remember` existe desde a Fase 4 e nunca foi aplicada: o turno imprimia
a proposta e parava. A Fase 5 fechou o laço da **ação** — `Decision.act` chega ao
`ActionExecutor`, que consulta o Policy Engine antes de qualquer efeito — e
deixou a memória de fora de propósito (`phase-5-plan.md §33`, V-5).

O laço da memória continuava aberto: o agente recebia memórias no prompt, decidia
que algo valia guardar, e o que ele decidia guardar era descartado. Um sistema
que lê memória e não escreve nenhuma só aprende pelo que o usuário digitar em
`jarvis memory add`.

Quem fecha o laço é a pergunta a decidir, e há um contrato forte perto dela:
[ADR-0003](0003-policy-engine-safety-authority.md) diz que o Agent Runtime não
executa o que propõe, e que o Policy Engine é a autoridade determinística única
sobre `allow`/`deny`/`require_confirmation`.

## Decisão

O **composition root** (`cli.py`) aplica a proposta de memória, logo depois de
receber o `AgentTurn` e antes de imprimi-lo — o mesmo desenho de
`_submit_proposal`, que entrega `Decision.action` ao `ActionExecutor`. O Agent
Runtime não muda: continua sem escrever nada, e `tests/test_agent_runtime.py`
continua afirmando isso.

A gravação **não** passa pelo Policy Engine e **não** é opt-in por flag, ao
contrário de `--execute`. Uma capacidade e uma afirmação não são a mesma coisa:

- uma Skill toca o mundo fora do processo (arquivo, rede, comando); uma memória
  toca uma tabela do próprio Jarvis;
- uma Skill executada não se desfaz; uma memória se desfaz por supersessão e
  invalidação, que é o que [ADR-0010](0010-immutable-memory-and-supersession.md)
  já garante — e `jarvis memory forget` já expõe;
- o vocabulário do Policy Engine é `capability`/`risk`/`effect` sobre Skills
  registradas. "Gravar memória" não é uma Skill, e transformá-la numa só para
  ter o que autorizar criaria uma capacidade sem backend, exatamente a abstração
  especulativa que `architecture-contracts.md §1` proíbe.

Aplica-se a **qualquer** decisão que carregue `memory`, não só `remember`: a
matriz de validação de `decision.py` permite `notify` com proposta junto.

**Proveniência, por caminho de entrada:**

| entrada | `origin` | `reference` |
|---|---|---|
| `agent ask` / `agent chat` | `USER` | nenhuma |
| `agent react` | `EVENT` | o `event_id` do gatilho |

Sem `reference` no caminho do usuário porque não há artefato durável para
apontar — decisões só viram trilha consultável na 7.4, conversas só são
persistidas na 6.4 — e porque `find_duplicate` exige a **mesma** `reference`
para deduplicar: um ponteiro que ainda não resolve custaria a consolidação, e
cada repetição da mesma afirmação viraria linha nova em vez de reforço. No
caminho do evento a referência resolve no Event Store, e é a mesma que o
`MemoryEventConsumer` já grava — as duas rotas convergem na mesma memória em vez
de duplicá-la.

`MemoryProposal` é mais permissivo que `Memory`: não tem `scope` nem
`valid_until`, então uma proposta `task`, `working`, ou `preference` sem
`subject` é válida como decisão e recusada pelo domínio. A recusa é **da
proposta, não do turno** — a mensagem e a ação da mesma decisão continuam
valendo, e o motivo é impresso.

## Alternativas consideradas

- **Gravar atrás de `--execute`, como a ação:** descartada — acoplaria duas
  autorizações diferentes à mesma flag. Quem roda `agent ask` sem `--execute`
  está dizendo "não execute capacidades", não "não aprenda nada"; e um usuário
  que precisasse pedir para ser lembrado a cada mensagem não teria memória
  automática nenhuma.
- **Submeter a gravação ao Policy Engine como uma Skill `memory.write`:**
  descartada — uma Skill existe para compor Tools e tocar o mundo externo
  ([ADR-0005](0005-skill-tool-mcp-distinction.md)). Uma que só chamasse
  `MemoryManager.remember` seria uma indireção para reusar um vocabulário de
  risco que não descreve o que ela faz, e ainda daria ao agente um caminho para
  escrever memória com parâmetros arbitrários via `Decision.act`.
- **`AgentRuntime` grava direto:** descartada — o runtime já segura um
  `MemoryManager` para `retrieve`, então seria a mudança de menos linhas. Viola o
  ADR-0003 no princípio ("propõe e para") e apagaria a distinção entre o que o
  modelo sugeriu e o que o sistema decidiu aceitar.
- **`origin=AGENT`:** descartada para o caminho do usuário. A afirmação é do
  usuário; o agente só a extraiu da mensagem. `AGENT` é para inferência do
  modelo, e o domínio inclusive proíbe `confidence == 1.0` nesse caso.
- **Levantar `InvalidMemoryError` até o `main`:** descartada — o comando sairia
  com código 2 e o usuário perderia a resposta e a ação por causa de um campo
  que o modelo não preencheu.

## Consequências

- O agente aprende: `agent ask`, `agent chat` e `agent react` gravam, e o que
  foi gravado aparece em `jarvis memory list` e volta no próximo prompt via
  `MemoryRetrieval`.
- A saída do turno passa a distinguir três desfechos — gravada, reforçada,
  recusada — e um `remember` puro ganha uma frase de confirmação, que é também o
  turno do assistente na conversa.
- **Custo aceito:** o modelo passa a ter um efeito de escrita que ninguém
  autoriza caso a caso. O limite disso é o que a memória pode fazer — nada fora
  do processo — e o remédio é `jarvis memory forget`. Se o `agent react`
  autônomo (7.1, sem usuário na frente) mostrar que memórias ruins se acumulam,
  o lugar de tratar isso é uma política de consolidação no Memory System, não o
  Policy Engine.
- Superfície de prompt injection: um evento hostil pode induzir uma memória
  falsa. Já era verdade para o `MemoryEventConsumer`, que grava a partir de
  eventos sem passar por LLM nenhum; a proveniência (`EVENT` + `event_id`) é o
  que permite rastrear e invalidar em bloco.
- A Fase 7.4 (Decision Logging) torna a decisão um artefato consultável. Quando
  isso existir, `reference` no caminho do usuário passa a ter para onde apontar —
  e a escolha precisa ser reavaliada junto do impacto em `find_duplicate`.
