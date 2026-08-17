# 0026. Decision log como eventos, construído a partir de primitivos

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A subfase 7.4 do [roadmap](../../ROADMAP.md) pede registrar decisões,
contexto usado, memória usada, razão e ações, com consulta posterior. Até
aqui, uma `Decision` só existe durante o turno que a produziu (`AgentTurn`,
em memória) — `agent ask`/`agent react` imprimem e esquecem; o painel
(ADR-0024) mostra só o turno em curso, e o próprio ADR-0024 já deixou isso
registrado como pendência explícita ("`DecisionCard` já tem a forma que a
7.4 vai preencher").

A Fase 5 já resolveu um problema estruturalmente idêntico para execução:
[ADR-0017](0017-audit-trail-as-events.md) fez da trilha de auditoria um fluxo
de eventos, sem um store próprio. A decisão óbvia é generalizar o mesmo
padrão para decisões — mas fazer isso literalmente (um componente que
recebe `Decision`/`AgentTurn` e os traduz) criaria uma dependência de
`jarvis.decisions` sobre `jarvis.agent`, algo que nenhum dos componentes
existentes tem: `jarvis.execution`, que já depende de meio sistema, não
depende de `jarvis.agent` — é o ADR-0003 e o teste
`test_the_earlier_components_do_not_know_the_action_layer` que garantem
isso.

## Decisão

`jarvis/decisions/events.py` expõe `decision_event(...)` recebendo
**primitivos** — `decision_id: str`, `decision_type: str`, `reason: str`,
`message: str | None`, `decided_at: datetime`, `correlation_id: str`,
`causation_id: str | None`, `consulted_llm: bool`, `importance: float |
None`, `used_memory_ids: Sequence[str]`, `context_as_of: datetime | None`,
`action_skill: str | None` — nunca `Decision` ou `AgentTurn`. O composition
root (`cli.py`, função `_record_decision`) é quem extrai esses campos de um
`AgentTurn` recém-produzido e publica o evento resultante
(`agent.decision_recorded`), exatamente como já fazia para
`voice_session_event`.

`event_id` é determinístico a partir de `decision_id` — reapresentar o mesmo
turno (retry, reconexão) é no-op no Event Store, nunca uma segunda linha na
trilha.

Nenhum parâmetro de ação nem conteúdo de memória entra no payload — só
`used_memory_ids` (identidade, não conteúdo) e `action_skill` (nome, não
parâmetros). "Registrar ações" não duplica a auditoria da Fase 5: como
`ActionRequest.correlation_id` é sempre `decision.correlation_id`, a mesma
`correlation_id` já liga decisão e execução — `jarvis decisions list
--correlation-id X` mostra a decisão; `jarvis action show` mostra a
execução; nenhuma das duas precisa saber da outra.

## Alternativas consideradas

- **`jarvis.decisions` importa `jarvis.agent.decision.Decision`**: mais
  direto, e a alternativa descartada — criaria a primeira aresta de
  `jarvis.agent` sendo dependência de outro componente de Core (hoje ele só
  depende de coisas, nunca é dependido), e obrigaria `jarvis.decisions` a
  acompanhar toda mudança de forma da `Decision` mesmo quando o log não
  precisa dela.
- **O próprio Agent Runtime publica o evento**: descartada de imediato —
  romperia a regra da Fase 4 ("o Agent Runtime não emite eventos") e o
  ADR-0003 na mesma tacada. O ganho de fechar a integração pertence a quem
  já fecha as outras (o composition root), não ao Agent Runtime.
- **Um `AuditKind` novo em `jarvis.audit`, reaproveitando a infraestrutura da
  Fase 5**: descartada — `jarvis.audit` é dividido por três componentes que
  não se conhecem (`policy`, `tools`, `execution`); decisões são uma
  categoria conceitualmente diferente (juízo do agente, não execução), e
  forçá-la no mesmo enum misturaria duas trilhas com donos diferentes.

## Consequências

- `jarvis.decisions` permanece folha o suficiente para ser testado sem
  nenhum outro componente do sistema: os testes constroem `Event`/
  `RecordedEvent` diretamente, nunca uma `Decision`.
- O painel (`ObservabilityService._decision_cards`) ganha histórico
  persistido de graça, lendo os mesmos eventos que já lê para a timeline —
  sem consulta nova, sem banco novo.
- **Custo aceito:** o composition root cresce mais uma função
  (`_record_decision`) chamada em quatro lugares (`agent ask`, `agent chat`,
  `agent react`, `RuntimeConversationalAgent.respond`) — o mesmo padrão de
  repetição que `_persist_memory_proposal` já tem, e pela mesma razão: é o
  único lugar autorizado a fazer essa ponte.
- **Não resolve:** um "porquê" navegável que junte decisão + contexto
  completo + memórias completas + execução numa única consulta. O que existe
  é a correlação por `correlation_id` entre três fontes já existentes — uma
  visão unificada, se vier a valer a pena, é trabalho de interface sobre
  dado que já está todo lá.
