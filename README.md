# Jarvis

Agente pessoal de IA, construído de forma incremental e orientado a eventos,
contexto e memória.

> **Status:** Fase 0 — Foundation. O projeto ainda não possui funcionalidades:
> por enquanto existe apenas a fundação do repositório. O planejamento completo
> está em [ROADMAP.md](ROADMAP.md).

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
