# Jarvis

Agente pessoal de IA, construído de forma incremental e orientado a eventos,
contexto e memória.

> **Status:** Fase 8 — Integration + Hardening concluída (v0.1). O Jarvis registra
> acontecimentos como fatos imutáveis, os projeta em um estado atual consultável,
> lembra (memórias tipadas, com proveniência, validade e ranking explicável),
> raciocina sobre tudo isso com um LLM atrás de um port vendor-agnóstico e
> **age**: a decisão passa por um Policy Engine determinístico antes de virar uma
> Skill executada por ferramentas locais ou por MCP Servers externos, com trilha
> de auditoria em eventos. **Conversa por voz** e mostra tudo o que está
> acontecendo num painel local. **Age sozinho, quando autorizado**: um evento
> publicado durante `jarvis run` pode disparar raciocínio (Trigger Engine) ou
> automação determinística sem LLM (Conditional Triggers), notificar por
> console ou voz (Notification Manager, com política de interrupção) e
> executar tarefas adiadas/repetíveis (Background Task Manager) — tudo atrás
> de três interruptores de opt-in, desligados por padrão (ver
> [ADR-0029](docs/adr/0029-proactivity-opt-in-layers.md)).
>
> A Fase 8 acrescentou **observação do computador** (aplicação/janela ativa,
> CPU/RAM/GPU/rede/ociosidade, processos relevantes — ver
> [`docs/computer.md`](docs/computer.md)) e uma **Computer Skill** (listar
> processos, focar janela, abrir/fechar aplicativo, executar comando
> allowlistado), negada por padrão como qualquer capacidade nova, mais
> `jarvis audit show` (decisão + trilha de ação numa consulta só),
> avaliação comportamental e testes de falha/recuperação cobrindo dez
> cenários de degradação. Planejamento completo em [ROADMAP.md](ROADMAP.md).

## Requisitos

- [uv](https://docs.astral.sh/uv/) (gerencia também o interpretador Python)
- Python 3.13 — instalado automaticamente pelo `uv` conforme `.python-version`

## Setup

```bash
uv sync
cp .env.example .env   # opcional; os defaults já funcionam
```

## Uso

```bash
uv run jarvis --version
uv run jarvis info      # mostra a configuração efetiva
```

### Eventos

```bash
# registra um acontecimento (o payload é um objeto JSON)
uv run jarvis events emit --type email.received --source gmail-watcher \
    --payload '{"subject": "reunião"}' --key '<msg-42@empresa.com>'

# --key deriva um event_id determinístico: reemitir o mesmo fato é no-op
uv run jarvis events list --limit 20
uv run jarvis events list --correlation-id <id>   # a cadeia causal inteira
```

Os eventos ficam em `<JARVIS_DATA_DIR>/events.db` (por padrão `data/events.db`, já
ignorado pelo Git). Detalhes em [`docs/event-system.md`](docs/event-system.md).

### Contexto

```bash
# o que o sistema sabe agora: valor, origem, quando foi observado e se ainda vale
uv run jarvis context show

# congela essa visão para consulta histórica (só grava se algo mudou)
uv run jarvis context snapshot
```

O contexto é uma projeção **derivada** dos eventos e dos providers locais, não uma
fonte de verdade: um processo novo a reconstrói a partir do event store. Campos sem
observação aparecem como `-` e nunca são preenchidos por suposição. Os snapshots
ficam em `<JARVIS_DATA_DIR>/context.db`. Detalhes em
[`docs/context-system.md`](docs/context-system.md).

### Memória

```bash
# cria uma memória (conteúdo é o único texto livre; o resto é tipado)
uv run jarvis memory add --type preference --subject preference.language \
    --content "prefere Python para scripts" --confidence 0.9

uv run jarvis memory list --type preference
uv run jarvis memory search "o que ele usa para programar?" --explain
uv run jarvis memory forget <memory_id> --reason "..."   # invalida, preserva evidência
uv run jarvis memory forget <memory_id> --reason "..." --purge  # apaga de vez
```

Memória é independente de LLM: a busca semântica usa um `EmbeddingProvider` local
e determinístico (similaridade lexical, não um modelo de verdade — um provider
real chega quando houver raciocínio). Contradições não sobrescrevem: a memória
nova supersede a antiga, que continua consultável com `--include-superseded`. As
memórias ficam em `<JARVIS_DATA_DIR>/memory.db`. Detalhes em
[`docs/memory-system.md`](docs/memory-system.md).

### Agente

Exige `JARVIS_GEMINI_API_KEY` (Google AI Studio, tier gratuito). Sem ela, só os
comandos `agent` falham — todo o resto do Jarvis continua funcionando offline.

```bash
uv run jarvis agent ask "o que aconteceu enquanto eu estava fora?"

# conversa multi-turno: uma mensagem por linha na entrada padrão
printf 'oi\ne o que mais?\n' | uv run jarvis agent chat

# avalia proativamente um evento já registrado
uv run jarvis agent react --event-id <id>

# submete a ação proposta ao Policy Engine (opt-in)
uv run jarvis agent ask "grave um lembrete no arquivo notas.txt" --execute
```

O agente monta contexto + memória + conversa, chama o LLM através de um port
vendor-agnóstico e devolve uma `Decision` estruturada (`ignore`, `remember`,
`notify`, `ask`, `act`, `act_and_notify`). **Ele nunca executa nada**: entrega a
decisão e para. Quem autoriza é o Policy Engine, e quem executa é a camada de
ação — por isso `--execute` é opt-in. Um evento de baixa importância vira
silêncio sem sequer chamar o modelo. Detalhes em
[`docs/agent-runtime.md`](docs/agent-runtime.md).

O que o agente decide **lembrar** é gravado no Memory System pelo composition
root, sem `--execute` e sem passar pela política: uma afirmação não é uma
capacidade, não toca nada fora do processo e se desfaz por supersessão
([ADR-0018](docs/adr/0018-memory-writes-outside-the-policy-engine.md)). A saída
diz o que aconteceu — `gravada como <id>`, `reforçada como <id>` ou `proposta
recusada: <motivo>` — e o que foi gravado volta no próximo prompt.

### Skills, tools e ações

```bash
uv run jarvis skills list          # capacidades registradas, com risco e schema
uv run jarvis tools list           # ferramentas descobertas, por backend
uv run jarvis tools list --schemas # + schema de entrada e o que não foi validado

# executa uma capacidade; a política decide antes de qualquer efeito
uv run jarvis action run --skill system.status
uv run jarvis action run --skill file.write \
  --parameters '{"path": "nota.txt", "content": "olá"}'

# ações de risco esperam confirmação explícita
uv run jarvis action pending
uv run jarvis action show <execution_id>
uv run jarvis action confirm <execution_id>
uv run jarvis action reject <execution_id> --reason "mudei de ideia"
```

A cadeia é `Decision → Policy Engine → Skill → Tool Router → Tool/MCP`, e cada
seta é uma barreira: uma ação negada nunca alcança uma ferramenta, e uma ação que
exige confirmação fica parada até você responder. Toda execução vira trilha de
auditoria no Event Store:

```bash
uv run jarvis events list --correlation-id <id>
uv run jarvis audit show <correlation_id>   # decisão + trilha, numa consulta só
```

Ferramentas vêm de três lugares: um backend **local** (arquivos do workspace e
informação de sistema), um backend de **computador** (processos, janelas,
abrir/fechar aplicativo, comando allowlistado — negado por padrão, ver
[`docs/computer.md`](docs/computer.md)) e, opcionalmente, **MCP Servers**
externos declarados em um `mcp.json`. Detalhes em
[`docs/skills.md`](docs/skills.md), [`docs/mcp.md`](docs/mcp.md) e
[`docs/security.md`](docs/security.md).

### Falando com o Jarvis

A voz exige um extra opcional — a única dependência de terceiros do projeto, e
ela existe porque a biblioteca padrão não abre microfone
([ADR-0020](docs/adr/0020-audio-io-ports-and-optional-backend.md)):

```bash
uv sync --extra voice
```

Duas credenciais a mais no `.env`: `JARVIS_GROQ_API_KEY` (transcrição) e
`JARVIS_GOOGLE_TTS_API_KEY` (síntese).

```bash
uv run jarvis voice devices              # o que existe na máquina
uv run jarvis voice say "Olá, tudo bem?" # testa a síntese
uv run jarvis run                        # voz + painel, o modo normal de uso
```

No modo padrão a ativação é por tecla: pressione **Enter** e fale. `Ctrl-C`
encerra. Para chamar pelo nome, `JARVIS_WAKE_STRATEGY=transcription`.

> **O que sai do seu computador.** Com a voz ligada, o áudio dos seus enunciados
> vai para a Groq e o texto das respostas vai para o Google. Com
> `JARVIS_WAKE_STRATEGY=transcription`, trechos curtos do ambiente também são
> enviados enquanto o modo de escuta estiver ativo — por isso ele **não** é o
> padrão. Nenhum áudio é gravado em disco e nenhuma transcrição entra em evento
> ([ADR-0025](docs/adr/0025-voice-transcripts-as-operational-state.md)); o que
> fica registrado em `data/voice.db` expira em 7 dias por default.

Interromper a resposta falando por cima funciona, e pressupõe fone —
sem ele o alto-falante alimenta o microfone (`JARVIS_VOICE_BARGE_IN=false`
desliga). Detalhes em [`docs/voice.md`](docs/voice.md).

### Painel

```bash
uv run jarvis panel serve   # http://127.0.0.1:8765
```

Uma página com sete blocos: conversa, eventos, contexto atual, memórias
recuperadas com score, decisões, ações com o veredito da política e ferramentas
usadas. É **somente leitura** e só escuta em loopback — nenhuma rota inicia ação
([ADR-0024](docs/adr/0024-observability-panel-as-snapshot-reader.md)).
Detalhes em [`docs/interface.md`](docs/interface.md).

### Proatividade

Desligada por padrão — `jarvis run` sem configuração extra se comporta
exatamente como antes da Fase 7. Ligar exige três interruptores
independentes (ver [ADR-0029](docs/adr/0029-proactivity-opt-in-layers.md)):

```bash
JARVIS_PROACTIVITY_ENABLED=true
JARVIS_PROACTIVITY_TRIGGER_EVENT_TYPES=printer.job_completed   # ou um arquivo de regras:
JARVIS_PROACTIVITY_RULES_PATH=rules.json
JARVIS_PROACTIVITY_EXECUTE_ACTIONS=true                        # opt-in, como --execute
```

```bash
uv run jarvis decisions list [--correlation-id <id>]   # trilha de decisões do agente
uv run jarvis tasks list                               # tarefas em background pendentes/em retry
uv run jarvis tasks show <task_id>
uv run jarvis tasks cancel <task_id>
uv run jarvis tasks run-due                             # tica o que estiver devido agora
```

Detalhes em [`docs/proactivity.md`](docs/proactivity.md).

## Desenvolvimento

```bash
uv run pytest             # testes — sem rede, sem credencial, sem áudio, sem quota
uv run pytest -m external # smoke test contra a API real (opcional, exige chave)
uv run ruff format .      # formatação
uv run ruff check .       # lint
uv run mypy               # type checking
```

Esses quatro comandos rodam automaticamente em CI (GitHub Actions) a cada push
e pull request para `main` — ver [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Estrutura

```text
src/jarvis/     código da aplicação
tests/          testes
docs/           documentação técnica
ROADMAP.md      planejamento por fases
```

## Configuração

Todas as variáveis usam o prefixo `JARVIS_` e podem ser definidas no ambiente ou
em um arquivo `.env` na raiz do projeto. Veja [`.env.example`](.env.example) para
a lista completa e os valores padrão.

`uv run jarvis info` imprime a configuração efetiva, incluindo a **política de
autorização** em vigor — ela decide entre uma ação permitida e uma negada, e não
deve ser adivinhada.

Os dados locais ficam em `data/`: `events.db`, `context.db`, `memory.db`,
`actions.db`, `voice.db`, `tasks.db` e o workspace das skills de arquivo.
Nenhum deles é versionado.

## Sobre containers

Sem Docker por enquanto. O projeto roda localmente via `uv`, que já resolve o
interpretador Python e as dependências de forma reprodutível — o principal
motivo para containerizar um projeto pessoal neste estágio. Isso deve ser
reconsiderado quando surgir uma razão concreta: uma dependência de sistema
operacional específica, um serviço externo (ex.: banco de dados) que precise
rodar isolado, ou a necessidade de implantar em outra máquina.
