# 0033. Checkpoint do Goal Pursuit Loop como estado operacional, fora do Event Store

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

O Goal Pursuit Loop (Fase 9.2, `jarvis agent pursue`) reinvoca o Agent
Runtime em sequência, um passo por `Decision`, até um dos cinco critérios de
parada. Até a Fase 10.5, se o processo morresse no meio — ou parasse numa
confirmação pendente — não havia como retomar: rodar `agent pursue` de novo
reiniciava o raciocínio do zero, sem lembrar dos passos já dados.

Fechar isso exige guardar, entre invocações do CLI, o suficiente para
continuar: o objetivo original, quantos passos já rodaram, o desfecho da
última ação e a proposta anterior (para o guard de repetição continuar
funcionando). O problema é o mesmo do
[ADR-0014](0014-confirmation-state-and-event-answers.md) para
`PendingAction`: esse "suficiente para continuar" inclui parâmetros de ação
e resumos de execução — exatamente o tipo de dado pessoal que o Decision Log
e a trilha de auditoria já excluem de propósito
(`decisions/record.py`, `execution/events.py`: "nenhum payload carrega os
parâmetros da ação"). Guardar isso no Event Store, imutável e perpétuo
([ADR-0004](0004-event-immutability-and-timestamps.md)), repetiria o mesmo
mau negócio que o ADR-0014 já recusou para confirmações.

## Decisão

`PursuitState` (`src/jarvis/pursuits/`) é estado operacional, apagável — o
mesmo tipo de coisa que `PendingAction` (ADR-0014) e `BackgroundTask`
(Fase 7.5), nunca um evento:

1. **Sétimo banco SQLite** (`data/pursuits.db`), mesmo padrão dos seis
   anteriores — um componente, um schema, um `user_version`.
2. **Um método de transição só, `advance`** — não a coleção
   `mark_succeeded`/`mark_failed`/`schedule_retry` de `TaskRepository`.
   Diferente de uma tarefa em background (que tem desfechos distintos e
   reais), todo passo do Goal Pursuit Loop muda exatamente o mesmo conjunto
   de campos junto (`step`, `status`, `last_action_result`,
   `previous_proposal`) — uma transição, não várias.
3. **`last_action_result`/`previous_proposal` viajam como documentos JSON
   soltos**, não tipados no pacote `pursuits`. Só `cli._agent_pursue` sabe a
   forma exata deles (`ActionResultSummary`, `(skill, parameters)`); modelar
   esse acoplamento em `jarvis.pursuits` duplicaria uma forma que já existe
   em `jarvis.agent`, e obrigaria o pacote a importar `jarvis.agent` só para
   guardar um checkpoint — o mesmo problema que o bridge adapter do
   ADR-0032 evita para `jarvis.proactivity`.
4. **`--resume` não reconcilia estado externo.** Se o usuário confirma uma
   ação pendente via `jarvis action confirm` enquanto o pursuit está parado,
   retomar não vai buscar o desfecho real dessa confirmação — usa o último
   checkpoint salvo (que ainda diz `awaiting_confirmation`) como
   `last_action_result` do próximo turno. É uma limitação aceita, não uma
   omissão: reconciliar exigiria `jarvis.pursuits` consultar
   `jarvis.execution` (`ActionRepository`), o mesmo tipo de acoplamento que
   o item 3 evita, por um ganho que nenhum caso de uso concreto pediu ainda.

## Alternativas consideradas

- **Reconstruir o checkpoint a partir do Decision Log/Event Store** —
  descartada primeiro: `DecisionRecord` não carrega parâmetros de ação
  nem o `data`/`summary` completo de um `ExecutionOutcome`, de propósito.
  Não há como reconstruir `previous_proposal` (precisa dos parâmetros
  exatos) nem um `last_action_result` fiel a partir do que já é
  persistido — a informação nunca esteve lá.
- **Tipar `last_action_result`/`previous_proposal` com os tipos reais de
  `jarvis.agent`** — descartada: obrigaria `jarvis.pursuits` a importar
  `jarvis.agent`, quebrando a garantia de que só o composition root conhece
  os dois ao mesmo tempo (mesmo critério do ADR-0032 para
  `jarvis.proactivity`/`jarvis.memory`).
- **Reconciliar automaticamente com `ActionRepository` no resume** —
  descartada por agora: nenhum caso de uso real pediu isso, e a alternativa
  mais simples (usar o checkpoint tal como salvo) já é suficiente e honesta
  sobre sua limitação. Gatilho para revisitar: se o hiato entre pausa e
  confirmação começar a produzir decisões visivelmente erradas na prática.
- **`jarvis pursuits list/show/cancel` nesta mesma subfase** — descartada
  por escopo: a porta (`PursuitRepository`) foi desenhada genérica o
  bastante para crescer sem retrabalho, mas os comandos em si não têm
  consumidor real ainda além do próprio `--resume`.

## Consequências

- Oitavo componente com store próprio (`event`, `context`, `memory`,
  `action`, `voice`, `task`, agora `pursuit`) — mesmo padrão replicado uma
  vez mais, sem desenho novo.
- `jarvis agent pursue` sempre imprime `pursuit <id>` no início — mesmo sem
  usar `--resume` depois, o id fica disponível caso o processo pare.
- Um `PursuitState` com `status=completed` nunca é retomável
  (`is_resumable`); todos os outros — inclusive teto de passos atingido —
  são, com um orçamento de passos novo se `--max-steps` não for repetido.
- **Gatilho para revisitar:** se surgir necessidade real de listar/cancelar
  pursuits pendentes, ou de reconciliar estado externo no resume, este ADR
  precisa ser revisto — a porta já comporta os métodos novos, o Core não.
