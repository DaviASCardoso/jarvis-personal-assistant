# Architecture Decision Records

Este diretório registra decisões arquiteturais do Jarvis que são difíceis de
reverter e que fundamentam os contratos em
[`../architecture-contracts.md`](../architecture-contracts.md).

## Quando criar um ADR

Crie um ADR quando a decisão for:

- **difícil/cara de reverter** depois que houver código real sobre ela; e
- **arquitetural** — afeta a forma como componentes se relacionam, não um
  detalhe interno de um único componente; e
- houve uma **alternativa real considerada** e descartada, não uma escolha
  óbvia sem trade-off.

Não crie ADR para: escolha de nomes de campos, formato exato de um schema,
detalhes que podem mudar sem afetar outros componentes, ou qualquer decisão
já reversível de forma barata. Esses detalhes vivem em
`architecture-contracts.md` ou na documentação do componente, não aqui.

## Convenção de nomenclatura

```text
NNNN-titulo-curto-em-kebab-case.md
```

Numeração sequencial, sem reuso de número mesmo que um ADR seja superado.

## Template

```markdown
# NNNN. Título da decisão

**Status:** Accepted | Superseded by ADR-NNNN
**Data:** AAAA-MM-DD

## Contexto

Qual problema/força está em jogo. O que motivou a decisão ser tomada agora.

## Decisão

O que foi decidido, de forma direta.

## Alternativas consideradas

Alternativas reais avaliadas e por que foram descartadas.

## Consequências

O que fica mais fácil, o que fica mais difícil, e o que essa decisão não
resolve.
```

## Ciclo de vida

Um ADR aceito não é editado para refletir uma mudança de decisão — uma
mudança de decisão gera um **novo ADR**, que marca o anterior como
`Superseded by ADR-NNNN`. Isso preserva o histórico de por que a decisão
original fazia sentido no momento em que foi tomada.

## Índice

| ADR | Título | Status |
|---|---|---|
| [0001](0001-ports-and-adapters-dependency-rule.md) | Ports & Adapters como regra de dependência | Accepted |
| [0002](0002-llm-provider-abstraction.md) | Abstração de LLM Provider e separação de Embedding Provider | Accepted |
| [0003](0003-policy-engine-safety-authority.md) | Policy Engine como autoridade determinística de segurança | Accepted |
| [0004](0004-event-immutability-and-timestamps.md) | Imutabilidade de evento e semântica de timestamps | Accepted |
| [0005](0005-skill-tool-mcp-distinction.md) | Distinção entre Skill, Tool, MCP Server e MCP Tool | Accepted |
| [0006](0006-configuration-vs-preferences-vs-state.md) | Configuração vs. Secrets vs. Preferências vs. Estado | Accepted |
| [0007](0007-sqlite-event-store.md) | SQLite como armazenamento do Event Store | Accepted |
| [0008](0008-synchronous-in-process-event-bus.md) | Event Bus síncrono em processo | Accepted |
| [0009](0009-sqlite-memory-storage.md) | SQLite como armazenamento do Memory System | Accepted |
| [0010](0010-immutable-memory-and-supersession.md) | Memória imutável, com supersessão em vez de sobrescrita | Accepted |
