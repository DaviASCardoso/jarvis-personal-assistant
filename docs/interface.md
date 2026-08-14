# Painel de observabilidade

> **Documentação de implementação**: descreve o que existe em
> `src/jarvis/interface/` desde a Fase 6. A decisão está no
> [ADR-0024](adr/0024-observability-panel-as-snapshot-reader.md); o modelo de
> processo, no [ADR-0023](adr/0023-single-resident-process.md).

---

## 1. O que o painel é

Uma janela para o estado interno do Jarvis — e **só uma janela**.

```text
Navegador
   │  GET /api/state · GET /api/stream (SSE)
   ▼
PanelServer  (adapters/http_panel.py)      Infrastructure
   │  lê
   ▼
LiveState    (live.py)                     Interface
   ▲  publish()
   │
ObservabilityService (service.py)          Interface
   │  funções de leitura injetadas
   ▼
Event Store · Context Engine · Memory · Action Repository   Core
```

`jarvis.interface` importa **apenas módulos de domínio** de outros componentes
(`events.event`, `context.model`, `memory.memory`, `execution.model`,
`voice.session`). Não conhece `jarvis.agent`, `jarvis.skills`, `jarvis.tools`,
`jarvis.policy`, o orquestrador de execução, nenhum `*.adapters`, `jarvis.config`
nem `sqlite3` — `tests/test_interface_architecture.py` verifica cada um.

---

## 2. Somente leitura

Não existe rota de escrita. `POST`, `PUT`, `DELETE` e `PATCH` respondem **405 em
qualquer caminho**, e um teste varre a AST para garantir que o único handler
implementado é `do_GET`.

Confirmar uma ação continua sendo assunto do CLI (`jarvis action confirm`) e da
voz. Um painel que executa seria um segundo caminho até uma Tool, sem o cuidado
que a Fase 5 construiu.

O bind é fixo em loopback: `JARVIS_PANEL_HOST` fora de
`127.0.0.1`/`localhost`/`::1` é recusado na construção. Expor na rede exigiria
autenticação, e autenticação é multiusuário — fora do escopo.

---

## 3. Os sete blocos

| bloco | view model | de onde vem |
|---|---|---|
| Conversa | `ConversationEntry` | `VoiceSession.turns` |
| Eventos | `TimelineEntry` | `EventStore.read_latest` |
| Contexto atual | `ContextRow` | `ContextEngine.current()` |
| Memórias | `MemoryCard` | as do turno (com score) + as últimas gravadas |
| Decisões | `DecisionCard` | turno em curso + turnos do assistente |
| Ações | `ActionCard` | trilha de auditoria agregada por `execution_id` + pendências |
| Ferramentas | `ToolCard` | `tool.execution_completed` / `_failed` |

As **ações** e as **ferramentas** vêm da trilha que a Fase 5 já publicava
([ADR-0017](adr/0017-audit-trail-as-events.md)) — o painel só a lê. Histórico
consultável de **decisões** é a subfase 7.4; até lá, `DecisionCard` é preenchido
pelo turno em memória e já tem a forma que a 7.4 vai usar.

---

## 4. O painel não tem estado

`PanelSnapshot` é reconstruído a cada refresh a partir das fontes de verdade. O
navegador guarda apenas o último `revision` recebido, para deduplicar toast.
Recarregar a página não perde nada; reiniciar o processo mostra o mesmo painel,
menos a sessão em curso.

Quando uma leitura falha, o bloco correspondente aparece em
`PanelSnapshot.degraded` e a tela **diz** que não conseguiu ler. Mostrar vazio
como se fosse ausência seria mentir sobre o estado do sistema — que é exatamente
o que o painel existe para não fazer.

---

## 5. Cadência

| trilha | gatilho | custo | atualiza |
|---|---|---|---|
| status | toda transição de estado da voz | nenhum I/O | `voice` |
| snapshot | a cada `JARVIS_PANEL_REFRESH_SECONDS` e ao fim do turno | 4 leituras | tudo |

A trilha de status existe porque, sem ela, o painel congelaria justamente quando
o Jarvis está esperando a nuvem — que é quando alguém olha para ele.

Toda leitura de banco acontece na **thread principal**. As threads do servidor só
leem o `LiveState`, que é um objeto imutável já montado. A regra de concorrência
cai da regra arquitetural, e não o contrário.

---

## 6. Contrato de `/api/state`

```json
{
  "revision": 42,
  "as_of": "2026-08-14T12:34:56.789+00:00",
  "voice": {"state": "speaking", "session_id": "…", "last_transcript": "…",
            "last_reply": "…", "detail": "", "at": "…"},
  "timeline": [{"event_id": "…", "event_type": "action.completed",
                "source": "jarvis-execution", "occurred_at": "…",
                "recorded_at": "…", "correlation_id": "…",
                "severity": "success", "summary": "action.completed skill=file.write"}],
  "context": [{"field": "utc_offset", "value": "-03:00", "source": "system-time",
               "observed_at": "…", "freshness": "fresh", "confidence": 1.0}],
  "memories": [{"memory_id": "…", "type": "preference", "content": "…",
                "subject": "…", "importance": 0.7, "confidence": 0.86,
                "origin": "user", "reference": "", "score": 0.71,
                "used_in_turn": true}],
  "decisions": [{"decision_type": "act_and_notify", "decided_at": "…",
                 "reason": "…", "message": "…", "correlation_id": "…",
                 "consulted_llm": true, "importance": 0.62, "memory_count": 3}],
  "actions": [{"execution_id": "…", "skill": "file.write", "status": "completed",
               "actor": "user", "verdict": "allow", "rule_id": "granted_capability",
               "reason": "", "duration_ms": 12.4, "tools_used": [],
               "correlation_id": "…", "at": "…"}],
  "tools": [{"tool_id": "local.fs.write", "backend_id": "local",
             "status": "completed", "duration_ms": 4.1,
             "execution_id": "…", "at": "…"}],
  "conversation": [{"role": "user", "text": "…", "at": "…",
                    "session_id": "…", "latency_ms": null}],
  "toasts": [{"toast_id": "…", "severity": "warning", "title": "…",
              "body": "…", "at": "…"}],
  "degraded": []
}
```

Datas sempre em ISO-8601 com offset; ausência é `null`, nunca string vazia
disfarçada. A serialização é escrita à mão, campo a campo — um `asdict` genérico
despejaria qualquer campo novo do domínio na resposta HTTP sem ninguém decidir
isso.

`/api/stream` é SSE: um `data:` por revisão nova, `: heartbeat` quando não há
novidade. A página cai para polling de 3 s depois de duas falhas de conexão.

---

## 7. Notificações

O painel mostra **toasts** derivados de eventos que já existem — confirmação
pedida, ação falhou, ação concluída, política negou. `toast_id` é determinístico
(o `event_id`), então o navegador deduplica sem estado no servidor.

Isso **não** é um Notification System. Não há port `Notification`, nem canal de
desktop, nem prioridade, nem modo silencioso configurável: isso é a subfase 7.3,
e implementá-la aqui adiantaria fase. Quando ela existir, publicará nos mesmos
eventos e o toast do painel vira um canal entre outros.

**Silêncio continua sendo uma decisão válida.** Uma `Decision.ignore` não gera
fala nem toast — e agora dá para *ver* isso acontecendo no painel, o que é a
única mudança que a fase traz para o assunto.

---

## 8. Privacidade

- **Payload de fonte externa nunca vira texto de tela.** `TimelineEntry.summary`
  é derivado do `event_type` mais uma allowlist de campos de identidade que o
  próprio Jarvis escreve (`skill`, `status`, `decision`, `rule_id`, `tool_id`…).
  Um e-mail aparece como `email.received`, e nada mais.
- **CSP sem origem externa**: a página não carrega nada de fora e não consegue
  mandar nada para fora, nem que alguém injete conteúdo num resumo.
- **`textContent`, nunca `innerHTML`** em toda inserção no DOM.
- Cabeçalhos em toda resposta: `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `Content-Security-Policy`.

---

## 9. Comandos

```bash
jarvis panel serve          # só o painel, em http://127.0.0.1:8765
jarvis panel serve --once   # publica um snapshot e sai (útil em teste)
jarvis run                  # voz + painel no mesmo processo
jarvis run --no-voice       # equivalente a `panel serve`
jarvis run --no-panel       # equivalente a `voice listen`
```

---

## 10. Limitações conhecidas

- **Somente leitura, por decisão.** Nenhuma ação é iniciada pelo painel.
- **Só loopback.** Não há como abrir para a rede sem mudar código — e a mudança
  exigiria autenticação.
- **O snapshot é de quando foi montado**, não uma consulta ao vivo. O `as_of` na
  tela diz de quando é.
- **Sem histórico navegável**: a linha do tempo mostra os últimos
  `JARVIS_PANEL_TIMELINE_LIMIT` eventos. Para consulta histórica existe
  `jarvis events list --correlation-id`.
- **Sem gráfico, sem métrica, sem agregação temporal** — o contrato de
  observabilidade (§14) mantém métricas fora de escopo por ora.
