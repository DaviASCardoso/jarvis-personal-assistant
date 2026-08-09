# Plano de implementação — Fase 1: Event System

> Plano técnico da **Fase 1** do [roadmap](../ROADMAP.md), produzido em sessão de
> planejamento dedicada e aprovado antes da implementação. Complementa
> [`../PHASE-1.md`](../PHASE-1.md) (especificação da fase) — o `ROADMAP.md`
> continua sendo a fonte de verdade sobre o escopo, e
> [`architecture-contracts.md`](architecture-contracts.md) + [ADRs](adr/) sobre a
> arquitetura. Este documento **não redefine** contrato nenhum: ele decide *como*
> materializar em código o que já está decidido.
>
> **Estado:** executado. A Fase 1 foi implementada conforme este plano; os poucos
> desvios estão registrados na §17. Para o que existe hoje no código, a referência
> é [`event-system.md`](event-system.md) — este documento fica como registro das
> decisões e das alternativas descartadas.

---

## 1. Contexto

A Fase 0 (Foundation) está concluída: contratos, seis ADRs aceitos, documentação
conceitual e um esqueleto de aplicação (`cli.py` + `config.py`) sem funcionalidade.
A Fase 1 é a primeira que produz comportamento real — transformar o contrato de
`Event` ([contracts §5](architecture-contracts.md#5-event-contract) +
[ADR-0004](adr/0004-event-immutability-and-timestamps.md)) em domínio, bus, store
persistente, consumers e integração, sem antecipar Context, Memory, Agent, Policy,
Skills ou MCP.

A fase será executada como **uma única unidade** (subfases 1.1–1.5 numa sessão),
conforme `PHASE-1.md §27`.

**Resultado esperado:** o Jarvis passa a registrar um acontecimento como fato
imutável, persistí-lo com deduplicação real, distribuí-lo a consumidores e
recuperá-lo por tipo, por janela temporal e por `correlation_id` — acionável pelo
CLI e verificável por testes.

---

## 2. Conflitos e ambiguidades encontrados

Registrados aqui em vez de resolvidos silenciosamente (`CLAUDE.md §10`).

| # | Conflito | Documentos | Resolução |
|---|---|---|---|
| C1 | `PHASE-1.md §19` manda "utilizar a infraestrutura de logging existente" — **ela não existe** (nenhum `logging` em `src/`), embora `JARVIS_LOG_LEVEL` já exista em `Settings` e nunca seja aplicado. | PHASE-1 §19; `config.py` | Criar o mínimo: `configure_logging(level)` **dentro de `cli.py`** (composition root), com `logging` da stdlib. Zero dependência nova, zero módulo novo. Componentes usam `logging.getLogger(__name__)`. |
| C2 | `ROADMAP 1.2` pede "acknowledgement / retry / tratamento de falhas" e `1.4` pede "processamento assíncrono quando necessário" e "dead-letter" — o que sugere um broker; a regra 11 do roadmap e `PHASE-1 §13/§24` proíbem infraestrutura especulativa. | ROADMAP 1.2/1.4 vs. regra 11 | Bus **síncrono em processo**: ack = retorno normal do consumer; nack = exceção; retry opt-in e limitado; dead-letter via callback injetado (default: log). Sem asyncio, sem broker — "quando necessário" é a válvula do próprio roadmap, e não é necessário nesta fase (nenhum consumer faz I/O bloqueante). Registrado como **ADR-0008**. |
| C3 | `ROADMAP 1.2` pede "definir interface do Event Bus"; [contracts §1](architecture-contracts.md#1-princípios-e-escopo) proíbe "port/interface sem consumidor real". | ROADMAP 1.2 vs. contracts §1 | O Bus é uma **classe concreta do Core** (implementação única, nenhuma necessidade de substituição); sua "interface" é sua API pública. O **Event Store é port** (`Protocol`) porque [contracts §11](architecture-contracts.md#11-persistence-boundary) e `PHASE-1 §11` exigem que o domínio não conheça SQL. Assimetria intencional. |
| C4 | `ROADMAP 1.3` pede "consulta temporal" sem dizer sobre qual timestamp. | ROADMAP 1.3; contracts §5 | A consulta temporal filtra `occurred_at` (tempo de domínio); a **ordenação** de toda leitura é a ordem de persistência. Nomes de método explícitos eliminam a ambiguidade. |
| C5 | `CLAUDE.md §2` afirma "Fase 0 … não há Event System implementado" — ficará desatualizado. | CLAUDE.md §2 | Atualizar a §2 (árvore + parágrafo de estado) como parte da fase. É manutenção factual, não mudança de regra. |
| C6 | `PHASE-1.md §26` exige working tree limpo ao final, mas `PHASE-1.md` está **untracked**. | git status | Versionar `PHASE-1.md` + este plano no primeiro commit da fase. |

Nenhum conflito impede implementação segura. `ROADMAP.md`, `CLAUDE.md`, contratos e
ADRs existentes **não são alterados** para acomodar o plano — apenas recebem as
atualizações previstas na §11.

---

## 3. Decisões técnicas

Formato: **decisão → motivo → alternativas → impacto → reversibilidade**.

### D1 — Estrutura física: um pacote por componente, com `adapters/` interno

`src/jarvis/events/` com módulos de Core na raiz do pacote e um subpacote
`events/adapters/`. **Não** criar `domain/`, `application/`, `infrastructure/`,
`interfaces/` no topo.

- **Motivo:** [ADR-0001](adr/0001-ports-and-adapters-dependency-rule.md)
  ("Alternativas consideradas") e `CLAUDE.md §1` proíbem a separação física em
  quatro pastas antes de o volume de código justificá-la. Um `adapters/` interno dá
  uma fronteira **verificável por teste** (nenhum módulo de Core importa
  `events.adapters`) sem antecipar a estrutura global.
- **Alternativas:** (a) quatro pastas top-level — rejeitada pelo ADR-0001;
  (b) tudo plano em `events/` com sufixos no nome do módulo — rejeitada porque a
  fronteira viraria convenção de nome, não algo testável.
- **Impacto:** profundidade máxima de dois níveis; a Fase 2 repete o padrão
  (`jarvis/context/`) sem precisar decidir nada de novo.
- **Reversibilidade:** alta (mover módulos + ajustar imports).

### D2 — Modelo de domínio: `dataclass(frozen=True, slots=True, kw_only=True)`, não pydantic

- **Motivo:** `PHASE-1 §16` manda não acoplar o modelo de domínio a uma biblioteca
  de serialização sem necessidade; as validações desta fase são simples (strings não
  vazias, `event_type` namespaced, datetime aware, versão ≥ 1). `frozen=True` dá
  imutabilidade **imposta pela linguagem** (`FrozenInstanceError`), atendendo
  `PHASE-1 §8` ("não confiar apenas em uma convenção informal").
- **Alternativas:** pydantic `BaseModel(frozen=True)` — já presente como dependência
  transitiva de `pydantic-settings`, daria validação e JSON de graça, mas acopla o
  domínio a uma biblioteca e exigiria promovê-la a dependência direta.
- **Impacto:** validação e serialização escritas à mão (~80 linhas somadas),
  inteiramente sob controle e testáveis.
- **Reversibilidade:** média — trocar depois exige reescrever `event.py` e os testes
  de domínio, mas nada fora do pacote `events`.

### D3 — `Event` e `RecordedEvent` são dois tipos

`Event` = o que um producer cria (sem `recorded_at`). `RecordedEvent` = `Event` +
`recorded_at`, produzido **apenas** pelo Event Store.

- **Motivo:** o ADR-0004 diz que `recorded_at` "não é definido nem editável pelo
  producer". Dois tipos tornam isso **estruturalmente impossível** em vez de apenas
  documentado. Consumers só recebem `RecordedEvent` — ou seja, só veem eventos já
  duráveis e já deduplicados.
- **Alternativas:** um tipo só, com `recorded_at: datetime | None` — rejeitada:
  campo nulo em todo lugar e nada impede o producer de preenchê-lo.
- **Impacto:** consumidores escrevem `recorded.event.event_type` (composição, sem
  properties delegadas — explícito em vez de meio-espelho de API).
- **Reversibilidade:** média (afeta assinaturas de bus, store e consumers).

### D4 — Persistência: SQLite (`sqlite3` da stdlib), arquivo em `data/events.db`

- **Motivo:** único candidato que satisfaz durabilidade + consulta + índice `UNIQUE`
  (idempotência real) com **zero dependência nova**, zero serviço externo e baixa
  complexidade operacional — exatamente o critério de `PHASE-1 §11`.
  [contracts §11](architecture-contracts.md#11-persistence-boundary) e
  [architecture.md §5](architecture.md#5-fronteira-de-persistência-cross-cutting)
  deixam a escolha explicitamente para a fase de implementação.
- **Alternativas:** (a) PostgreSQL — rejeitada: serviço externo e Docker num projeto
  pessoal de processo único, e `PHASE-1 §4` proíbe banco de produção nesta fase;
  (b) log JSONL append-only — rejeitada: sem índice único para deduplicação e sem
  consulta por tipo/correlação a não ser por varredura; (c) apenas in-memory —
  rejeitada: `ROADMAP 1.3` exige armazenamento persistente.
- **Impacto:** o sistema terá dois bancos quando a Fase 3 escolher PostgreSQL +
  pgvector para Memory — aceitável, e isolado pelos ports.
- **Reversibilidade:** alta no código (o port isola tudo), média nos dados (migração
  exigiria export/import). **Registrada como ADR-0007.**

### D5 — Idempotência: `UNIQUE(event_id)` + `INSERT … ON CONFLICT DO NOTHING`

Duplicata **não é erro**: `append()` devolve
`AppendResult(event=<o já gravado>, is_duplicate=True)` e o publisher **não
republica** no bus.

- **Motivo:** contracts §5 e ADR-0004 mandam tratar reinserção como no-op.
  Deduplicar **antes** do dispatch dá idempotência de consumo de graça
  (`PHASE-1 §9`).
- **Alternativas:** (a) `DuplicateEventError` — contradiz o contrato; (b) `SELECT`
  antes do `INSERT` — race condition e uma ida a mais ao banco.
- **Impacto:** o chamador distingue "gravei" de "já existia" sem exceção como fluxo
  de controle e sem `None` ambíguo (`PHASE-1 §18`).
- **Reversibilidade:** alta.

### D6 — Duplicata com conteúdo divergente: no-op + `WARNING`

Se chegar o mesmo `event_id` com corpo diferente, o registro original é preservado
(contrato) e um `WARNING` é emitido comparando **fingerprints** (SHA-256 do JSON
canônico), nunca os payloads.

- **Motivo:** silêncio total esconderia um bug de producer; erro violaria o no-op do
  contrato; logar payload violaria `PHASE-1 §20`.
- **Alternativas:** ignorar em silêncio, ou levantar erro — ambas piores.
- **Reversibilidade:** alta.

### D7 — Imutabilidade também na persistência: triggers SQLite

`CREATE TRIGGER … BEFORE UPDATE/DELETE ON events … RAISE(ABORT, …)`.

- **Motivo:** `PHASE-1 §8` exige imutabilidade "tanto no modelo de domínio quanto na
  persistência" e proíbe confiar em convenção. São ~6 linhas de DDL, e viram teste.
- **Alternativas:** apenas disciplina de código (o adapter não emite `UPDATE`/
  `DELETE`) — rejeitada por ser exatamente a convenção informal proibida.
- **Impacto:** qualquer correção futura precisa ser um novo evento — que é a regra
  do ADR-0004.
- **Reversibilidade:** alta (`DROP TRIGGER`), mas a decisão é justamente não deixar
  a porta aberta.

### D8 — Payload profundamente congelado e restrito a tipos JSON

No `__post_init__`, `payload`/`metadata` são convertidos recursivamente
(`dict → MappingProxyType`, `list → tuple`) e validados contra o conjunto de tipos
JSON; qualquer outro tipo levanta `InvalidEventError`.

- **Motivo:** resolve três requisitos numa passada — imutabilidade real (§8),
  tipagem explícita sem `Any` (§15) e garantia de que o evento **é serializável** no
  momento em que é criado, não só na hora de gravar (§16).
- **Alternativas:** aceitar `dict` e confiar no chamador — rejeitada: mutação
  posterior corromperia um "fato imutável" já publicado.
- **Impacto:** ~25 linhas recursivas; erro de tipo aparece cedo e com mensagem clara.
- **Reversibilidade:** alta.

### D9 — Event Bus síncrono, ack por retorno, retry opt-in, dead-letter por callback

Ver conflito **C2**. Dispatch síncrono em ordem de inscrição, isolamento por
consumer, `RetryPolicy(max_attempts, delay)` com default de uma tentativa, `sleep`
injetável (testes não dormem) e dead-letter entregue a um
`Callable[[DeadLetter], None]` cujo default apenas loga.

- **Alternativas:** (a) bus asyncio — mudaria o modelo de execução de todo o sistema
  sem necessidade atual; (b) broker externo (Redis/NATS) — infraestrutura pesada,
  proibida por `PHASE-1 §11` e pela regra 11 do roadmap; (c) sem retry/dead-letter —
  contraria ROADMAP 1.2/1.4.
- **Impacto:** a Fase 2 (Context Engine) escreverá consumers síncronos; migrar para
  async depois tocaria todos os consumers.
- **Reversibilidade:** média/baixa → por isso vira **ADR-0008**.

### D10 — Ordem: store primeiro, bus depois (`EventPublisher`)

- **Motivo:** garante que nenhum consumer veja um evento que ainda não está durável,
  e faz a deduplicação acontecer antes do dispatch.
- **Alternativas:** publicar antes de persistir (consumer reagiria a algo que pode
  falhar ao gravar); publicar em paralelo (concorrência sem necessidade).
- **Impacto:** falha de persistência propaga (`EventAppendError`); falha de consumer
  **não** falha o registro — o fato já é histórico.
- **Reversibilidade:** alta.

### D11 — `event_id` é `str`, com dois helpers explícitos

`new_event_id()` → UUID4; `deterministic_event_id(source=…, natural_key=…)` → UUID5
sob uma constante de namespace fixa do projeto.

- **Motivo:** contracts §5 pede id determinístico "quando possível"; dois helpers
  nomeados tornam a escolha consciente no ponto de criação.
- **Alternativas:** `NewType("EventId", str)` — não desambigua nada de útil
  (`correlation_id` e `causation_id` teriam o mesmo tipo) e adiciona ruído.
- **Impacto:** a constante de namespace **nunca pode mudar** — mudá-la quebraria a
  deduplicação de eventos já gravados. Vai comentada no código.
- **Reversibilidade:** alta para o tipo; baixa para o namespace (daí o comentário).

### D12 — Taxonomia de erros: base compartilhada mínima em `src/jarvis/errors.py`

`JarvisError` → `DomainError` (`retryable = False`) / `InfrastructureError`
(`retryable = True`); as classes específicas ficam em `events/errors.py`.

- **Motivo:** [contracts §13](architecture-contracts.md#13-error-contract) diz que o
  Core é dono de uma taxonomia **compartilhada** e que toda categoria declara
  retryable/permanent. Tem consumidor real hoje (o Event System), então não é
  abstração especulativa. Apenas as duas categorias em uso — nada de
  `ProviderError`/`PolicyDenied`/`UserFacingError` sem consumidor.
- **Reversibilidade:** alta.

### D13 — Nenhuma dependência nova

Tudo com biblioteca padrão. Ver §9.

---

## 4. Arquivos

### Criados — código

```text
src/jarvis/errors.py                           taxonomia base do Core (D12)
src/jarvis/events/__init__.py                  API pública do componente
src/jarvis/events/event.py                     Event, RecordedEvent, JsonValue, ids, freeze/validação
src/jarvis/events/errors.py                    InvalidEventError, EventStoreError, Append/Read
src/jarvis/events/ports.py                     EventStore (Protocol), EventConsumer (Protocol), AppendResult
src/jarvis/events/bus.py                       EventBus, RetryPolicy, DeadLetter
src/jarvis/events/publisher.py                 EventPublisher (store → bus)
src/jarvis/events/adapters/__init__.py
src/jarvis/events/adapters/serialization.py    Event ↔ registro persistido + fingerprint
src/jarvis/events/adapters/sqlite_store.py     SqliteEventStore
src/jarvis/events/adapters/logging_consumer.py LoggingEventConsumer
```

### Criados — testes

```text
tests/test_events_event.py           domínio, validação, imutabilidade, ids
tests/test_events_errors.py          hierarquia + classificação retryable
tests/test_events_serialization.py   round-trip, JSON canônico, fingerprint
tests/test_events_sqlite_store.py    persistência, consultas, idempotência, triggers, erros
tests/test_events_bus.py             dispatch, filtro, isolamento, retry, dead-letter
tests/test_events_publisher.py       ordem store→bus, duplicata não republica
tests/test_events_architecture.py    direção de import (Core ⇏ adapters), via AST
tests/test_events_integration.py     fluxo end-to-end com SQLite em arquivo real
```

### Criados — documentação

```text
docs/adr/0007-sqlite-event-store.md                 D4
docs/adr/0008-synchronous-in-process-event-bus.md   D9
```

### Modificados

```text
src/jarvis/cli.py               composition root + configure_logging + subcomando `events`
tests/test_cli.py               cobertura dos novos subcomandos
docs/event-system.md            deixa de ser só conceitual → documenta o que existe
docs/README.md                  ajusta a descrição de event-system.md
docs/adr/README.md              índice: 0007, 0008
docs/architecture-contracts.md  §15: acrescenta 0007 e 0008 à lista de ADRs
CLAUDE.md                       §2: árvore e estado do projeto (C5)
README.md                       status da fase + uso do `jarvis events`
ROADMAP.md                      checkboxes 1.1–1.5, "FASE 1 CONCLUÍDA", M1, histórico
PHASE-1.md                      apenas passa a ser versionado (C6); conteúdo intacto
```

### Removidos

Nenhum. `pyproject.toml` e `uv.lock` **não** são tocados.

---

## 5. Modelo de domínio (`events/event.py`)

```python
type JsonValue = str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    event_id: str
    event_type: str  # namespaced: >= 2 segmentos, ex. "email.received"
    occurred_at: datetime  # tz-aware, normalizado para UTC
    source: str  # ex. "gmail-watcher", "manual-cli"
    payload: Mapping[str, JsonValue]
    schema_version: int = 1
    correlation_id: str | None = None  # resolvido para event_id quando ausente
    causation_id: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    event: Event
    recorded_at: datetime  # UTC; atribuído SÓ pelo Event Store
```

Invariantes verificadas em `__post_init__` (falha ⇒ `InvalidEventError`):

1. `event_id` não vazio; `causation_id`, se presente, não vazio.
2. `event_type` casa `^[a-z0-9]+(_[a-z0-9]+)*(\.[a-z0-9]+(_[a-z0-9]+)*)+$`
   (namespace obrigatório).
3. `source` casa `^[a-z0-9][a-z0-9._-]*$`.
4. `occurred_at` é tz-aware (naive ⇒ erro) e é normalizado para UTC.
5. `schema_version >= 1`.
6. `payload`/`metadata` congelados recursivamente e restritos a tipos JSON (D8).
7. `correlation_id is None` ⇒ passa a valer `event_id` (contracts §5).

Helpers: `new_event_id()`, `deterministic_event_id(source=…, natural_key=…)` (D11).

Campos deliberadamente ausentes: nenhum além dos de contracts §5 — sem `sequence`/
`offset` exposto (detalhe de ordenação do adapter), sem `actor`, sem `trace_id`.

---

## 6. Ports, Bus e Publisher

### `events/ports.py`

```python
@dataclass(frozen=True, slots=True)
class AppendResult:
    event: RecordedEvent
    is_duplicate: bool


class EventStore(Protocol):
    def append(self, event: Event) -> AppendResult: ...
    def get(self, event_id: str) -> RecordedEvent | None: ...
    def read_by_type(
        self, event_type: str, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]: ...
    def read_by_correlation(self, correlation_id: str) -> Sequence[RecordedEvent]: ...
    def read_occurred_between(
        self, start: datetime, end: datetime, *, limit: int | None = None
    ) -> Sequence[RecordedEvent]: ...
    def read_latest(self, *, limit: int) -> Sequence[RecordedEvent]: ...


class EventConsumer(Protocol):
    @property
    def name(self) -> str: ...
    def handle(self, event: RecordedEvent) -> None: ...
```

- Toda leitura devolve em **ordem de persistência ascendente** (contracts §5).
- `read_occurred_between` é semiaberto `[start, end)` sobre `occurred_at` (C4).
- `get` devolve `None` para "não existe" — ausência legítima, não erro (§18).
- Cada método existe por um caso de uso desta fase (ROADMAP 1.3 + CLI). **Não** há
  paginação, busca textual, filtro composto nem leitura por offset — offset é
  necessidade da Fase 2 e será adicionado lá (`PHASE-1 §12`).

### `events/bus.py`

```python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1  # 1 = sem retry
    delay: float = 0.0  # segundos entre tentativas


@dataclass(frozen=True, slots=True)
class DeadLetter:
    event: RecordedEvent
    consumer: str
    attempts: int
    error: Exception


DeadLetterHandler = Callable[[DeadLetter], None]


class EventBus:
    def __init__(
        self,
        *,
        dead_letter_handler: DeadLetterHandler | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None: ...
    def subscribe(
        self,
        consumer: EventConsumer,
        *,
        event_types: Collection[str] | None = None,
        retry: RetryPolicy | None = None,
    ) -> None: ...
    def publish(self, event: RecordedEvent) -> None: ...
```

- `event_types=None` recebe tudo; caso contrário, match **exato** de `event_type`.
- **Acknowledgement:** retorno normal de `handle()` = ack; exceção = nack.
- **Retry:** reexecuta até `max_attempts`, dormindo `delay` entre tentativas
  (`sleep` injetável ⇒ testes instantâneos). Default: sem retry.
- **Isolamento:** cada consumer roda dentro do seu próprio `try/except Exception` —
  falha de um não impede os demais nem propaga para o publisher. Isso **não** é
  "esconder falha com `except` genérico" (§18): a exceção é logada com stack trace e
  roteada explicitamente para o dead-letter handler. `BaseException`
  (`KeyboardInterrupt`/`SystemExit`) não é capturada.
- **Dead letter:** esgotadas as tentativas → `ERROR` + `DeadLetter` para o handler
  (default: logar). Sem fila persistente — não há requisito para uma nesta fase.

### `events/publisher.py`

```python
class EventPublisher:
    def __init__(self, *, store: EventStore, bus: EventBus) -> None: ...
    def publish(self, event: Event) -> AppendResult:
        result = self._store.append(event)  # 1. durável + dedupe
        if result.is_duplicate:
            logger.info("event.duplicate", ...)  # 2. no-op: não republica
            return result
        self._bus.publish(result.event)  # 3. distribui
        return result
```

É o serviço de aplicação que fecha a subfase 1.5 ("criar fluxo completo"). Falha de
persistência propaga; falha de consumer não (D10).

---

## 7. Event Store SQLite e serialização

### Schema (`events/adapters/sqlite_store.py`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;          -- versão de schema, para migração futura simples

CREATE TABLE IF NOT EXISTS events (
    sequence       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT    NOT NULL UNIQUE,
    event_type     TEXT    NOT NULL,
    occurred_at    TEXT    NOT NULL,   -- ISO-8601 UTC, microssegundos
    recorded_at    TEXT    NOT NULL,   -- ISO-8601 UTC, atribuído pelo store
    source         TEXT    NOT NULL,
    schema_version INTEGER NOT NULL,
    correlation_id TEXT    NOT NULL,
    causation_id   TEXT,
    payload        TEXT    NOT NULL,   -- objeto JSON canônico
    metadata       TEXT    NOT NULL    -- objeto JSON canônico
);

CREATE INDEX IF NOT EXISTS events_event_type_idx     ON events(event_type);
CREATE INDEX IF NOT EXISTS events_correlation_id_idx ON events(correlation_id);
CREATE INDEX IF NOT EXISTS events_occurred_at_idx    ON events(occurred_at);

CREATE TRIGGER IF NOT EXISTS events_block_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_block_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
```

- Três índices, um por consulta obrigatória do ROADMAP 1.3 — nenhum índice
  especulativo (`PHASE-1 §12`).
- `sequence` é o desempate determinístico da ordenação quando dois `recorded_at`
  coincidem; **não** é exposto no domínio.
- API: `SqliteEventStore.open(database: Path | str)` (cria diretórios e schema, de
  forma idempotente), `close()`, context manager. Testes usam `":memory:"` e arquivo
  em `tmp_path`.
- `recorded_at = datetime.now(UTC)` no append — único lugar do sistema que define
  esse campo.
- `append` = `INSERT … ON CONFLICT(event_id) DO NOTHING`, seguido da leitura do
  registro efetivo (D5/D6).
- Erros: todo `sqlite3.Error` vira `EventAppendError` ou `EventReadError`
  (`raise … from exc`); nenhum `sqlite3.Row`/cursor atravessa a fronteira
  (contracts §11).
- Conexão única e síncrona, sem threading — o processo é single-threaded nesta fase.

### Erros (`events/errors.py`)

```text
JarvisError
├── DomainError            (retryable = False)
│   └── InvalidEventError          # validação de Event
└── InfrastructureError    (retryable = True)
    └── EventStoreError
        ├── EventAppendError       # falha ao persistir
        └── EventReadError         # falha ao recuperar
```

Não existe `DuplicateEventError` — duplicata é no-op por contrato (D5); o docstring
do módulo registra isso para não parecer omissão.

### Serialização (`events/adapters/serialization.py`)

- `StoredEvent` (`TypedDict`) espelha as colunas; `to_record(event, recorded_at)` e
  `from_record(record)` fazem a tradução — o domínio nunca vê colunas nem JSON.
- Datas: `dt.astimezone(UTC).isoformat()` (ordenação lexicográfica válida porque o
  offset é sempre `+00:00`); leitura via `datetime.fromisoformat`.
- JSON canônico: `json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False, default=…)`, com o `default` convertendo `MappingProxyType` em
  `dict` (D8 congela mappings, e `json` não os conhece).
- `payload_fingerprint(event) -> str`: SHA-256 do corpo canônico, usado só para o
  aviso de divergência do D6 — nunca loga conteúdo.
- Round-trip exato: `from_record(to_record(e, t)) == RecordedEvent(e, t)` (listas
  voltam como tuplas porque o domínio congela dos dois lados).

---

## 8. Observabilidade, segurança e CLI

### Observabilidade e segurança

- `configure_logging(level)` em `cli.py`, aplicando `settings.log_level` — que hoje
  existe e é ignorado (C1). Componentes usam `logging.getLogger(__name__)`.
- Logs estruturados via `extra=` com chaves fixas: `event_id`, `event_type`,
  `source`, `correlation_id`, `causation_id`, `consumer`, `attempt`
  ([contracts §14](architecture-contracts.md#14-observability-contract)).
- Registros previstos: `event.recorded` (INFO), `event.duplicate` (INFO),
  `event.duplicate_divergent` (WARNING), `event.consumer_failed` (WARNING por
  tentativa), `event.dead_letter` (ERROR), falhas de store (ERROR).
- **Nunca** são logados `payload` nem `metadata` — no máximo
  `payload_keys = sorted(payload)` (`PHASE-1 §19/§20`). O `LoggingEventConsumer`
  segue a mesma regra, e existe um teste que assere isso.
- Nenhum secret entra em evento, log ou banco; `data/` já está no `.gitignore`.

### CLI / Composition Root (`cli.py`)

```text
jarvis info                       # + linha com o caminho do event store
jarvis events emit --type T --source S --payload '<json>'
                   [--key NATURAL_KEY] [--occurred-at ISO8601]
                   [--correlation-id ID] [--causation-id ID] [--schema-version N]
jarvis events list [--type T] [--correlation-id C]
                   [--since ISO8601] [--until ISO8601] [--limit N]
```

- `emit` monta store + bus + `LoggingEventConsumer` + `EventPublisher`, publica e
  imprime o `event_id` e se foi duplicata. `--key` usa `deterministic_event_id`, o
  que torna a idempotência demonstrável na linha de comando.
- `--occurred-at` ausente ⇒ `datetime.now(UTC)`.
- `list` abre só o store e escolhe o método de leitura pelos filtros; sem filtro,
  `read_latest(limit)`.
- Códigos de saída: `0` ok; `2` entrada inválida (`InvalidEventError`, JSON malformado,
  data inválida); `1` falha de infraestrutura (`EventStoreError`). Mensagens em
  `stderr`, sem stack trace (contracts §13).
- `cli.py` continua sendo o **único** módulo que conhece Core, Infrastructure e
  Interfaces ao mesmo tempo (ADR-0001).

---

## 9. Dependências

**Nenhuma dependência nova, runtime ou dev.**

| Necessidade | Solução | Por que a stdlib basta |
|---|---|---|
| Persistência + índice único | `sqlite3` | embutido, transacional, com `UNIQUE` e triggers |
| Serialização | `json` | payload é JSON por contrato (D8) |
| Identificadores | `uuid` (v4/v5) | UUID5 dá o id determinístico do contrato §5 |
| Fingerprint | `hashlib` | SHA-256 |
| Imutabilidade | `dataclasses` + `types.MappingProxyType` | frozen + proxy cobrem o requisito |
| Logging | `logging` | contracts §14 pede log estruturado, não plataforma |
| Teste de arquitetura | `ast` | análise estática de imports sem lib externa |

`pyproject.toml` e `uv.lock` ficam intocados ⇒ `uv sync --locked` e a CI continuam
válidos.

---

## 10. Ordem de implementação

Sequência sem checkpoint humano; cada passo termina com os testes daquele passo
verdes.

1. Este documento (`docs/phase-1-plan.md`).
2. `src/jarvis/errors.py` + `events/errors.py` + `tests/test_events_errors.py`.
3. `events/event.py` + `tests/test_events_event.py`.
4. `events/ports.py` (Protocols + `AppendResult`).
5. `events/bus.py` + `tests/test_events_bus.py` (ROADMAP 1.2).
6. `events/adapters/serialization.py` + `tests/test_events_serialization.py`.
7. `events/adapters/sqlite_store.py` + `tests/test_events_sqlite_store.py` (1.3).
8. `events/adapters/logging_consumer.py` (1.4, testado junto do bus).
9. `events/publisher.py` + `tests/test_events_publisher.py`.
10. `events/__init__.py` (API pública) + `tests/test_events_architecture.py`.
11. `cli.py` (logging + subcomandos) + `tests/test_cli.py` atualizado.
12. `tests/test_events_integration.py` (1.5).
13. Documentação + ADR-0007/0008 + índices.
14. `ROADMAP.md` (checkboxes + histórico).
15. Gates de qualidade + commits.

---

## 11. Testes

### Domínio (`test_events_event.py`)

- `correlation_id` ausente vira o próprio `event_id`; presente é preservado.
- `occurred_at` naive ⇒ `InvalidEventError`; aware não-UTC ⇒ normalizado para UTC.
- `event_type` sem namespace, com maiúsculas ou vazio ⇒ erro; `source` inválido ⇒ erro.
- `schema_version` 0 ou negativo ⇒ erro; default é 1.
- **Imutabilidade:** atribuir a um campo ⇒ `FrozenInstanceError`; `payload["k"] = …`
  ⇒ `TypeError`; mapping e lista aninhados congelados; mutar o `dict` original depois
  de construir não afeta o evento.
- Payload com tipo não-JSON (`datetime`, `set`, objeto) ⇒ `InvalidEventError`.
- `deterministic_event_id` é estável entre chamadas e distinto por `source`/chave;
  `new_event_id` é único.
- `RecordedEvent` com `recorded_at` naive ⇒ erro.

### Erros (`test_events_errors.py`)

- Hierarquia: `InvalidEventError` é `DomainError`; `EventAppendError`/
  `EventReadError` são `EventStoreError` → `InfrastructureError`.
- `retryable`: `False` no ramo de domínio, `True` no de infraestrutura.

### Serialização (`test_events_serialization.py`)

- Round-trip exato com payload aninhado, unicode e todos os tipos JSON.
- JSON canônico: chaves ordenadas, sem espaços supérfluos, `ensure_ascii=False`.
- `causation_id=None` sobrevive ao round-trip.
- `payload_fingerprint` é estável para conteúdo igual em ordem de chave diferente e
  diverge para conteúdo diferente.

### Store (`test_events_sqlite_store.py`)

- Append + `get` devolve exatamente o mesmo `Event`.
- `recorded_at` é atribuído pelo store e é UTC (sem assumir relógio monotônico —
  ADR-0004).
- Ordenação estável de todas as leituras, inclusive com `occurred_at` fora de ordem.
- `read_by_type`, `read_by_correlation`, `read_occurred_between` (limites
  semiabertos), `read_latest`, com e sem `limit`.
- **Idempotência:** segundo append do mesmo `event_id` ⇒ `is_duplicate=True`,
  `recorded_at` original preservado, contagem de linhas inalterada.
- Duplicata divergente ⇒ no-op + `WARNING` (via `caplog`), conteúdo original mantido.
- **Imutabilidade:** `UPDATE`/`DELETE` diretos na tabela ⇒ `sqlite3` aborta.
- Persistência real: gravar, fechar, reabrir o mesmo arquivo, ler de volta.
- `open()` duas vezes sobre o mesmo arquivo não quebra (schema idempotente).
- Erro de infraestrutura: operar sobre conexão fechada ⇒ `EventAppendError`/
  `EventReadError`, nunca `sqlite3.Error` cru.

### Bus (`test_events_bus.py`)

- Entrega a todos os inscritos, em ordem de inscrição.
- Filtro por `event_types` (recebe só o que assinou; `None` recebe tudo).
- Consumer que levanta exceção não impede os demais nem propaga.
- Retry: `max_attempts=3` ⇒ 3 chamadas; sucesso na 2ª ⇒ para em 2, sem dead-letter;
  `sleep` fake registra os intervalos.
- Dead-letter após esgotar tentativas: recebe `event`, `consumer`, `attempts`, `error`.
- Handler default loga em `ERROR` (via `caplog`).
- `LoggingEventConsumer` loga metadados e **não** loga payload — asserção explícita
  de que o valor sensível não aparece no log.

### Publisher (`test_events_publisher.py`)

- Store é chamado antes do bus (ordem verificada com store fake instrumentado).
- Duplicata ⇒ bus não é acionado.
- Falha do store propaga e nada é publicado.
- Falha de consumer não impede o `AppendResult` de retornar sucesso.

### Arquitetura (`test_events_architecture.py`)

- Varredura AST de `src/jarvis/events/*.py` (exceto `adapters/`): nenhum importa
  `jarvis.events.adapters`, `sqlite3`, `jarvis.cli` ou `jarvis.config`.
- `src/jarvis/events/**` não importa nada de `jarvis` fora de `jarvis.events` e
  `jarvis.errors`.

### Integração (`test_events_integration.py`) — SQLite em arquivo real (`tmp_path`)

1. Emissão de um evento raiz e de um evento filho (`causation_id` apontando para o
   pai, mesmo `correlation_id`).
2. O consumer registrado recebe ambos, na ordem.
3. Reabrir o store e reconstruir a cadeia por `read_by_correlation`; `causation_id`
   permite remontar pai → filho.
4. Reemitir o evento raiz com o mesmo `event_id` ⇒ no-op; o consumer **não** recebe
   de novo.
5. Falha exposta: store fechado ⇒ `EventStoreError`.

### CLI (`test_cli.py`, ampliado)

- `events emit` com `JARVIS_DATA_DIR` apontando para `tmp_path`: sai 0 e imprime o id.
- `events emit --key X` duas vezes: a segunda reporta duplicata, sai 0, store com uma
  linha.
- `events list` mostra o evento emitido; `--type`/`--correlation-id`/`--limit` filtram.
- JSON de payload inválido ⇒ exit 2, mensagem em `stderr`, sem stack trace.
- Testes existentes (`--version`, `info`, help) continuam passando.

A estrutura de testes permanece **plana** em `tests/` (`CLAUDE.md §4`) — sem
`tests/unit/`, `tests/integration/` ou `tests/architecture/`. Nenhum teste toca rede
ou serviço externo.

---

## 12. Documentação e ADRs

- **ADR-0007 — SQLite como armazenamento do Event Store** (D4): decisão,
  alternativas (PostgreSQL, JSONL, in-memory), consequências (dois bancos a partir da
  Fase 3; troca isolada pelo port).
- **ADR-0008 — Event Bus síncrono em processo** (D9): decisão, alternativas (asyncio,
  broker externo, sem retry/dead-letter), consequências (todo consumer futuro é
  síncrono).
- `docs/adr/README.md`: duas linhas no índice.
  `architecture-contracts.md §15`: duas linhas na lista de ADRs. **Nada mais nos
  contratos** — os campos de `Event` já estavam definidos em §5, e a implementação
  apenas os materializa (`CLAUDE.md §8`).
- `docs/event-system.md`: perde o aviso "não implementa" e ganha seções sobre o que
  passa a existir (módulos e API pública, `Event` vs. `RecordedEvent`, schema SQLite,
  semântica de ack/retry/dead-letter, comandos de CLI, e o que **não** foi
  implementado e por quê), referenciando contratos e ADRs em vez de repeti-los.
- `docs/README.md`: a linha de `event-system.md` passa de "conceitual" para
  "implementação (Fase 1)".
- `CLAUDE.md §2`: árvore atualizada e parágrafo de estado reescrito. Nenhuma regra
  alterada.
- `README.md`: status "Fase 1 — Event System", uso do `jarvis events`, e nota de que
  os dados ficam em `data/events.db`.

**Sem ADR** para: a dupla `Event`/`RecordedEvent` (materializa o ADR-0004), dataclass
em vez de pydantic (reversível e interno a um componente) e nomes de campos/métodos
([`adr/README.md`](adr/README.md) exclui explicitamente esse tipo de decisão).

---

## 13. Validação

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run jarvis --version
uv run jarvis info
uv run jarvis events emit --type demo.checked --source manual-cli --payload '{"ok":true}' --key smoke-1
uv run jarvis events emit --type demo.checked --source manual-cli --payload '{"ok":true}' --key smoke-1   # duplicata
uv run jarvis events list --limit 5
```

A CI ([`ci.yml`](../.github/workflows/ci.yml)) roda os cinco primeiros comandos, sem
alteração no workflow.

---

## 14. Git

Um commit por subfase, na ordem do `ROADMAP.md`, mais três de borda. Sem `push`, sem
`--no-verify`, sem tocar em histórico publicado. Cada commit deixa a suíte verde.

| # | Mensagem | Conteúdo |
|---|---|---|
| 1 | `docs: record phase 1 specification and plan` | `PHASE-1.md`, `docs/phase-1-plan.md` (resolve C6) |
| 2 | `feat: implement event domain` | `errors.py`, `events/{event,errors,ports}.py` + testes (1.1) |
| 3 | `feat: implement event bus` | `events/bus.py` + testes (1.2) |
| 4 | `feat: implement persistent event store` | `adapters/{serialization,sqlite_store}.py` + testes (1.3) |
| 5 | `feat: implement event consumers` | `adapters/logging_consumer.py` + testes (1.4) |
| 6 | `feat: complete event-driven core` | `publisher.py`, `events/__init__.py`, `cli.py`, testes de integração/arquitetura/CLI (1.5) |
| 7 | `docs: document event system implementation` | ADR-0007/0008, `event-system.md`, `docs/README.md`, `adr/README.md`, contracts §15, `CLAUDE.md`, `README.md` |
| 8 | `chore: complete event system milestone` | `ROADMAP.md` (checkboxes 1.1–1.5, "FASE 1 CONCLUÍDA", M1, histórico) |

Working tree limpo ao final; nenhum arquivo temporário, nenhum secret, `data/`
continua ignorado.

---

## 15. Critérios de conclusão

- [ ] ROADMAP 1.1–1.5: todos os itens implementados e verificados por teste.
- [ ] `Event` imutável no domínio **e** na persistência (triggers).
- [ ] `occurred_at` (producer) e `recorded_at` (store) separados por tipo, não por
      convenção.
- [ ] Idempotência real: `UNIQUE` no banco, no-op no append, sem republicação no bus.
- [ ] `correlation_id` e `causation_id` distintos, com cadeia causal reconstruível.
- [ ] Consultas por tipo, temporal e por `correlation_id` funcionando sobre SQLite.
- [ ] Core não importa adapters (teste de arquitetura verde).
- [ ] Erros explícitos e classificados; nenhum `except Exception` que esconda falha.
- [ ] Nenhum payload em log; nenhum secret versionado.
- [ ] `ruff format --check`, `ruff check`, `mypy` e `pytest` verdes; CLI funcionando.
- [ ] Documentação e ADRs atualizados; `ROADMAP.md` marcado.
- [ ] Commits criados, working tree limpo, **nenhum push**.

---

## 16. Fora de escopo

Context, Memory, Agent Runtime, LLM/Embedding, Policy, Skills, Tool Router, MCP,
STT/TTS, wake word, UI, Docker, deployment e autenticação. Dentro do próprio Event
System: bus assíncrono, broker externo, dead-letter queue persistente, leitura por
offset/cursor, paginação, busca textual, migrações de schema, upcasting de
`schema_version`, event sources reais (Gmail etc.) e qualquer port sem consumidor
nesta fase.

---

## 17. Desvios em relação ao plano

Todos pequenos, reversíveis e dentro da autonomia prevista em `PHASE-1.md §27`
("nomes de arquivos", "organização interna", "escolhas triviais de teste").

| Desvio | Motivo |
|---|---|
| `tests/factories.py` acrescentado | Construtores de `Event`/`RecordedEvent` com defaults válidos, compartilhados por seis arquivos de teste; evita repetir o envelope inteiro quando só um campo importa. Módulo plano em `tests/`, sem subdiretório novo. |
| `tests/test_events_logging_consumer.py` como arquivo próprio | O plano previa testar o `LoggingEventConsumer` junto do bus. Separar mantém cada arquivo espelhando um módulo e deixa o commit da subfase 1.4 autocontido. |
| `payload_fingerprint` renomeado para `event_fingerprint` | O resumo cobre o envelope inteiro (tipo, tempos, origem, correlação, payload e metadata), não só o payload; o nome antigo descrevia menos do que a função faz. |
| `SqliteEventStore` recebe um `clock` injetável | Permite verificar que `recorded_at` é atribuído pelo store e que uma duplicata preserva o `recorded_at` original, sem depender do relógio real. |
| `Event.correlation_id` permanece tipado `str \| None` | Depois da construção nunca é nulo, mas o tipo declarado não expressa isso. Em vez de `cast`/`assert`, a garantia fica no `NOT NULL` da coluna: se a invariante quebrar, o insert falha em vez de gravar nulo. |
| `errors.py` do Event System ficou sem `EventConsumerError` | Falha de consumer não vira exceção de domínio: ela é roteada para retry/dead letter pelo bus, então uma classe de erro para isso não teria consumidor. |
