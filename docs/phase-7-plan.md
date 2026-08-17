# Fase 7 — Proactivity + Autonomy: plano de implementação

> Cobre o que `ROADMAP.md` define para a Fase 7 (§7.1–7.7). O
> `phase-7-development-guide.md` anexado à sessão que originou este plano
> descreve um escopo diferente ("External Integrations" — Todoist/Calendar/
> Gmail); a divergência foi sinalizada ao usuário na sessão e a resposta foi
> seguir `ROADMAP.md`. Este plano **não** implementa nenhuma integração
> externa: `ROADMAP.md` continua sendo a fonte oficial da subfase, como
> `CLAUDE.md §0.1` exige.

**Objetivo da fase:** permitir que o agente avalie eventos autonomamente e
decida quando agir ou interromper o usuário, sem introduzir nenhuma
capacidade cognitiva nova (o raciocínio continua sendo o Agent Runtime da
Fase 4) e sem reabrir a cadeia de execução (a Fase 7 **aciona**
`ActionExecutor`; não a reimplementa — ver
[ADR-0016](adr/0016-action-execution-orchestrator.md), que já nomeia
explicitamente Trigger Engine (7.1) e Background Tasks (7.5) como futuros
chamadores).

## 0. Leitura prévia e princípio geral

Toda subfase desta fase segue o mesmo princípio: **autonomia é opt-in em
cada camada**, nunca um comportamento novo ligado por default.
`jarvis run` hoje não reage a evento nenhum sozinho; depois da Fase 7,
continua não reagindo, a menos que `JARVIS_PROACTIVITY_ENABLED=true` **e**
uma allowlist de tipos de evento tenha sido configurada explicitamente —
mesma disciplina de `wake_strategy=push_to_talk` (custo zero por default) e
`voice_execute_actions=false` (executar é sempre opt-in). Isso não é
timidez: é a mesma regra que already protege `policy_granted_capabilities`
(allowlist vazia nega tudo) aplicada a "o Jarvis pode agir sem eu pedir".

## 1. Componentes novos

Cinco pacotes novos em `src/jarvis/`, cada um seguindo o padrão já
estabelecido (Core na raiz do pacote, `adapters/` só quando há I/O real):

| Pacote | Subfases | Responsabilidade |
|---|---|---|
| `jarvis/proactivity/` | 7.1, 7.2, 7.6 | Decide **se** e **quando** um evento merece virar raciocínio ou automação — nunca executa nada sozinho. |
| `jarvis/notify/` | 7.3 | Entrega uma `Notification` já formada por um canal (console/"desktop", voz, silencioso), com prioridade e histórico de deduplicação. |
| `jarvis/decisions/` | 7.4 | Modela e projeta a trilha consultável de decisões do agente, como eventos — mesmo padrão do audit trail da Fase 5 (ADR-0017). |
| `jarvis/tasks/` | 7.5 | Modela execuções adiadas/repetíveis de uma `ActionRequest`, com estado, retry e cancelamento — sem thread nova (ADR-0023 continua valendo). |
| (extensão) `cli.py` | 7.7 | Composition root ganha os `build_*` e os `EventConsumer` de ligação — mesmo papel que já cumpre para Voice/Panel. |

Nenhum desses pacotes vira uma capacidade cognitiva nova: `jarvis.proactivity`
não chama LLM (Trigger Engine decide "vale acionar o Agent Runtime?", não
"o que fazer" — isso continua sendo só do Agent Runtime); `jarvis.notify` não
decide o conteúdo da mensagem, só a entrega.

### 1.1 Grafo de dependências (regra a testar)

```text
proactivity   →  jarvis.errors, jarvis.context.model, jarvis.execution.model (ActionRequest/Actor), jarvis.events.event
notify        →  jarvis.errors, jarvis.proactivity (InterruptionPolicy/InterruptionDecision)
decisions     →  jarvis.errors, jarvis.events.event
tasks         →  jarvis.errors, jarvis.execution (ActionRequest, ActionExecutor, ExecutionOutcome)
```

Nenhum dos quatro depende de `jarvis.agent`: exatamente como
`jarvis.execution` não conhece `jarvis.agent` (ADR-0003/teste
`test_the_earlier_components_do_not_know_the_action_layer`), os pacotes da
Fase 7 recebem dados já extraídos (primitivos, não `Decision`/`AgentTurn`)
de quem os chama — o composition root. Isso mantém a regra "o Agent Runtime
nunca é chamado por baixo" simétrica também na direção contrária: nada na
Fase 7 pode chamar o Agent Runtime por conta própria a não ser através do
callback que o composition root injeta.

## 2. Subfases

### 7.1 — Trigger Engine

**Entrega:** `jarvis/proactivity/triggers.py`.

- `TriggerRule` — `trigger_id`, `event_types: frozenset[str]`, `enabled`.
  Casamento por tipo de evento apenas — a granularidade fina (vale a pena
  chamar o LLM?) continua sendo o Importance Engine (4.4), que já existe e
  já é aplicado dentro de `AgentRuntime.handle()`. O Trigger Engine responde
  uma pergunta anterior e mais grosseira: "este tipo de evento é candidato a
  *sequer* ser considerado, neste Jarvis, agora?" — a allowlist vazia
  (default) nunca casa com nada.
- `TriggerEngine.match(event: RecordedEvent) -> TriggerRule | None`.
- `TriggerEventConsumer` — implementa o protocolo `EventConsumer` (mesma
  forma de `MemoryEventConsumer`/`ActionEventConsumer`), recebe um
  `on_match: Callable[[RecordedEvent, TriggerRule], None]` injetado. Não
  conhece `AgentRuntime`; só decide *que* algo bateu e delega.
- **Testes:** casamento de tipo, allowlist vazia não casa nada,
  `enabled=False` não casa, consumer entrega ao callback exatamente o
  evento e a regra, consumer ignora evento sem trigger sem levantar.

**Sem adapter nesta subfase** — configuração da allowlist chega como texto
(`JARVIS_PROACTIVITY_TRIGGER_EVENT_TYPES`), convertida pelo composition
root, mesmo padrão de `parse_capabilities`.

### 7.2 — Interruption Policy

**Entrega:** `jarvis/proactivity/interruption.py`.

- Reaproveita `ImportanceAssessment` da Fase 4 (`agent/importance.py`) em vez
  de recalcular urgência/relevância/custo — o roadmap pede "considerar
  importância", e importância já é uma grandeza modelada; duplicá-la seria a
  abstração especulativa que o contrato §1 proíbe.
- `InterruptionDecision` — `should_interrupt: bool`, `reason: str`,
  `suppressed_by: str | None` (motivo da supressão, quando houver).
- `InterruptionPolicy.evaluate(*, assessment, context, recent: tuple[SentNotification, ...], now) -> InterruptionDecision`
  considera, além de `assessment.total` vs. limiar:
  - **conversa atual** — `context.conversation.active_id` fresco suprime
    (não empilhar uma notificação sobre uma conversa por voz em andamento);
  - **horário** — janela configurável de silêncio (`quiet_hours_start/end`,
    hora local derivada de `context.environment.utc_offset`; sem
    `utc_offset` observado, a janela não se aplica — ausência não vira
    suposição, mesma regra do contrato de contexto §6);
  - **notificações recentes** — deduplicação por `(subject, cooldown)`
    contra o histórico que `NotificationManager` mantém e passa como
    parâmetro (Interruption Policy não guarda estado próprio — é função
    pura sobre o que recebe, testável sem relógio real nem I/O);
  - **localização** — contracts já documentam a ausência do Location
    Provider desde a subfase 2.2 (não implementado, por decisão da Fase 2).
    A política trata a ausência de localização como neutra e registra isso
    explicitamente no motivo, em vez de fingir que considerou algo que o
    sistema não sabe.
- **Testes:** cada consideração isoladamente (conversa ativa suprime, hora
  silenciosa suprime, cooldown suprime repetição do mesmo assunto,
  importância abaixo do limiar suprime), e o caso feliz (nada suprime,
  `should_interrupt=True`).

### 7.3 — Notification Manager

**Entrega:** `jarvis/notify/` (`notification.py`, `ports.py`, `manager.py`,
`errors.py`, `adapters/console.py`, `adapters/voice.py`).

- `Notification` — `notification_id`, `title`, `body`, `priority`
  (`NotificationPriority`: `LOW`/`NORMAL`/`HIGH`/`URGENT`), `correlation_id`,
  `created_at`.
- `NotificationChannel` (Protocol) — `send(notification) -> DeliveryResult`.
- `NotificationManager.notify(notification, *, assessment, context) -> DeliveryOutcome`:
  aplica `InterruptionPolicy` (7.2); se suprimido, registra e não entrega
  (silêncio é decisão, não falha — mesmo vocabulário da Fase 4); se
  liberado, escolhe canal (voz se há sessão "pode falar agora"; senão
  console) e entrega; sempre atualiza o histórico usado por 7.2.
- `silent_mode: bool` (de `Settings`) força supressão total, exceto
  `URGENT` — ainda registrado no histórico, nunca perdido silenciosamente.
- **Canais:**
  - `ConsoleNotificationChannel` (Infrastructure) — grava uma linha
    estruturada em stdout/stderr. Ver §4 (decisão sobre por que "desktop" é
    isto e não um toast nativo do SO nesta fase).
  - `VoiceNotificationChannel` (Infrastructure) — usa os ports já
    existentes de `jarvis.voice` (`TextToSpeech`/`AudioSink`); só tenta
    falar quando recebe `can_speak_now() -> bool` (injetado pelo
    composition root a partir do estado real do `VoiceLoop`) igual a
    `True`; caso contrário recusa e quem chama cai para o console. Não abre
    dispositivo de áudio por conta própria — recebe o `AudioSink` já
    aberto pelo composition root, mesma disciplina de `RuntimeConversationalAgent`.
- Publicação de evento (`notification.sent`/`notification.suppressed`)
  **não** é responsabilidade de `jarvis.notify` (contracts §3.10 não lista
  Event System entre as dependências permitidas) — o composition root
  publica, mesmo padrão de `voice_session_event`.
- **Testes:** supressão por política, silent mode, escolha de canal,
  fallback voz→console quando `can_speak_now()` é `False`, histórico
  atualizado em ambos os desfechos.

**Decisão explícita de escopo:** o fluxo de confirmação de ações (5.9/5.10)
**não** é retrofitado para passar pelo `NotificationManager` nesta subfase,
mesmo o contrato §3.10 mencionando esse uso. Motivo: o fluxo atual
(CLI/voz perguntando e recebendo resposta como evento, ADR-0014) já
funciona, é testado, e religá-lo introduziria risco de regressão em Fase 5
sem necessidade concreta desta fase — critério do `ROADMAP.md` regra 11.
Fica registrado como trabalho futuro, não como dívida oculta.

### 7.4 — Decision Logging

**Entrega:** `jarvis/decisions/` (`record.py`, `events.py`, `query.py`,
`errors.py`).

- `DecisionRecord` — dado plano: `decision_id`, `decision_type`, `reason`,
  `message` (truncada), `decided_at`, `correlation_id`, `causation_id`,
  `consulted_llm`, `importance`, `used_memory_ids`, `context_as_of`,
  `action_skill`. Sem parâmetros de ação e sem conteúdo de memória — mesma
  disciplina de privacidade do `AuditEntry` (ADR-0017): a trilha prova
  *que* decisão foi tomada e *com que* insumos, não repete o conteúdo deles.
- `decision_event(...)` — constrói um `Event` (`agent.decision_recorded`)
  a partir de **argumentos primitivos**, não de `Decision`/`AgentTurn`: é
  essa escolha que mantém `jarvis.decisions` sem depender de `jarvis.agent`
  (ver ADR novo, §5). `event_id` determinístico a partir de `decision_id`
  (reapresentar o mesmo turno é no-op, mesmo padrão de `execution/events.py`).
- `project_decisions(events: Sequence[RecordedEvent]) -> tuple[DecisionRecord, ...]`
  — filtra pelo tipo, valida `schema_version`, traduz de volta. Função pura,
  testável sem Event Store real.
- **Quem publica:** o composition root, logo após `AgentRuntime.handle()`
  retornar um `AgentTurn`, em `_agent_ask`/`_agent_chat`/`_agent_react` e em
  `RuntimeConversationalAgent.respond` — mesmo ponto onde hoje só se
  imprime/fala a decisão. "Registrar ações" (item do roadmap) não duplica a
  trilha de auditoria da Fase 5: como `ActionRequest.correlation_id` é
  sempre `decision.correlation_id`, `jarvis decisions show <correlation_id>`
  já mostra decisão **e** execução juntas, sem escrever a ligação duas vezes.
- **CLI:** `jarvis decisions list [--correlation-id ID] [--limit N]`.
- **Painel:** `ObservabilityService._decision_cards` passa a também ler
  `agent.decision_recorded` do event store (via `read_events`, já injetado),
  preenchendo o histórico que `DecisionCard`/ADR-0024 deixou como pendência
  explícita ("`DecisionCard` já tem a forma que a 7.4 vai preencher").
- **Testes:** construção/leitura do evento (roundtrip), projeção filtrando
  tipo e schema, truncamento de mensagem, integração do painel com um
  event store fake.

### 7.5 — Background Task Manager

**Entrega:** `jarvis/tasks/` (`model.py`, `ports.py`, `manager.py`,
`errors.py`, `adapters/sqlite_tasks.py`).

- `BackgroundTask` — `task_id`, `request: ActionRequest` (serializado),
  `status` (`TaskStatus`: `PENDING`/`RUNNING`/`RETRYING`/`SUCCEEDED`/
  `FAILED`/`CANCELLED`), `attempts`, `max_attempts`, `next_attempt_at`,
  `created_at`, `updated_at`, `last_error`.
- `TaskRepository` (Protocol) — `put`/`get`/`list_by_status`/`mark` —
  mesmo desenho de `ActionRepository` (sem `update` genérico).
- `TaskManager`:
  - `submit(request: ActionRequest, *, max_attempts, delay) -> BackgroundTask`
    — enfileira, não executa na hora (é isso que distingue de
    `ActionExecutor.submit` direto: a tarefa existe para ser executada
    **depois**, possivelmente mais de uma vez).
  - `cancel(task_id) -> BackgroundTask` — só de tarefas não terminais.
  - `run_due(*, executor: ActionExecutor, now) -> Sequence[BackgroundTask]`
    — para cada tarefa `PENDING`/`RETRYING` com `next_attempt_at <= now`,
    chama `executor.submit(task.request)`; `COMPLETED`→`SUCCEEDED`,
    `DENIED`/`REJECTED`→`FAILED` (política negou; repetir não muda o
    resultado sem intervenção humana), falha de infraestrutura ou
    `FAILED` de execução → `RETRYING` com backoff, até `max_attempts`,
    depois `FAILED` terminal.
- **Concorrência:** nenhuma thread nova. `run_due` é **ticado**, nunca
  agendado — mesmo padrão que `ActionExecutor.expire()` já usa hoje (chamado
  explicitamente por `jarvis action pending`, não por um timer). Ver ADR
  novo em §5. Pontos de tick: `jarvis tasks run-due` (comando explícito),
  início de `_run_resident`, e cada ciclo de `PanelBridge.refresh()`.
- **Testes:** submit não executa na hora, `run_due` executa o que está
  devido e ignora o que não está, retry com backoff até o teto, depois
  `FAILED` terminal, `DENIED` vira `FAILED` sem novas tentativas,
  cancelamento de tarefa pendente, adapter SQLite (roundtrip, imutabilidade
  do `request`).

### 7.6 — Conditional Triggers

**Entrega:** `jarvis/proactivity/conditions.py` +
`jarvis/proactivity/adapters/rules_config.py`.

- `Condition` — árvore pequena e fechada, **sem `eval`**: `always`,
  `context_equals(field, value)`, `context_present(field)`,
  `payload_equals(key, value)`, `and_(...)`, `or_(...)`, `not_(...)`. Nunca
  código arbitrário — regras vêm de um arquivo de configuração, e um
  arquivo de configuração que executasse código seria uma porta para
  execução arbitrária disfarçada de dado.
- `ConditionalRule` — `rule_id`, `when: frozenset[str]` (tipos de evento),
  `condition: Condition`, `then: ActionTemplate` (skill + parâmetros, com
  placeholders `"$event.<chave>"` resolvidos contra o payload do evento no
  momento da avaliação).
- `ConditionEngine.evaluate(event, *, context) -> ActionRequest | None` —
  produz `ActionRequest(actor=Actor.SYSTEM, ...)`: `Actor.SYSTEM` já existe
  em `execution/model.py` e é exatamente o ator certo aqui — não foi o
  usuário nem um evento avaliado pelo LLM, foi uma regra determinística.
- `ConditionalTriggerConsumer` — mesmo desenho de `TriggerEventConsumer`:
  implementa `EventConsumer`, chama um `on_action: Callable[[ActionRequest], None]`
  injetado (o composition root chama `ActionExecutor.submit`). **Sem LLM
  nesta trilha** — é automação determinística, distinta do caminho 7.1
  (evento → Agent Runtime → `Decision`).
- `load_conditional_rules(path: Path) -> tuple[ConditionalRule, ...]` —
  adapter que lê um JSON, mesmo padrão de `tools/adapters/mcp_config.py`.
  Ausência do arquivo = nenhuma regra (não é erro).
- **Testes:** cada operador de `Condition` isoladamente, resolução de
  placeholder, regra que não casa o tipo não avalia a condição, adapter de
  config (roundtrip, arquivo ausente, JSON malformado).

### 7.7 — Proactivity Integration

**Entrega:** extensões em `cli.py` e `config.py`; sem pacote novo.

- `Settings`: `proactivity_enabled`, `proactivity_trigger_event_types`,
  `proactivity_importance_threshold`, `proactivity_execute_actions`,
  `proactivity_quiet_hours_start/end`, `proactivity_notification_cooldown_seconds`,
  `proactivity_rules_path`, `notify_silent_mode`, `tasks_max_attempts`,
  `tasks_retry_base_delay_seconds` — todos com default seguro (desligado /
  restritivo), mesma disciplina de `voice_execute_actions`.
- `cli.py` ganha:
  - `build_trigger_engine`, `build_interruption_policy`,
    `build_notification_manager`, `build_condition_engine`,
    `build_task_manager` (todos puros/injetados, mesmo padrão de
    `build_policy_engine`);
  - `ProactiveEventConsumer`-equivalente: uma função de callback
    (`_on_trigger_matched`) que reproduz exatamente o corpo de
    `_agent_react`, adaptado para não imprimir em stdout e sim notificar
    via `NotificationManager` e (se `proactivity_execute_actions`) submeter
    via `ActionExecutor` com `Actor.EVENT` — reaproveitando
    `_submit_proposal`/`_persist_memory_proposal`/`decision_event` que já
    existem;
  - wiring em `_run_resident`: assina `TriggerEventConsumer` e
    `ConditionalTriggerConsumer` no bus só quando `proactivity_enabled` e
    houver ao menos um trigger/regra configurado; tica `TaskManager.run_due`
    no início e a cada `PanelBridge.refresh()`.
  - `jarvis tasks list|show|cancel|run-due` e `jarvis decisions list` como
    novos subcomandos.
- **Testes:** um teste de integração de ponta a ponta (evento → trigger →
  Agent Runtime fake → decisão → notificação →, se configurado, ação via
  `ActionExecutor` fake) cobrindo "comportamento proativo completo" —
  exigência literal do roadmap 7.7 — mais os testes de
  `_run_resident`/`build_*` que já existem para as fases anteriores
  (`test_cli.py`, `test_cli_action.py`, `test_cli_voice.py`), estendidos
  para cobrir os novos comandos.

## 3. Dependências entre subfases

```text
7.1 Trigger Engine ──┐
                     ├──► 7.7 Proactivity Integration
7.2 Interruption ────┤
Policy               │
                     │
7.3 Notification ────┤     (depende de 7.2)
Manager              │
                     │
7.4 Decision Logging ┤     (independente das demais; só precisa de AgentTurn)
                     │
7.5 Background Task ─┤     (depende só de jarvis.execution, já existente)
Manager              │
                     │
7.6 Conditional ─────┘     (independente de 7.1–7.5; usa ActionExecutor direto)
Triggers
```

Ordem de implementação: **7.1 → 7.2 → 7.3 → 7.4 → 7.5 → 7.6 → 7.7**, seguindo
a numeração do roadmap. 7.4 e 7.5 não têm dependência real de 7.1–7.3 e
poderiam ser feitas em paralelo; a ordem linear é mantida por disciplina de
commit (`ROADMAP.md` regra 5 — uma sessão por subfase; aqui, uma sessão
cobre a fase inteira, mas os commits continuam granulares por subfase).

## 4. Riscos e decisões de escopo

| Risco | Mitigação |
|---|---|
| "Desktop notification" sem dependência nova nem risco de injeção de comando | Canal "desktop" é console/log estruturado nesta fase, não um toast nativo do SO. Documentado como decisão explícita (ADR novo), não como lacuna. Native toast fica disponível como adapter futuro atrás do mesmo `NotificationChannel`. |
| Nova concorrência quebrando ADR-0008/ADR-0023 (bus síncrono, processo único) | Nenhuma thread nova. Background Task Manager é ticado em pontos existentes do loop síncrono, nunca por timer. |
| Autonomia real (executar sem humano no laço) sendo perigosa por default | Três interruptores independentes, todos default-off: `proactivity_enabled`, allowlist de triggers vazia, `proactivity_execute_actions`. Sem os três, `jarvis run` se comporta exatamente como antes da Fase 7. |
| Regras condicionais como vetor de execução arbitrária | Linguagem de condição fechada (6 operadores, sem `eval`, sem acesso a atributo livre) — impossível expressar código, só predicados de dado. |
| Duplicar a trilha de auditoria da Fase 5 dentro do Decision Log | Decision Log não repete o que a auditoria já registra; a ligação é `correlation_id`, já existente. |
| `jarvis.decisions`/`jarvis.notify` vazando por acidente para dentro de `jarvis.agent` (violando ADR-0003) | Builders recebem primitivos, não `Decision`/`AgentTurn` — dependência estrutural impossível, verificada por teste de arquitetura por pacote (mesmo padrão de `test_action_architecture.py`). |
| Regressão nos fluxos de confirmação/execução já testados (Fase 5/6) | Nenhum arquivo de Fase 5/6 é alterado além de `cli.py` (extensão aditiva) e `interface/service.py` (leitura adicional de decisões, aditiva). Suíte completa roda ao final de cada subfase. |

## 5. ADRs previstos

Registrados apenas onde há decisão genuinamente nova e difícil de reverter
(critério de `docs/adr/README.md`), não uma por subfase:

1. **Decision log como eventos, construído a partir de primitivos** —
   generaliza ADR-0017 para um componente novo, e fixa a escolha de não
   acoplar `jarvis.decisions` a `jarvis.agent`.
2. **Background tasks ticadas de pontos existentes, sem thread/timer novo**
   — extensão direta de ADR-0008/ADR-0023, registrada porque "por que não
   um scheduler" é a pergunta óbvia que um leitor futuro vai fazer.
3. **Notificação "desktop" como canal console/log nesta fase** — decisão de
   escopo com alternativa descartada explícita (toast nativo via
   subprocess/PowerShell), registrando o motivo (risco de injeção,
   dependência de plataforma, ausência de necessidade concreta hoje).
4. **Autonomia em três interruptores independentes, e triggers condicionais
   sem LLM** — a decisão mais importante da fase: como a Fase 7 introduz a
   capacidade real de o sistema agir sem um humano pedir, o desenho de
   segurança (opt-in em camadas + automação determinística separada do
   caminho de raciocínio) merece registro formal, não só o parágrafo do
   roadmap.

Números exatos (`ADR-0026`–`ADR-0029`) atribuídos na implementação, depois
de confirmar que nenhum outro ADR foi criado em paralelo.

## 6. Componentes reutilizados (não recriados)

- `ActionExecutor` (Fase 5) — único caminho até uma Skill, para 7.1 e 7.6.
- `ImportanceAssessment`/`assess()` (Fase 4) — reaproveitado inteiro por
  7.2, não recalculado.
- `EventBus`/`EventConsumer` (Fase 1) — 7.1 e 7.6 são só mais dois
  consumers, mesmo padrão de `MemoryEventConsumer`/`ActionEventConsumer`.
- `AuditEntry`/`AuditKind` (Fase 5) — modelo de "marco auditável" citado
  como referência de desenho para `DecisionRecord`, sem reuso de código
  (categorias diferentes: uma é sobre execução, outra sobre decisão).
- `Settings`/`load_settings()` (Fase 0) — só cresce com os campos novos,
  mesmo mecanismo.
- `PanelBridge`/`ObservabilityService` (Fase 6) — ganha leitura adicional
  (decisões), não uma reescrita.
- Ports de voz (`TextToSpeech`, `AudioSink`) (Fase 6) — reaproveitados pelo
  `VoiceNotificationChannel`, sem nenhuma mudança em `jarvis.voice`.

## 7. Commits previstos

Um commit por subfase, seguindo os títulos já reservados no `ROADMAP.md`:

```text
feat: implement event trigger engine            (7.1)
feat: implement interruption policy              (7.2)
feat: implement notification manager             (7.3)
feat: implement agent decision logging           (7.4)
feat: implement background task manager          (7.5)
feat: implement conditional triggers             (7.6)
feat: enable proactive agent behavior             (7.7)
```

ADRs e atualização de `docs/architecture-contracts.md` entram no commit da
subfase que os motivou (7.1 para o ADR de autonomia/opt-in se antecipado, ou
7.7 se só ficar claro no fechamento — decisão tomada durante a
implementação). `ROADMAP.md` é atualizado ao final de cada subfase, nunca
em lote no fim.

## 8. Critérios de conclusão (por subfase e da fase)

Por subfase, os mesmos da regra de conclusão do `ROADMAP.md`: implementação
completa, testes relevantes passando, documentação necessária atualizada,
arquitetura preservada (testes de arquitetura do pacote novo, verificados
por AST como os já existentes), nenhum problema crítico conhecido, commit
criado, checkbox marcado.

Da fase inteira (`ROADMAP.md` §"Proactivity completa"): as sete subfases
concluídas, `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`
e `uv run mypy` verdes, `uv run jarvis` continua funcionando sem
`JARVIS_PROACTIVITY_ENABLED`, e com ele ligado um evento configurado como
trigger efetivamente produz uma decisão, uma notificação e (se
`proactivity_execute_actions`) uma execução — testado de ponta a ponta em
7.7.
