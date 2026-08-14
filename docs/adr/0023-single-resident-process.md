# 0023. `jarvis run`: um processo residente para voz e painel

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

Até a Fase 5 todo comando do Jarvis era one-shot: abre os bancos num `with`,
faz uma coisa, fecha e devolve o terminal. A Fase 6 quebra isso por necessidade —
uma conversa por voz dura minutos, e um painel que mostra o estado ao vivo
precisa estar de pé enquanto ela acontece.

Isso levanta duas perguntas acopladas:

1. **quantos processos** — voz e painel juntos ou separados;
2. **quantas threads tocam SQLite** — que é a pergunta que o driver do Python
   força a responder (`check_same_thread`), e que a regra arquitetural "a
   interface não acessa banco" já respondia de outro jeito.

## Decisão

**Um processo, quatro threads, uma única que toca banco.**

```text
jarvis run
├─ thread principal   VoiceLoop + refresh de snapshot     ← única que usa SQLite
├─ thread daemon      ThreadingHTTPServer (N handlers)    ← só lê o LiveState
├─ thread daemon      callback do PortAudio → queue       ← só produz AudioChunk
└─ thread daemon      StdinTrigger (modo push-to-talk)
```

O que liga as duas primeiras é o `LiveState`: um `PanelSnapshot` por vez, com
revisão monotônica e um `threading.Condition`. A thread principal **publica**; as
threads do servidor **leem** e, no SSE, dormem até a próxima revisão.

Consequência que vale mais que a simetria: a regra de concorrência cai de graça
da regra arquitetural. O servidor nunca precisa de uma conexão porque nunca
precisa de dado que não esteja no snapshot — e é bom sinal que "não acessar
banco" e "não ter problema de thread" tenham a mesma solução.

`jarvis voice listen` e `jarvis panel serve` são o mesmo corpo com peças
diferentes (`--no-panel` / `--no-voice`), e não implementações paralelas.

Duas cadências de atualização, porque uma só não serviria:

- **status**: toda transição de estado da voz publica na hora, sem I/O;
- **snapshot**: a cada `JARVIS_PANEL_REFRESH_SECONDS` e ao fim de cada turno,
  relê as quatro fontes.

Sem a primeira, o painel congelaria enquanto o Jarvis espera a nuvem — que é
justamente quando alguém olha para ele.

## Alternativas consideradas

- **Dois processos (voz e painel), conversando por arquivo ou socket**: exigiria
  IPC, serialização e uma segunda fonte de estado a divergir, num agente pessoal
  de um usuário. Todo o custo, nenhum benefício.
- **`asyncio`**: reverteria o [ADR-0008](0008-synchronous-in-process-event-bus.md)
  na prática, forçando a reescrita do bus, dos consumers, do CLI e da suíte
  inteira. O sistema tem exatamente um usuário e uma conversa por vez.
- **Painel lendo o banco na própria thread** (com `check_same_thread=False`):
  quebraria a regra "a interface não acessa SQLite", que é verificada por teste,
  e trocaria uma propriedade arquitetural por conveniência.
- **Um daemon de verdade (serviço do sistema operacional)**: fora de escopo. O
  Jarvis ainda é um processo que alguém inicia e encerra com Ctrl-C.

## Consequências

- O painel continua servindo mesmo quando a voz falha: um erro de áudio encerra a
  sessão, não o processo — e é exatamente aí que observabilidade vale alguma
  coisa.
- Ctrl-C encerra a sessão com `ended_reason="interrupted"`, fecha dispositivos e
  para o servidor, com código 0.
- Como os quatro bancos já usam `PRAGMA journal_mode = WAL` desde as fases
  anteriores, um `jarvis events emit` em outro terminal continua funcionando com
  o residente de pé.
- **Custo aceito:** um consumer lento na thread principal atrasa a resposta da
  voz. Aceitável enquanto as leituras forem as quatro consultas curtas do painel;
  o gatilho para revisitar é um snapshot que passe a custar o suficiente para ser
  perceptível entre um turno e outro.
- **Este ADR precisará ser superado** se o Jarvis executar ações fora deste
  processo (daemon separado, serviço remoto) — aí passa a existir uma fronteira
  de confiança real, e o [ADR-0013](0013-single-use-policy-approval.md) também
  cai junto.
