# Event System

> Documentação do Event System, implementado na **Fase 1** do
> [roadmap](../ROADMAP.md). O contrato normativo está em
> [`architecture-contracts.md §5`](architecture-contracts.md#5-event-contract) e em
> [ADR-0004](adr/0004-event-immutability-and-timestamps.md); as decisões de
> implementação desta fase, em [ADR-0007](adr/0007-sqlite-event-store.md) e
> [ADR-0008](adr/0008-synchronous-in-process-event-bus.md). Este documento explica o
> *porquê* e descreve o que existe de verdade em `src/jarvis/events/`, sem repetir a
> tabela de campos do contrato.

## Por que um Event System

O Event System é o componente que primeiro toca tudo que acontece no mundo
digital/físico observável pelo Jarvis — um email chegando, o usuário abrindo uma
aplicação, uma reunião se aproximando. Ele existe para transformar esses
acontecimentos brutos em **fatos estruturados e imutáveis** que o resto do sistema
(Context Engine, Memory, Agent Runtime) pode consumir sem precisar conhecer a fonte
original de cada um. Ver visão geral em
[architecture.md §2](architecture.md#2-visão-de-alto-nível).

## Conceitos

- **Event** — um fato imutável: algo que aconteceu, com identidade (`event_id`),
  tipo (`event_type`), quando aconteceu (`occurred_at`) e o que aconteceu
  (`payload`). Uma vez persistido, nunca é alterado — correções são novos eventos.
- **Event Source** — de onde um evento se origina (ex. `gmail-watcher`,
  `manual-cli`). É um adapter de Infrastructure, não um componente do Core. Nenhuma
  source real existe ainda: hoje o único producer é o CLI.
- **Event Bus** — entrega um evento recém-registrado a quem estiver consumindo.
- **Event Store** — o registro persistente e consultável. É ele, e só ele, que
  atribui `recorded_at`.
- **Event Consumer** — qualquer componente a jusante que reage a eventos. Um
  Consumer nunca modifica um evento — só lê e produz efeitos próprios.

## Estrutura

```text
src/jarvis/events/
├── event.py       Event, RecordedEvent, JsonValue, geradores de event_id
├── errors.py      InvalidEventError, EventStoreError, Append/Read
├── ports.py       EventStore (Protocol), EventConsumer (Protocol), AppendResult
├── bus.py         EventBus, RetryPolicy, DeadLetter
├── publisher.py   EventPublisher (store → bus)
└── adapters/
    ├── serialization.py    Event ↔ registro persistido, fingerprint
    ├── sqlite_store.py     SqliteEventStore
    └── logging_consumer.py LoggingEventConsumer
```

A raiz do pacote é Core; `adapters/` é Infrastructure. Nenhum módulo de Core importa
`adapters/` — a regra de dependência do
[ADR-0001](adr/0001-ports-and-adapters-dependency-rule.md) é verificada por
`tests/test_events_architecture.py`, que analisa os imports estaticamente. A
separação física global em `domain/`/`application/`/`infrastructure/` continua **não
existindo**, de propósito.

## `Event` e `RecordedEvent`: dois tipos, não um

O contrato diz que `recorded_at` é atribuído pelo Event Store e "não é definido nem
editável pelo producer". Em vez de confiar nessa regra como convenção, ela é
estrutural:

- `Event` é o que um producer constrói. Não possui `recorded_at` — passar esse
  argumento é um `TypeError`.
- `RecordedEvent` é `Event` + `recorded_at`, e só o Event Store o produz.

Consumers recebem sempre `RecordedEvent`, ou seja, só veem eventos que já estão
duráveis e já passaram pela deduplicação.

### Imutabilidade

Vale nos dois lados, conforme `PHASE-1.md §8`:

- **no domínio** — `Event` é um dataclass `frozen`; reatribuir um campo levanta
  `FrozenInstanceError`. O `payload` é congelado recursivamente na construção
  (`dict` vira `MappingProxyType`, `list` vira `tuple`), então nem o próprio
  producer consegue alterá-lo depois, e mutar o dicionário original não afeta o
  evento já criado;
- **na persistência** — o schema tem triggers que abortam qualquer `UPDATE` ou
  `DELETE` na tabela `events`.

O congelamento também valida: só tipos JSON são aceitos (`bytes`, `set`, `datetime`,
`NaN` e afins são recusados com `InvalidEventError`), o que garante que um evento
construído é sempre serializável — o erro aparece na criação, não na hora de gravar.

## Correlation e Causation

Um único acontecimento costuma gerar uma cadeia: um email chega
(`email.received`) → o agente decide agir → uma resposta é enviada (`email.sent`).
Dois campos amarram essa cadeia sem depender de posição no tempo:

- **`correlation_id`** agrupa a cadeia inteira. Um evento raiz que não informa
  correlação passa a usar o próprio `event_id` — depois da construção o campo nunca
  é nulo.
- **`causation_id`** aponta apenas para o evento pai **direto**.

`store.read_by_correlation(...)` devolve a cadeia inteira, e `causation_id` permite
remontar pai → filho sem usar a posição no stream como prova de causalidade.

## Idempotência

Sources podem, por retry de rede ou reprocessamento, emitir o "mesmo" evento mais de
uma vez. A responsabilidade é empurrada para a origem: `deterministic_event_id`
deriva o `event_id` de uma chave natural da source (ex. o `Message-ID` de um email)
via UUID5, de modo que reobservar o mesmo fato produza o mesmo identificador.
`new_event_id` (UUID4) fica para eventos sem chave natural.

No store, a coluna `event_id` é `UNIQUE` e o insert usa `ON CONFLICT DO NOTHING`:

- reinserção é **no-op**, nunca erro — não existe `DuplicateEventError`;
- `append` devolve `AppendResult(event=<registro original>, is_duplicate=True)`, com
  o `recorded_at` da primeira vez;
- o `EventPublisher` **não republica** duplicatas no bus, então nenhum consumer
  processa o mesmo fato duas vezes.

Se um `event_id` conhecido reaparece com conteúdo diferente, o registro original
prevalece (imutabilidade não admite exceção) e um `WARNING` é emitido comparando
fingerprints SHA-256 — nunca o conteúdo.

## `occurred_at` vs. `recorded_at`

| | `occurred_at` | `recorded_at` |
|---|---|---|
| **O que representa** | tempo de domínio — quando o fato aconteceu | tempo de persistência — quando o Event Store gravou |
| **Quem define** | o producer | o Event Store, no `append` |
| **Editável depois?** | não (imutável) | nunca — não é sequer um campo de `Event` |

Ambos são normalizados para UTC e exigem timezone; um datetime naive é recusado.

A ordenação de leitura é a **ordem de persistência**, desempatada por uma coluna
`sequence` autoincremental quando dois `recorded_at` coincidem. É uma garantia de
ordem estável para quem lê do mesmo store, não uma alegação sobre relógio monotônico
global: o store aceita e preserva um `occurred_at` posterior ao `recorded_at`, que é
exatamente o que clock skew entre source e store produz.

## Consultas disponíveis

O port `EventStore` expõe apenas o que a fase precisa (`PHASE-1.md §12`):
`append`, `get`, `read_by_type`, `read_by_correlation`, `read_occurred_between`
(intervalo semiaberto sobre `occurred_at`) e `read_latest`. Não há paginação, busca
textual, filtro composto nem leitura por offset — leitura por cursor é necessidade
do Context Engine e será acrescentada na Fase 2, com o consumidor real na mão.

## Distribuição: bus, ack, retry, dead letter

Persistência e distribuição são responsabilidades separadas. O bus é síncrono e em
processo (ver [ADR-0008](adr/0008-synchronous-in-process-event-bus.md) para as
alternativas descartadas):

- entrega em ordem de inscrição, com filtro opcional por `event_type`;
- **ack** = o consumer retorna; **nack** = o consumer levanta exceção;
- **retry** opt-in via `RetryPolicy(max_attempts, delay)`, default sem retry;
- **dead letter** entregue a um handler injetado depois de esgotadas as tentativas;
  o default registra em log;
- a falha de um consumer não impede os demais nem propaga para quem publicou.

O `EventPublisher` é o ponto de entrada que junta os dois na ordem correta:
**persistir e só então distribuir**. Falha de persistência propaga; falha de consumer
não — o fato já é histórico.

## Uso pelo CLI

```bash
# registra um evento (o payload é um objeto JSON)
jarvis events emit --type email.received --source gmail-watcher \
    --payload '{"subject": "reunião"}' --key '<msg-42@empresa.com>'

# reemitir o mesmo acontecimento é no-op: status "duplicate", nada é republicado
jarvis events emit --type email.received --source gmail-watcher \
    --payload '{"subject": "reunião"}' --key '<msg-42@empresa.com>'

jarvis events list --limit 20
jarvis events list --type email.received
jarvis events list --correlation-id <id>            # a cadeia causal inteira
jarvis events list --since <iso> --until <iso>      # janela de occurred_at
```

O banco fica em `<JARVIS_DATA_DIR>/events.db` (padrão `data/events.db`, já ignorado
pelo Git). `jarvis info` mostra o caminho efetivo.

Códigos de saída: `0` sucesso, `2` entrada inválida, `1` falha de infraestrutura.
Mensagens de erro vão para `stderr`, sem stack trace.

## Observabilidade e dados sensíveis

Componentes usam `logging.getLogger(__name__)`; quem configura formato, destino e
nível é o composition root (`cli.py`), aplicando `JARVIS_LOG_LEVEL`. Os registros
carregam `event_id`, `event_type`, `source`, `correlation_id` e `causation_id`, como
pede [`architecture-contracts.md §14`](architecture-contracts.md#14-observability-contract).

**Nem `payload` nem `metadata` são logados em nenhum ponto.** Eventos podem carregar
dados pessoais, e log é o lugar mais fácil de vazá-los. Quando a forma do conteúdo
importa para diagnóstico, apenas os nomes das chaves de primeiro nível são
registrados; para detectar duplicata divergente, apenas fingerprints. Há testes que
asseguram que valores sensíveis não aparecem no log.

## O que não foi implementado, e por quê

- **Bus assíncrono, broker externo, fila de dead letter persistente** — sem
  consumidor real nesta fase (ADR-0008).
- **Leitura por offset/cursor, paginação, busca textual** — necessidades da Fase 2
  em diante; construí-las agora seria API para requisito inexistente.
- **Migração de schema e upcasting de `schema_version`** — o campo existe no
  envelope e é persistido; tratar versões antigas é responsabilidade do consumidor
  quando houver uma segunda versão de algum `event_type`.
- **Event Sources reais (Gmail, calendário, sistema operacional)** — pertencem às
  fases das capacidades correspondentes.

## Relação com o resto do sistema

O Event System não conhece Context Engine, Memory, Agent Runtime, Skills ou Policy —
ele só produz, armazena e distribui `Event`s (ver limites em
[`architecture-contracts.md §3.1`](architecture-contracts.md#31-event-system)). É o
Context Engine, como consumidor, que decidirá o que fazer com cada evento — ver
[context-system.md](context-system.md).

## Documentos relacionados

- Contrato normativo: [architecture-contracts.md §5](architecture-contracts.md#5-event-contract)
- Imutabilidade e timestamps: [ADR-0004](adr/0004-event-immutability-and-timestamps.md)
- Persistência escolhida: [ADR-0007](adr/0007-sqlite-event-store.md)
- Modelo de distribuição: [ADR-0008](adr/0008-synchronous-in-process-event-bus.md)
- Plano da fase: [phase-1-plan.md](phase-1-plan.md)
- Regras de criação de Events: [CLAUDE.md §6](../CLAUDE.md)
