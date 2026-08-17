# 0027. Background tasks são ticadas de pontos existentes, nunca agendadas

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A subfase 7.5 do [roadmap](../../ROADMAP.md) pede "executar tarefas em
background", com retry e cancelamento. "Background" sugere um agendador — uma
thread ou timer que acorda sozinho e roda o que está devido.

O Jarvis já respondeu uma pergunta parecida duas vezes:
[ADR-0008](0008-synchronous-in-process-event-bus.md) manteve o Event Bus
síncrono e em processo porque o sistema tem um usuário e uma conversa por
vez; [ADR-0023](0023-single-resident-process.md) fixou exatamente quatro
threads em `jarvis run`, cada uma com um papel nomeado, e nenhuma delas é "um
scheduler genérico". Introduzir um timer novo para tarefas em background
reverteria os dois na prática, sem que a subfase 7.5 exija isso — o
comportamento pedido ("retry", "cancelamento", "estados de tarefa") não
depende de *quando* a checagem acontece, só de que ela aconteça.

Aliás, o próprio `ActionExecutor` já resolveu o problema irmão
(`expire()`, que marca confirmações vencidas) sem timer nenhum: é chamado
explicitamente sempre que `jarvis action pending` roda.

## Decisão

`TaskManager.run_due(*, executor, moment=None)` é **ticado**: quem decide
quando chamá-lo é sempre um ponto que já existe no sistema, nunca um relógio
próprio do `TaskManager`. Três pontos, nesta fase:

1. `jarvis tasks run-due` — tick explícito, mesmo padrão de `action pending`;
2. o início de `_run_resident` (`jarvis run`) — drena o que ficou pendente
   entre execuções do processo;
3. cada ciclo de `PanelBridge.refresh()` — que já roda periodicamente
   (`JARVIS_PANEL_REFRESH_SECONDS`) tanto no modo só-painel quanto durante uma
   conversa por voz, sem que `jarvis.tasks` precise saber disso.

Nenhuma thread nova, nenhum `sched`/`asyncio`, nenhum polling próprio dentro
de `jarvis.tasks` — o pacote nem importa `threading` (verificado por teste
arquitetural).

## Alternativas consideradas

- **Uma quinta thread daemon, com `time.sleep` num loop**: funcionaria, e
  reabriria exatamente a pergunta que o ADR-0023 fechou ("quantas threads
  tocam SQLite"). `TaskManager.run_due` chama `ActionExecutor.submit`, que
  grava no banco de ações — uma thread própria de tarefas seria uma segunda
  thread a escrever, quebrando a garantia de "só a thread principal toca
  SQLite".
- **`asyncio`**: reverteria o ADR-0008 sem que nada nesta subfase precise de
  concorrência real — o sistema continua com um usuário e uma conversa por
  vez.
- **Um scheduler de SO (cron/Agendador de Tarefas do Windows) chamando
  `jarvis tasks run-due`**: viável e nada impede o usuário de configurar
  isso por conta própria; o Jarvis não assume esse papel porque ainda não é
  "um daemon de verdade" (mesma fronteira que o ADR-0023 já traçou).

## Consequências

- `run_due` é determinístico e testável sem `time.sleep`: os testes de
  `TaskManager` passam `moment=` explicitamente, do mesmo jeito que os testes
  de `ActionExecutor.expire()` já fazem.
- Uma tarefa agendada com um atraso maior que o intervalo entre dois ticks
  (ex. `delay_seconds` grande, painel fechado, ninguém rodou `jarvis run`)
  simplesmente espera até o próximo tick — não há garantia de latência, e o
  roadmap não pede uma.
- **Custo aceito:** sem `jarvis run` nem `jarvis tasks run-due` rodando, uma
  tarefa retryable fica parada indefinidamente em `retrying`/`pending`. Isso é
  o comportamento correto para um processo que só existe enquanto alguém o
  mantém de pé — o mesmo custo que confirmações pendentes já aceitam
  (ADR-0014) e Ctrl-C já aceita (ADR-0023).
- **Gatilho para revisitar:** se o Jarvis vier a rodar como serviço do SO de
  verdade (fora do escopo desta fase e do ADR-0023), um scheduler interno
  passa a fazer sentido — e `run_due` já tem a forma que ele chamaria.
