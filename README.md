# Jarvis

Agente pessoal de IA, construído de forma incremental e orientado a eventos,
contexto e memória.

> **Status:** Fase 3 — Memory System concluída. O Jarvis registra acontecimentos
> como fatos imutáveis, os projeta em um estado atual consultável e agora também
> lembra: memórias tipadas, com proveniência, validade e um ranking explicável,
> independentes de qualquer LLM. Raciocínio e voz ainda não existem — o
> planejamento completo está em [ROADMAP.md](ROADMAP.md).

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

## Desenvolvimento

```bash
uv run pytest           # testes
uv run ruff format .    # formatação
uv run ruff check .     # lint
uv run mypy             # type checking
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

## Sobre containers

Sem Docker por enquanto. O projeto roda localmente via `uv`, que já resolve o
interpretador Python e as dependências de forma reprodutível — o principal
motivo para containerizar um projeto pessoal neste estágio. Isso deve ser
reconsiderado quando surgir uma razão concreta: uma dependência de sistema
operacional específica, um serviço externo (ex.: banco de dados) que precise
rodar isolado, ou a necessidade de implantar em outra máquina.
