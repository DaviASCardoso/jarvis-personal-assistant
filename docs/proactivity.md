# Proatividade

**Documentação de implementação.** Descreve o que existe em
`src/jarvis/proactivity/`, `src/jarvis/notify/`, `src/jarvis/decisions/` e
`src/jarvis/tasks/` desde a Fase 7, e o wiring correspondente em `cli.py`.
Não é normativo — para as regras que este código precisa respeitar, ver
[`architecture-contracts.md §3.15–3.17`](architecture-contracts.md) e os
ADRs 0026–0029.

## Visão geral

Até a Fase 6, o Jarvis só raciocinava ou agia quando alguém pedia na hora
(`agent ask`/`agent react`, `--execute`). A Fase 7 acrescenta a capacidade
de reagir a eventos **sem** esse pedido imediato, durante `jarvis run` —
sem introduzir nenhuma capacidade cognitiva nova (o raciocínio continua
sendo o Agent Runtime da Fase 4) e sem reabrir a cadeia de execução (todo
caminho proativo aciona `ActionExecutor`, nunca a reimplementa —
[ADR-0016](adr/0016-action-execution-orchestrator.md)).

```text
                    evento publicado durante `jarvis run`
                                   │
                      ┌────────────┴────────────┐
                      ▼                          ▼
              TriggerEngine (7.1)         ConditionEngine (7.6)
              "vale raciocinar?"          "regra determinística casa?"
                      │                          │
                      ▼                          │
              Agent Runtime (Fase 4)              │
                      │                          │
                      ▼                          │
              Decision Log (7.4)                  │
                      │                          │
                      ▼                          │
          NotificationManager (7.3)               │
       (InterruptionPolicy, 7.2, decide            │
        se interrompe agora)                       │
                      │                          │
                      └────────────┬─────────────┘
                                   ▼
                          ActionExecutor (Fase 5)
                       Policy → Skill → Tool Router
```

Autonomia real é opt-in em três interruptores independentes — ver
[ADR-0029](adr/0029-proactivity-opt-in-layers.md):

| Interruptor | Default | Controla |
|---|---|---|
| `JARVIS_PROACTIVITY_ENABLED` | `false` | Se o Trigger Engine/Conditional Trigger são sequer inscritos no bus de `jarvis run`. |
| `JARVIS_PROACTIVITY_TRIGGER_EVENT_TYPES` / `JARVIS_PROACTIVITY_RULES_PATH` | vazio | Allowlist de tipos de evento (7.1) e arquivo de regras (7.6) — vazio nega tudo. |
| `JARVIS_PROACTIVITY_EXECUTE_ACTIONS` | `false` | Se uma proposta de ação chega a `ActionExecutor.submit`. Exigido pelo caminho condicional mesmo com os outros dois ligados — uma `ConditionalRule` não tem modo "só avisar". |

Sem os três, `jarvis run` se comporta exatamente como antes da Fase 7.

## `jarvis.proactivity` (7.1, 7.2, 7.6)

- **`TriggerEngine`/`TriggerRule`** (`triggers.py`) — casa `RecordedEvent`
  contra uma allowlist de `event_type`. Não decide o que fazer com o
  casamento: `TriggerEventConsumer` (um `EventConsumer`) delega a um
  callback injetado pelo composition root.
- **`InterruptionPolicy`** (`interruption.py`) — decide **quando** algo já
  considerado importante deve interromper agora: reaproveita o `total` do
  `ImportanceAssessment` da Fase 4 (por valor, não por tipo — este pacote
  nunca importa `jarvis.agent`), e acrescenta conversa ativa, janela de
  silêncio configurável e cooldown por assunto. Localização é considerada e
  registrada como neutra — o Location Provider não existe (decisão da 2.2).
- **`ConditionEngine`/`ConditionalRule`/`Condition`** (`conditions.py`) —
  linguagem de condição fechada (seis operadores: `always`,
  `context_equals`, `context_present`, `payload_equals`, `and`, `or`,
  `not`), sem `eval`. Produz uma `ActionRequest(actor=Actor.SYSTEM)`
  diretamente — **sem LLM**. `adapters/rules_config.py` carrega regras de um
  JSON (formato documentado no próprio módulo); arquivo ausente é "nenhuma
  regra", não erro.

## `jarvis.notify` (7.3)

`Notification` (subject/title/body/priority) → `NotificationManager.notify`
aplica `InterruptionPolicy` e entrega por um `NotificationChannel`, em
ordem de preferência, com fallback em `REFUSED`:

- **`ConsoleNotificationChannel`** — o canal "desktop" desta fase é uma
  linha estruturada em stdout/stderr, não um toast nativo do SO — decisão
  registrada em [ADR-0028](adr/0028-console-channel-for-desktop-notifications.md).
- **`VoiceNotificationChannel`** — fala via `TextToSpeech`/`AudioSink` já
  existentes (Fase 6), só quando `can_speak_now()` diz que o Jarvis está
  ocioso (`VoiceState.IDLE`); caso contrário recusa e o console assume.

`silent_mode` suprime tudo abaixo de `URGENT`. O histórico de notificações
entregues (não as suprimidas) alimenta o cooldown da `InterruptionPolicy`.

**Fora de escopo desta fase:** o fluxo de confirmação de ações (5.9/5.10)
não foi retrofitado para passar pelo `NotificationManager`, mesmo o
contrato §3.10 mencionando esse uso — decisão registrada, não lacuna
silenciosa (ver `architecture-contracts.md §3.10`).

## `jarvis.decisions` (7.4)

Generaliza o padrão de auditoria como eventos da Fase 5
([ADR-0017](adr/0017-audit-trail-as-events.md)) para decisões do agente:
`decision_event(...)` constrói um `Event` (`agent.decision_recorded`) a
partir de **primitivos** — nunca de `Decision`/`AgentTurn`
([ADR-0026](adr/0026-decision-log-as-events-built-from-primitives.md)), o
que mantém `jarvis.decisions` sem depender de `jarvis.agent`. O composition
root publica o evento logo após todo `AgentRuntime.handle()` (`agent
ask`/`chat`/`react`, e a voz). `project_decisions` é a projeção pura de
volta a `DecisionRecord`.

`jarvis decisions list [--correlation-id ID] [--limit N]` consulta a
trilha; como `ActionRequest.correlation_id` é sempre
`decision.correlation_id`, a mesma correlação já liga decisão e execução
sem duplicar auditoria. O painel (`ObservabilityService`) passa a incluir
histórico persistido em `DecisionCard`, além do turno em curso.

## `jarvis.tasks` (7.5)

`BackgroundTask` envolve uma `ActionRequest` com estado
(`pending`/`running`/`retrying`/`succeeded`/`failed`/`cancelled`).
`TaskManager.run_due` aciona `ActionExecutor` (via o port estreito
`ActionSubmitter`, para testar sem montar Policy/Skills/Tools de verdade) e
decide o desfecho: `COMPLETED` → `succeeded`; negação de política ou
confirmação pendente → `failed` direto (não é transitório); qualquer outra
falha → retry com backoff exponencial até `max_attempts`, depois `failed`.

**Nenhuma thread/timer novo** — `run_due` é ticado de pontos que já existem
(`jarvis tasks run-due`, início de `jarvis run`, cada ciclo de
`PanelBridge.refresh()`, sobre um `ActionExecutor` construído uma única vez
por sessão) — ver [ADR-0027](adr/0027-background-tasks-ticked-not-scheduled.md).

`jarvis tasks list|show <id>|cancel <id>|run-due`.

## Bancos de dados

Sexto banco: `data/tasks.db` (`SqliteTaskRepository`), mesmo critério dos
anteriores — um componente, um schema, um `user_version`. `jarvis.notify` e
`jarvis.proactivity` não persistem nada por conta própria: histórico de
notificação e regras carregadas vivem em memória, pelo tempo de vida do
processo residente.

## Limitação conhecida: escopo de reação

O `EventBus` é síncrono e em processo
([ADR-0008](adr/0008-synchronous-in-process-event-bus.md)). O Trigger
Engine e o Conditional Trigger só veem eventos publicados **dentro do
mesmo processo `jarvis run`** — hoje, isso cobre sessões de voz, decisões e
confirmações. Um `jarvis events emit` rodado em outro terminal grava no
Event Store (visível depois via `jarvis events list`/`agent react`), mas
**não** aciona reação em tempo real num `jarvis run` já de pé: não existe
poller entre processos nesta fase, e não deveria existir sem necessidade
concreta (`architecture-contracts.md §1`). Fontes externas de eventos
(email, calendário) continuam fora de escopo desta fase — ver
`docs/phase-7-plan.md`.

## Comandos de CLI novos

```text
jarvis decisions list [--correlation-id ID] [--limit N]
jarvis tasks list
jarvis tasks show <task_id>
jarvis tasks cancel <task_id>
jarvis tasks run-due
```

`jarvis info` mostra o estado efetivo de proatividade e notificação
(`enabled`, contagem de triggers, `execute`, `rules`, `silent`).
