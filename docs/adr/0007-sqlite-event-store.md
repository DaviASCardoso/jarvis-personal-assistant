# 0007. SQLite como armazenamento do Event Store

**Status:** Accepted
**Data:** 2026-08-09

## Contexto

A Fase 1 precisa de um Event Store persistente
([ROADMAP 1.3](../../ROADMAP.md)). Nem
[`architecture-contracts.md §11`](../architecture-contracts.md#11-persistence-boundary)
nem [ADR-0004](0004-event-immutability-and-timestamps.md) escolhem tecnologia —
ambos deixam a decisão explicitamente para a fase de implementação, garantindo
apenas que ela fique atrás de um port.

O que o store precisa entregar nesta fase:

- durabilidade entre execuções do processo;
- unicidade de `event_id`, para que a idempotência do contrato §5 seja imposta
  pelo armazenamento e não por uma checagem de aplicação sujeita a corrida;
- consulta por tipo, por janela temporal e por `correlation_id`;
- imutabilidade verificável — o contrato exige que ela exista "tanto no modelo de
  domínio quanto na persistência";
- ordenação de leitura estável.

O Jarvis é um agente pessoal em processo único. A Fase 3 escolherá separadamente o
armazenamento da memória (o roadmap já prevê PostgreSQL + pgvector lá), então esta
decisão não precisa antecipar as necessidades daquela fase.

## Decisão

Implementar o Event Store sobre **SQLite**, usando o módulo `sqlite3` da biblioteca
padrão, com o banco em `<data_dir>/events.db`.

O adapter fica em `jarvis/events/adapters/sqlite_store.py`, atrás do port
`EventStore` definido no Core. O schema impõe três propriedades do contrato:

- `UNIQUE(event_id)` + `INSERT … ON CONFLICT DO NOTHING` — reinserção é no-op;
- triggers `BEFORE UPDATE` e `BEFORE DELETE` que abortam a operação — imutabilidade;
- coluna `sequence` autoincremental — desempate determinístico da ordem de leitura
  quando dois `recorded_at` coincidem.

Nenhuma dependência nova é introduzida.

## Alternativas consideradas

- **PostgreSQL**: descartada para esta fase. Exigiria um serviço externo (e
  provavelmente Docker, que o [README](../../README.md) deliberadamente evita por
  ora) para um sistema que roda em processo único na máquina do usuário. O ganho
  real — concorrência de escrita entre processos, replicação — não tem consumidor
  nesta fase. A Fase 3 pode adotá-lo para Memory sem que isso obrigue a migrar o
  Event Store, precisamente porque ambos ficam atrás de ports distintos.
- **Log append-only em arquivo (JSONL)**: descartada. É mais simples de escrever,
  mas não oferece índice único para deduplicação nem consulta por tipo/correlação
  sem varrer o arquivo inteiro, e a imutabilidade dependeria só de disciplina de
  código — exatamente o que `PHASE-1.md §8` proíbe.
- **Somente em memória**: descartada por contrariar o requisito explícito de
  "armazenamento persistente" da subfase 1.3. (SQLite em `:memory:` continua
  disponível, e é o que os testes usam.)

## Consequências

- Zero complexidade operacional: não há serviço para subir, e o arquivo do banco já
  está coberto pelo `.gitignore` via `data/`.
- Idempotência e imutabilidade passam a ser propriedades do armazenamento, não
  promessas da aplicação — e são verificáveis por teste atacando o banco por fora
  do adapter.
- A partir da Fase 3 o sistema provavelmente terá dois bancos com tecnologias
  diferentes (SQLite para eventos, PostgreSQL para memória). Isso é aceitável: são
  ports distintos, com requisitos distintos, e nenhum código de Core muda por causa
  disso.
- SQLite serializa escritas e não é adequado a múltiplos processos escrevendo
  concorrentemente. Se o Jarvis passar a rodar como vários processos, esta decisão
  precisa ser revisitada por um novo ADR — não por uma alteração deste.
- Não resolve migração de schema. Há um `PRAGMA user_version = 1` gravado para que
  uma migração futura tenha um ponto de partida, mas nenhuma ferramenta de migração
  é introduzida agora.
