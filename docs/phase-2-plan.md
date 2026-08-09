# Plano de implementação — Fase 2: Context Engine

> Plano técnico da **Fase 2** do [roadmap](../ROADMAP.md), produzido em sessão de
> planejamento dedicada e revisado antes da implementação. Complementa
> [`../PHASE-2.md`](../PHASE-2.md) (especificação da fase) — o `ROADMAP.md`
> continua sendo a fonte de verdade sobre escopo, e
> [`architecture-contracts.md`](architecture-contracts.md) + [ADRs](adr/) sobre
> arquitetura. Este documento **não redefine** contrato nenhum: decide *como*
> materializar em código o que já está decidido.
>
> **Estado:** aprovado com ajustes; aguardando início da implementação.

---

## 1. Contexto e estado inicial

### 1.1 Ponto de partida inspecionado

- **Commit:** `c40cb54` (`chore: complete event system milestone`), branch `main`.
- **Working tree:** limpo, exceto `PHASE-2.md` **untracked** (ver conflito **C6**).
- **Fases concluídas:** 0 (Foundation) e 1 (Event System), com histórico marcado no
  `ROADMAP.md`.

### 1.2 Estrutura real hoje

```text
src/jarvis/
├── __init__.py  __main__.py  cli.py  config.py  errors.py
└── events/  event.py  errors.py  ports.py  bus.py  publisher.py
    └── adapters/  serialization.py  sqlite_store.py  logging_consumer.py
tests/            13 arquivos planos + factories.py
docs/             architecture{,-contracts}.md, event-system.md, context-system.md (conceitual),
                  phase-1-plan.md, adr/0001–0008
```

`pyproject.toml`: Python 3.13, mypy `strict`, Ruff (`E,F,I,UP,B,SIM,RUF`,
`line-length=100`), pytest `--strict-markers --strict-config`, `testpaths=["tests"]`.
Dependência de runtime única: `pydantic-settings`. CI
([`ci.yml`](../.github/workflows/ci.yml)) roda `uv sync --locked`,
`ruff format --check .`, `ruff check .`, `mypy`, `pytest`.

### 1.3 Integrações reais da Fase 1 que a Fase 2 consome

Verificadas no código, com arquivo e assinatura:

| O que | Onde | Assinatura real |
|---|---|---|
| Fato imutável | `events/event.py:121` | `Event(event_id, event_type, occurred_at, source, payload, schema_version=1, correlation_id=None, causation_id=None, metadata={})`, `frozen/slots/kw_only`; `payload` congelado recursivamente para tipos JSON |
| Fato persistido | `events/event.py:178` | `RecordedEvent(event: Event, recorded_at: datetime)` — só o store constrói |
| Contrato de consumer | `events/ports.py:66` | `EventConsumer` Protocol: `name: str` (property) + `handle(event: RecordedEvent) -> None` |
| Contrato de store | `events/ports.py:35` | `append`, `get`, `read_by_type(event_type, *, limit=None)`, `read_by_correlation`, `read_occurred_between(start, end, *, limit=None)`, `read_latest(*, limit)` — **toda leitura em ordem de persistência ascendente** |
| Distribuição | `events/bus.py:84` | `EventBus.subscribe(consumer, *, event_types=None, retry=None)`; `publish(RecordedEvent)`; ack = retorno, nack = exceção; `RetryPolicy(max_attempts=1, delay=0.0)`; dead-letter via handler injetado |
| Ordem correta | `events/publisher.py:30` | `EventPublisher.publish(event) -> AppendResult`: **`store.append` → se `is_duplicate` retorna sem republicar → `bus.publish`** |
| Taxonomia base | `errors.py` | `JarvisError` → `DomainError` (`retryable=False`) / `InfrastructureError` (`retryable=True`) |
| Composition root | `cli.py:1` | único módulo que conhece Core + Infrastructure + Interfaces; `configure_logging`, `load_settings()`, `SqliteEventStore.open(path)` |
| Config | `config.py` | `Settings(env, log_level, data_dir)`, prefixo `JARVIS_` |
| Padrão físico | `events/` + `events/adapters/` | Core na raiz do pacote, Infrastructure em `adapters/`, fronteira verificada por AST em `tests/test_events_architecture.py` |

Consequências diretas para o plano:

1. O Context Engine é um **consumer síncrono**: `handle()` roda na thread de quem
   publicou (ADR-0008) e **não pode** fazer I/O — nem gravar snapshot.
2. Duplicatas nunca chegam ao bus (`publisher.py:33-42`), então a idempotência de
   `handle()` é defesa adicional (chamada direta, reconstrução, evolução futura),
   não a defesa primária.
3. Falha de consumer não desfaz o evento nem propaga ao publisher — retry e
   dead-letter já existem e **não** serão duplicados no Context Engine.
4. `RecordedEvent` dá `occurred_at` (tempo de domínio) e `recorded_at` (tempo de
   registro, base da ordenação estável do store); o contexto precisa de um terceiro
   tempo, `observed_at`.

---

## 2. Conformidade com o roadmap

Cada item de 2.1–2.5 do `ROADMAP.md`, o arquivo que o materializa, o teste e o
critério de aceitação observável.

### 2.1 — Context Domain → `feat: implement context domain`

| Item do roadmap | Arquivo(s) | Teste(s) | Critério de aceitação |
|---|---|---|---|
| Definir `CurrentContext` | `context/model.py` | `test_context_model.py` | frozen; agrega os 7 subcontextos + `as_of`; projeção derivada, nunca fonte de verdade; nenhum `dict[str, Any]` |
| Definir `UserContext` | `context/model.py` | idem | `availability: Observation[str] \| None` — produtor: evento `user.availability_changed` |
| Definir `EnvironmentContext` | `context/model.py` | idem | `local_time` (Time Provider) e `place` (produtor só em teste — ver **C2**) |
| Definir `DeviceContext` | `context/model.py` | idem | `device_id` — produtor: Device Provider |
| Definir `ActivityContext` | `context/model.py` | idem | `current: Observation[str \| None] \| None` — produtor: eventos `user.activity_started`/`user.activity_ended` |
| Definir `ScheduleContext` | `context/model.py` | idem | `next_entry_at` (produtor só em teste — **C2**) |
| Definir `ConversationContext` | `context/model.py` | idem | `active_id`, **sem produtor nesta fase** (**C3**) |
| Definir `TaskContext` | `context/model.py` | idem | `active_id`, **sem produtor nesta fase** (**C3**) |
| Definir timestamps e validade dos dados | `context/observation.py`, `context/freshness.py` | `test_context_observation.py`, `test_context_freshness.py` | `Observation` com `observed_at` tz-aware, `source`, `confidence ∈ [0,1]`, `ttl`; `Freshness.FRESH/STALE` derivada; `TtlPolicy` por campo |

### 2.2 — Context Providers → `feat: implement context providers`

| Item | Arquivo(s) | Teste(s) | Critério |
|---|---|---|---|
| Criar interface `ContextProvider` | `context/ports.py` | `test_context_architecture.py` | Protocol `name` + `observe(now) -> ContextUpdate`; múltiplas fontes independentes ⇒ port justificado |
| Criar Time Provider | `context/adapters/time_provider.py` | `test_context_providers.py` | clock e `tzinfo` injetáveis; produz `local_time`; nenhum teste dorme |
| Criar Device Provider | `context/adapters/device_provider.py` | idem | `platform.node()` da stdlib; sem automação de SO; função injetável |
| Criar Activity Provider | port + double (`tests/context_doubles.py`) | idem | **C2** — nada observável com segurança sem automação de SO; o port é exercido por um double, não por um adapter que finge integração |
| Criar Calendar Provider | port + double | idem | **C2** — PHASE-2 §8: "interface/double sem OAuth ou integração de produção" |
| Criar Location Provider | port + double | idem | **C2** — PHASE-2 §8: "interface/double sem rastreamento real" |
| Criar mocks para testes | `tests/context_doubles.py` | usados por ≥6 arquivos | `StubProvider`, `FailingProvider`, `SpyRepository`, `FakeSnapshotRepository`, `frozen_clock`; doubles vivem em `tests/`, **nunca** em `src/` |

### 2.3 — Context Aggregation → `feat: implement context aggregation`

| Item | Arquivo(s) | Teste(s) | Critério |
|---|---|---|---|
| Criar Context Aggregator | `context/aggregator.py` | `test_context_aggregator.py` | classe concreta de Core (sem port: implementação única, nenhum substituto real) |
| Coletar dados dos providers | `context/aggregator.py` | idem | `refresh()` percorre providers na ordem de registro; falha declarada degrada, não apaga |
| Resolver conflitos | `context/projection.py` | `test_context_projection.py` | `observed_at` mais recente vence por campo; empate → incumbente permanece; conflito devolvido em `ContextConflict` **e** logado |
| Controlar validade dos dados | `context/freshness.py`, `context/projection.py` | `test_context_freshness.py` | TTL por campo carimbado na merge; `fresh → stale` no vencimento, sem descarte |
| Implementar timestamps | `context/observation.py`, `context/model.py` | `test_context_observation.py` | `observed_at`, `as_of`, `captured_at` — três tempos distintos, todos tz-aware UTC |
| Criar `get_current_context` | `context/aggregator.py` | `test_context_aggregator.py` | leitura pura, sem I/O e sem poll; `as_of = clock()` |
| Criar testes | — | acima | cobertura de comportamento, não contagem |

### 2.4 — Context Snapshots → `feat: implement context snapshots`

| Item | Arquivo(s) | Teste(s) | Critério |
|---|---|---|---|
| Definir snapshot | `context/snapshot.py` | `test_context_snapshot.py` | `ContextSnapshot` frozen com `snapshot_id`, `captured_at`, `context`; preserva `source`/`observed_at`/`confidence`/`ttl` de cada campo |
| Persistir snapshots relevantes | `context/ports.py`, `context/adapters/sqlite_snapshots.py`, `context/engine.py` | `test_context_sqlite_snapshots.py`, `test_context_engine.py` | port `ContextSnapshotRepository`; captura só por pedido explícito **e** só se o conteúdo mudou (fingerprint) |
| Implementar consulta histórica | port + adapter | `test_context_sqlite_snapshots.py` | `read_captured_between(start, end, *, limit, include_expired)` e `latest()`, ordem de captura ascendente |
| Implementar expiração | port + adapter | idem | **expiração lógica** (`expire_before(cutoff)` marca `expired_at`), explícita, auditável, nunca automática; **nada é apagado** (**C7**) |
| Criar testes | — | acima | round-trip real em SQLite de arquivo; imutabilidade verificada atacando o banco por fora |

### 2.5 — Context Integration → `feat: complete context engine`

| Item | Arquivo(s) | Teste(s) | Critério |
|---|---|---|---|
| Integrar Event System | `context/consumer.py` | `test_context_consumer.py` | `ContextEventConsumer` satisfaz `EventConsumer` estruturalmente; assinatura no bus com lista explícita de tipos |
| Integrar Context Engine | `context/engine.py`, `cli.py` | `test_cli.py` | composition root instancia providers, aggregator, consumer e repositório, e assina o consumer no bus |
| Atualizar contexto a partir de eventos | `context/consumer.py` | `test_context_consumer.py` | 3 `event_type` mapeados explicitamente (**C13**); tipo/versão desconhecidos ignorados com log; `handle` sem I/O |
| Validar consistência | `context/engine.py` (`rebuild_from`) | `test_context_integration.py` | reconstruir do Event Store **na ordem de persistência** produz o mesmo `CurrentContext` que a aplicação incremental |
| Testar fluxo completo | — | `test_context_integration.py` | `Event → EventPublisher → EventBus → ContextEventConsumer → get_current_context() → snapshot → consulta` com SQLite real |

---

## 3. Conflitos, ambiguidades e pressupostos

Registrados em vez de resolvidos silenciosamente (`CLAUDE.md §10`). Classificação:
**[C]** resolvido pelo contrato · **[D]** decisão pequena e reversível ·
**[A]** decisão que exigiria ADR · **[B]** bloqueador.

| # | Tipo | Questão | Fontes | Resolução |
|---|---|---|---|---|
| C1 | **D** | `events/ports.py:10-11` e `docs/event-system.md` afirmam que leitura por offset/cursor "é necessidade da Fase 2 e será acrescentada lá". | `events/ports.py`; `event-system.md` | A necessidade **não se materializou nesta fase**: a reconstrução (§7.5) usa `read_by_type()` e reordena por `recorded_at`, que o `RecordedEvent` já expõe. O port **não é ampliado** agora. As duas frases são corrigidas para dizer isso e para nomear o gatilho concreto de revisão (§12.1). Isso **não** é uma afirmação de que cursor nunca será necessário. |
| C2 | **D** | ROADMAP 2.2 exige "Criar Activity/Calendar/Location Provider"; PHASE-2 §8 admite "interface/double" para Calendar e Location; `CLAUDE.md §11` e PHASE-2 §5 proíbem integração externa. | ROADMAP 2.2; PHASE-2 §5/§8 | Em `src/` ficam apenas os dois providers com dado local genuíno: **Time** e **Device**. Activity, Calendar e Location são atendidos por **port + doubles em `tests/`**, que provam que o port suporta essas fontes sem que o repositório passe a conter adapters que aparentam integração pronta. Se a revisão preferir adapters "de valor declarado" em `src/`, é uma troca pequena e reversível — mas o default deste plano é não simular funcionalidade. |
| C3 | **C/D** | ROADMAP 2.1 exige os sete subcontextos; contracts §1 proíbe "abstração sem consumidor real". `ConversationContext` e `TaskContext` não têm produtor concreto nesta fase. | ROADMAP 2.1; contracts §1 | ROADMAP prevalece (CLAUDE §0.1). Os sete existem, cada um com **exatamente um** campo. `ConversationContext.active_id` e `TaskContext.active_id` ficam **sem produtor** e permanentemente ausentes na Fase 2 — o que é a semântica correta de "ausência não observada" e é exercitado pelos testes de serialização/ausência. Produtor real chega com Voice (Fase 6) e Background Task Manager (Fase 7). Nada é inventado para preenchê-los. |
| C4 | **D** | PHASE-2 §10 permite relacionar o snapshot a `correlation_id`/`causation_id` "quando ela existir"; na Fase 2 não existe produtor dessa relação. | PHASE-2 §10 | `ContextSnapshot` não recebe esses campos agora — seriam campos sem produtor. Adiado para a fase em que uma decisão/ação dispara a captura (4/7). Acrescentar campo opcional depois não quebra o schema (§8.3). |
| C5 | **D** | `CLAUDE.md §2` descreve a árvore e afirma que "não há Context Engine"; ficará desatualizado. | CLAUDE.md §2 | Atualização factual da §2 (mesmo tratamento do C5 da Fase 1). Nenhuma regra alterada. |
| C6 | **D** | `PHASE-2.md` está untracked; a DoD exige árvore limpa. | git status; PHASE-2 §14 | Versionar `PHASE-2.md` + este plano no primeiro commit da fase. |
| C7 | **D** | ROADMAP 2.4 exige "Implementar expiração"; PHASE-2 §10 proíbe apagar em silêncio evidência auditável; ADR-0007/§8 tratam registros como imutáveis. | ROADMAP 2.4; PHASE-2 §10 | **Expiração é lógica, não física.** `expire_before(cutoff)` marca `expired_at`, exclui o snapshot das consultas por default e devolve a contagem; nada é removido do banco. `DELETE` continua bloqueado por trigger, e o conteúdo do snapshot continua imutável (trigger de `UPDATE` restrito às colunas de conteúdo). Isso cumpre o roadmap com a solução menor que preserva auditabilidade — e por isso **nenhum ADR novo é necessário** (§12.2). |
| C8 | **C** | Snapshots precisam ser persistidos; consumer não pode fazer I/O bloqueante. | PHASE-2 §3/§9; ADR-0008 | `handle()` **nunca** toca no repositório: só muta a projeção em memória. Captura é sempre acionada pelo composition root. Teste: um `SpyRepository` não recebe chamada alguma durante `handle`. |
| C9 | **D** | ROADMAP 2.3 diz "Implementar timestamps" sem dizer quais. | ROADMAP 2.3; PHASE-2 §6.2 | Três tempos nomeados e distintos: `Observation.observed_at` (quando a observação ocorreu), `CurrentContext.as_of` (quando a projeção foi lida), `ContextSnapshot.captured_at` (quando a captura foi feita). Nenhum se confunde com `occurred_at`/`recorded_at`. Todos tz-aware, normalizados para UTC. |
| C10 | **D** | contracts §13 prevê a categoria `ProviderError`; `errors.py` ainda não a tem. | contracts §13; `errors.py` | `ContextProviderError` herda de `InfrastructureError` (falha local de adapter). A base compartilhada `ProviderError` (LLM/MCP/API externa) **não** é criada agora — não teria segundo consumidor; entra na Fase 4. Mesmo critério do D12 da Fase 1. |
| C11 | **D** | contracts §6 fixa "`observed_at` mais recente vence por campo", mas não define o empate. | contracts §6; PHASE-2 §6.4 | Menor regra determinística compatível com o contrato: **empate ⇒ o incumbente permanece** (§4.5). É documentada e testada, mas fica como detalhe de implementação — **não** vira regra arquitetural global e **não** gera ADR. `confidence` e `source` **não** são usados como critério de desempate. |
| C12 | **D** | A reconstrução precisa de uma ordem quando o resultado depende dela (ex. `activity_started` seguido de `activity_ended`). | PHASE-2 §6.4/§9; ADR-0004 | A reconstrução respeita a **ordem de persistência** que o store já fornece, reordenando os eventos lidos por `recorded_at` (§7.5). Empates de `recorded_at` entre tipos diferentes não são desempatáveis com o port atual (`sequence` não é exposto) — limitação registrada, com gatilho concreto de revisão. |
| C13 | **D** | Quantos `event_type` a Fase 2 deve projetar? | ROADMAP 2.5; PHASE-2 §9 | Três, o menor conjunto representativo que demonstra o fluxo e cobre substituição, ausência observada e idempotência: `user.availability_changed`, `user.activity_started`, `user.activity_ended` (§7.1). Nada de agenda, localização, conversa ou tarefa — são fontes das Fases 5–7. |

**Nenhum bloqueador.** Nenhum contrato ou ADR aceito é alterado para acomodar o
plano.

---

## 4. Desenho do domínio

Formato de decisão: **decisão → motivo → alternativas → impacto → reversibilidade**.

### 4.1 D1 — Padrão físico: `src/jarvis/context/` + `context/adapters/`

Repete o D1 da Fase 1. **Motivo:** ADR-0001 ("Alternativas consideradas") e
`CLAUDE.md §1` proíbem a separação global em `domain/`/`application/`/
`infrastructure/`; um `adapters/` interno dá fronteira **verificável por teste**.
**Alternativas:** quatro pastas top-level (proibida); módulos planos com sufixo no
nome (a fronteira viraria convenção, não teste). **Impacto:** nenhum conceito novo.
**Reversibilidade:** alta.

### 4.2 D2 — `Observation[T]`: o valor observado com seus próprios metadados

```python
class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True, kw_only=True)
class Observation[T]:
    value: T
    observed_at: datetime  # tz-aware, normalizado para UTC
    source: str  # "provider:time" | "event:user.activity_started"
    confidence: float = 1.0  # 0.0 ≤ c ≤ 1.0
    ttl: timedelta | None = None  # carimbado pela TtlPolicy na merge

    def expires_at(self) -> datetime | None: ...
    def freshness(self, now: datetime) -> Freshness: ...
```

- **Motivo:** PHASE-2 §6.2 exige valor tipado + `observed_at` + `source` +
  `confidence` + regra de TTL + estado de validade, e proíbe `dict[str, Any]`. Um
  genérico frozen dá tudo isso **com o tipo do valor preservado**.
- **Invariantes** (violação ⇒ `InvalidContextError`): `observed_at` tz-aware
  (naive é recusado, como `Event.occurred_at`) e normalizado para UTC; `source`
  não vazio; `0.0 ≤ confidence ≤ 1.0` e finito; `ttl`, se presente, estritamente
  positivo.
- **Freshness é derivada, nunca armazenada:** `ttl is None` ⇒ sempre `FRESH`;
  senão `FRESH` enquanto `now < observed_at + ttl`. Vencer marca `STALE` — o valor
  **permanece** acessível (contrato §6). `confidence` **não** participa de
  freshness nem de resolução de conflito: é metadado de proveniência para quem
  consumir o contexto no futuro (Agent Runtime), como manda contracts §6.
- **Alternativas:** dois tipos (`Observation` + `ContextValue` com TTL) — duplica
  o modelo sem ganho; TTL global no `CurrentContext` — proibido por contracts §6;
  `dict[str, Any]` por subcontexto — proibido por PHASE-2 §6.1.
- **Variância:** `T` aparece só em posição de leitura num dataclass frozen, então a
  inferência de variância de PEP 695 o torna covariante — necessário para o helper
  de enumeração de campos (§4.6). *Fallback* se o mypy strict recusar: um Protocol
  `ObservationView` com propriedades somente-leitura, usado apenas nesse helper.
  Ambos internos ao pacote e reversíveis.
- **Reversibilidade:** média (afeta o pacote `context`, nada fora dele).

### 4.3 D3 — Ausência não observada ≠ ausência observada

| Situação | Representação | Significado |
|---|---|---|
| Nunca houve dado | `campo is None` | O Context Engine não sabe nada. **Nunca infere** (contracts §6). |
| Alguém observou que não há | `Observation[X \| None](value=None, …)` | Fato positivo, com origem, tempo e confiança. |

**Caso concreto único nesta fase:** `user.activity_ended`, que afirma que não há
atividade corrente. Só `ActivityContext.current` usa o tipo `Observation[str | None]`;
os demais campos usam `Observation[X] | None`. A distinção existe porque há um caso
real, não por simetria — se um segundo caso aparecer, o padrão já está definido.

- **Alternativas:** um enum com membro `IDLE`/`NONE` — inventaria um estado
  semântico que o evento não afirma; apagar o campo — destruiria proveniência.
- **Reversibilidade:** alta.

### 4.4 D4 — Valores são identificadores, rótulos e tempos; nunca texto livre

Nenhum campo de contexto carrega assunto de email, título de reunião, conteúdo de
conversa ou coordenada geográfica. Rótulos (`availability`, `place`, `current`)
são validados como **slug curto** (`^[a-z0-9][a-z0-9_-]*$`, ≤ 32 caracteres) por um
helper `require_label`; identificadores são strings não vazias; tempos são
datetimes tz-aware.

- **Motivo:** PHASE-2 §11 e `CLAUDE.md §11` — um modelo que **não pode** conter
  dado pessoal livre é estruturalmente mais seguro do que um que apenas promete
  não logá-lo, e snapshots são persistidos em disco.
- **Alternativas:** enums fechados por campo (inventariam taxonomias de atividade/
  disponibilidade que nenhuma fonte real desta fase define); `str` sem validação
  (admitiria texto livre e PII).
- **Reversibilidade:** alta (fechar um rótulo em enum depois é aditivo).

### 4.5 D5 — Conflito: a menor regra determinística compatível com o contrato

Para cada campo, dados o valor corrente e o incidente:

1. se um dos dois é ausente, o outro vence;
2. senão, vence o de **`observed_at` mais recente** — a regra literal de
   contracts §6;
3. em **empate de `observed_at`**, o incumbente permanece.

Há **conflito** quando ambos estão presentes e `value` difere. O conflito é
devolvido em `ContextConflict(field, winner_source, loser_source,
winner_observed_at, loser_observed_at)` **e** logado (`context.conflict`, INFO,
sem valores). Nada é descartado em silêncio.

- **Motivo:** contracts §6 já fixa o critério; a única lacuna era o empate. A regra
  3 é a menor decisão determinística possível, e é o que torna a reaplicação da
  **mesma** observação um no-op — a propriedade de idempotência que PHASE-2 §9
  exige do consumer.
- **Alternativas:** `confidence` como desempate (contracts §6 usa `confidence`
  como metadado de proveniência, não como autoridade de resolução — promovê-lo
  seria criar regra arquitetural nova sem necessidade); ordem lexicográfica de
  `source` (arbitrária e sem respaldo contratual); estratégias plugáveis por campo
  (proibidas até haver caso de uso concreto, contracts §6 e PHASE-2 §6.4).
- **Escopo:** regra de implementação, documentada e testada; **não** é uma regra
  arquitetural global e **não** gera ADR (C11). Se um caso concreto futuro exigir
  desempate mais rico, a decisão será tomada com esse caso na mão.
- **Impacto:** quando duas fontes disputam o mesmo campo com o mesmo
  `observed_at`, o resultado depende da ordem de aplicação — por isso a
  reconstrução respeita a ordem de persistência (§7.5) em vez de assumir que a
  ordem é irrelevante.
- **Reversibilidade:** alta (regra local à `projection.py`, coberta por testes).

### 4.6 D6 — `ContextField`: identidade tipada de campo

`ContextField` é um `StrEnum` com os oito campos. É a chave usada por: `TtlPolicy`,
logs de conflito/atualização, listagem de campos `stale` e serialização de
snapshot. Um helper explícito
`iter_fields(context) -> Iterator[tuple[ContextField, Observation[object] | None]]`
(oito linhas literais, **sem reflexão**) evita repetir a enumeração em quatro
lugares.

- **Motivo:** sem identidade de campo, TTL e log de conflito voltariam a ser
  strings soltas — o "magic number espalhado" que PHASE-2 §6.3 proíbe.
- **Alternativa:** `getattr` por nome de atributo — reintroduz `Any` e quebra o
  refactor seguro.
- **Reversibilidade:** alta.

### 4.7 Modelo concreto — oito campos, nenhum enum de domínio

```python
# context/model.py
@dataclass(frozen=True, slots=True, kw_only=True)
class UserContext:          availability:  Observation[str] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class EnvironmentContext:   local_time:    Observation[datetime] | None = None
                            place:         Observation[str] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class DeviceContext:        device_id:     Observation[str] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityContext:      current:       Observation[str | None] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduleContext:      next_entry_at: Observation[datetime] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationContext:  active_id:     Observation[str] | None = None
@dataclass(frozen=True, slots=True, kw_only=True)
class TaskContext:          active_id:     Observation[str] | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class CurrentContext:
    as_of: datetime          # tz-aware; instante da leitura
    user: UserContext = UserContext()
    environment: EnvironmentContext = EnvironmentContext()
    device: DeviceContext = DeviceContext()
    activity: ActivityContext = ActivityContext()
    schedule: ScheduleContext = ScheduleContext()
    conversation: ConversationContext = ConversationContext()
    task: TaskContext = TaskContext()

@dataclass(frozen=True, slots=True, kw_only=True)
class ContextUpdate:
    """Observações plana e tipadamente nomeadas — a moeda entre providers/consumer
    e a projeção. Campo `None` = 'esta fonte não fala disso'."""
    availability:  Observation[str] | None = None
    local_time:    Observation[datetime] | None = None
    place:         Observation[str] | None = None
    device_id:     Observation[str] | None = None
    current:       Observation[str | None] | None = None
    next_entry_at: Observation[datetime] | None = None
    conversation:  Observation[str] | None = None
    task:          Observation[str] | None = None

    def is_empty(self) -> bool: ...
```

`ContextUpdate` é o que **evita** `dict[str, Any]` sem tornar o modelo abstrato:
plano, totalmente tipado, um campo por `ContextField`. Todos os dataclasses são
`frozen` — imutabilidade imposta pela linguagem, como na Fase 1. Nenhum enum de
domínio, nenhuma dataclass auxiliar (`ScheduleEntry`, refs de conversa/tarefa):
tudo o que a Fase 2 precisa cabe em rótulo, identificador e datetime, e inventar
tipos ricos agora seria antecipar as fontes das Fases 5–7.

### 4.8 TTL por campo (`context/freshness.py`)

```python
@dataclass(frozen=True, slots=True)
class TtlPolicy:
    ttl_by_field: Mapping[ContextField, timedelta | None]

    def ttl_for(self, field: ContextField) -> timedelta | None: ...
```

| Campo | TTL | Por quê |
|---|---|---|
| `LOCAL_TIME` | 1 min | leitura de relógio envelhece imediatamente |
| `PLACE` | 15 min | contracts §6: "localização expira em minutos" |
| `DEVICE_ID` | — | identidade do dispositivo não envelhece sozinha |
| `AVAILABILITY` | 4 h | disponibilidade declarada vale por um turno |
| `ACTIVITY` | 1 h | atividade sem novo sinal é suposição velha |
| `NEXT_ENTRY_AT` | 15 min | contracts §6: "calendário expira no próximo poll" |
| `CONVERSATION` | 30 min | conversa sem novo sinal provavelmente terminou |
| `TASK` | 12 h | tarefa aberta atravessa o dia |

`DEFAULT_TTL_POLICY` é a **única** constante de TTL do sistema; `TtlPolicy` é
injetável (testes usam valores curtos). `ttl_for` de campo não mapeado levanta
`InvalidContextError` — mapeamento incompleto é bug, não default silencioso.

---

## 5. Ports e adapters

### 5.1 Por que exatamente dois ports

| Port | Consumidor real na Fase 2 | Justificativa |
|---|---|---|
| `ContextProvider` | 2 adapters em `src/` + 2 doubles em `tests/` | contracts §3.2 e PHASE-2 §7: fontes independentes; o aggregator não pode conhecer implementações concretas |
| `ContextSnapshotRepository` | 1 adapter SQLite + 1 fake de teste | contracts §11 nomeia este port explicitamente; o Core não pode conhecer SQL |

**Não** viram port, por decisão explícita (contracts §1, PHASE-2 §7):
`ContextProjection`, `ContextAggregator`, `ContextEventConsumer` e `ContextEngine`
— implementação única, nenhum substituto real; "interface" = API pública da classe.
Simetria com o `EventBus` da Fase 1.

### 5.2 `context/ports.py`

```python
class ContextProvider(Protocol):
    @property
    def name(self) -> str: ...
    def observe(self, now: datetime) -> ContextUpdate: ...
```

- `now` é **injetado**: nenhum provider lê o relógio por conta própria ⇒ testes
  determinísticos, nenhum `sleep`.
- Cada provider define `Observation.source = f"provider:{self.name}"` e o
  `observed_at` real da observação (pode ser anterior a `now`).
- Ausência: devolve `ContextUpdate()` vazio.
- Falha: levanta `ContextProviderError`; o adapter traduz exceções nativas
  (`OSError` etc.) e nunca as deixa vazar.

```python
class ContextSnapshotRepository(Protocol):
    def save(self, snapshot: ContextSnapshot) -> None: ...
    def latest(self) -> ContextSnapshot | None: ...
    def read_captured_between(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int | None = None,
        include_expired: bool = False,
    ) -> Sequence[ContextSnapshot]: ...
    def expire_before(self, cutoff: datetime) -> int: ...
```

Quatro métodos, um por necessidade do ROADMAP 2.4. Sem paginação, busca ou filtro
composto — nenhum consumidor. `latest()` é o que a regra de relevância (§8.2)
consulta; `include_expired` existe porque expiração é lógica e o registro
**continua auditável** (C7).

### 5.3 Providers concretos e doubles

| Onde | Nome | Produz | Como |
|---|---|---|---|
| `src/` | `SystemTimeProvider` | `local_time` | `clock()` convertido para o `tzinfo` recebido; `None` ⇒ fuso local do sistema. `clock` e `tzinfo` injetáveis |
| `src/` | `LocalDeviceProvider` | `device_id` | `platform.node()` (stdlib); sem automação de SO; função injetável |
| `tests/` | `StubProvider` | qualquer campo | `ContextUpdate` fixo passado na construção — cobre os papéis de Activity, Calendar e Location Provider (**C2**) |
| `tests/` | `FailingProvider` | — | levanta `ContextProviderError` ou uma exceção não traduzida, à escolha do teste |

Nenhum componente abre socket, lê credencial, usa OAuth ou consulta serviço
externo. Nenhum adapter de `src/` finge ter integração pronta.

### 5.4 Fronteira e como ela é testada

`tests/test_context_architecture.py` (mesma técnica AST de
`test_events_architecture.py`):

- módulos de Core (`src/jarvis/context/*.py`) **não** importam `sqlite3`, `json`,
  `pathlib`, `jarvis.context.adapters`, `jarvis.events.adapters`, `jarvis.cli`,
  `jarvis.config`;
- imports `jarvis.*` do Core de contexto restritos a `jarvis.context`,
  `jarvis.errors` e `jarvis.events` (permitido por contracts §3.2: Context conhece
  o Event System como consumidor/leitor);
- `context/adapters/**` **importa** `jarvis.context.ports` (direção obrigatória);
- fora de `adapters/`, só `cli.py` importa `jarvis.context.adapters`;
- teste de não-vacuidade, copiando `test_there_are_core_modules_to_check`.

O teste da Fase 1 já garante o outro lado
(`ALLOWED_JARVIS_IMPORTS_IN_EVENTS = {"jarvis.events", "jarvis.errors"}`): o Event
System não passa a conhecer Context (contracts §3.1). Nenhuma alteração lá.

---

## 6. Agregação

### 6.1 `ContextProjection` (`context/projection.py`) — estado + merge

```python
class ContextProjection:
    def __init__(self, *, policy: TtlPolicy = DEFAULT_TTL_POLICY) -> None: ...
    def apply(self, update: ContextUpdate) -> tuple[ContextConflict, ...]: ...
    def snapshot_of(self, *, as_of: datetime) -> CurrentContext: ...
```

`apply` percorre os oito campos com um helper genérico

```python
def _merge[T](field, current: Observation[T] | None, incoming: Observation[T] | None)
        -> tuple[Observation[T] | None, ContextConflict | None]
```

que (1) carimba `ttl = policy.ttl_for(field)` na observação incidente via
`dataclasses.replace`, (2) aplica a regra do D5, (3) devolve o conflito quando
houver. As oito chamadas são **literais e explícitas** — verbosas de propósito,
type-safe, sem reflexão. `snapshot_of` monta o `CurrentContext` frozen com o
`as_of` recebido.

### 6.2 `ContextAggregator` (`context/aggregator.py`)

```python
class ContextAggregator:
    def __init__(
        self,
        *,
        providers: Sequence[ContextProvider],
        clock: Callable[[], datetime] = _utc_now,
        policy: TtlPolicy = DEFAULT_TTL_POLICY,
    ) -> None: ...
    def refresh(self) -> tuple[ContextConflict, ...]: ...
    def apply(self, update: ContextUpdate) -> tuple[ContextConflict, ...]: ...
    def get_current_context(self) -> CurrentContext: ...
```

**Fluxo de `refresh()`** (PHASE-2 §9, na ordem):

1. `now = clock()`;
2. para cada provider, na ordem de registro: `update = provider.observe(now)`;
3. validação/normalização já ocorreu na construção de `Observation` (D2) — entrada
   inválida vira `InvalidContextError` na origem, nunca descarte silencioso;
4. `projection.apply(update)` combina **por campo** (D5);
5. TTL é carimbado na merge; `fresh/stale` é derivado **na leitura**
   (`Observation.freshness(now)`), nunca gravado;
6. conflitos são acumulados, logados e devolvidos.

**Comportamento em falha de provider — política explícita:**

| Exceção | Comportamento |
|---|---|
| `ContextProviderError` | degrada: `WARNING context.provider_failed` (provider + tipo do erro, **sem valores**), provider pulado, **valores já conhecidos permanecem intactos**, demais providers continuam |
| Qualquer outra exceção | **propaga** |

Nada de `except Exception` engolindo falha (PHASE-2 §11): adapter que não traduz
seu erro tem bug, e bug não vira degradação silenciosa. Os dois ramos são testados.

**`get_current_context()` é leitura pura:** não faz poll nem I/O; devolve
`projection.snapshot_of(as_of=clock())`. Poll é sempre explícito via `refresh()`,
acionado pelo composition root — nunca pelo bus (PHASE-2 §3).

**Clock injetável** em aggregator, providers e engine; nenhum teste dorme ou lê o
relógio real.

---

## 7. Eventos

### 7.1 Tipos assinados e transformação (lista exaustiva, `schema_version = 1`)

`CONTEXT_EVENT_TYPES` é uma constante `frozenset[str]` em `context/consumer.py`,
usada na assinatura do bus e na reconstrução. Não existe catch-all: um `event_type`
fora desta lista **nunca** é interpretado.

| `event_type` | Campo lido do `payload` | Campo de contexto | Valor resultante |
|---|---|---|---|
| `user.availability_changed` | `availability` (rótulo) | `AVAILABILITY` | o rótulo validado |
| `user.activity_started` | `activity` (rótulo) | `ACTIVITY` | o rótulo validado |
| `user.activity_ended` | — | `ACTIVITY` | `None` — ausência **observada** (D3) |

Três tipos, escolhidos por serem o menor conjunto que demonstra o fluxo completo e
cobre os três comportamentos que precisam de teste: **substituição** de um valor,
**ausência observada** e **idempotência**. Agenda, localização, conversa, tarefa e
estado de sessão **não** viram eventos aqui — são fontes das Fases 5–7 (C13).

Regras uniformes de tradução:

- `Observation.observed_at = event.occurred_at` — **tempo de domínio**, nunca
  `recorded_at` (que é tempo de registro e não descreve quando a observação
  ocorreu);
- `Observation.source = f"event:{event.event_type}"`;
- `Observation.confidence = 1.0` — o evento *afirma* o fato; o Context Engine não
  reinterpreta nem infere.

### 7.2 Política de tipos e versões desconhecidos

| Situação | Comportamento |
|---|---|
| `event_type` fora de `CONTEXT_EVENT_TYPES` | ignorado; `DEBUG context.event_ignored`, `reason="unsubscribed_type"`. (O bus nem entrega — a assinatura usa `event_types=CONTEXT_EVENT_TYPES`; a checagem em `handle` protege chamada direta e reconstrução.) |
| `schema_version != 1` | ignorado; `INFO context.event_ignored`, `reason="unsupported_schema_version"`. Cumpre contracts §5: "consumidores devem tratar explicitamente versões desconhecidas, nunca assumir a versão mais recente". |
| `payload` sem o campo exigido, com tipo errado ou com rótulo inválido | **levanta `InvalidContextError`** |

`InvalidContextError` é `DomainError` ⇒ `retryable = False`. O bus loga
`event.consumer_failed` e roteia para dead-letter na primeira tentativa; por isso a
assinatura usa a `RetryPolicy()` **default (1 tentativa, sem retry)** — payload
malformado é falha determinística e permanente, e repetir só geraria ruído. O
evento continua no Event Store: o fato não se perde. **Nenhuma segunda semântica de
retry é criada no Context Engine** (PHASE-2 §9).

### 7.3 Idempotência

`handle(recorded)` traduz o evento em `ContextUpdate` e chama
`aggregator.apply(...)`. Reentregar o mesmo `RecordedEvent` produz a mesma
`Observation` (mesmo `observed_at`, `source`, `value`), cujo `observed_at` empata
com o corrente ⇒ regra 3 do D5 ⇒ **no-op**. Teste explícito: `handle` cinco vezes
⇒ `get_current_context()` idêntico ao de uma chamada, e zero conflitos reportados.

### 7.4 Nenhum I/O em `handle`

`ContextEventConsumer` conhece apenas o aggregator (memória) e o `logging`. Não
recebe o repositório de snapshots, não abre arquivo, não lê relógio externo.
Teste: um `SpyRepository` injetado no `ContextEngine` **não recebe chamada alguma**
durante a publicação de eventos (C8).

### 7.5 Reconstrução (`ContextEngine.rebuild_from(store)`)

Materializa o invariante "projeção derivada e reconstruível" e o item 2.5
"Validar consistência":

```python
def rebuild_from(self, store: EventStore) -> None:
    recorded = [
        item
        for event_type in sorted(CONTEXT_EVENT_TYPES)
        for item in store.read_by_type(event_type)
    ]
    for item in sorted(
        recorded, key=lambda r: (r.recorded_at, r.event.occurred_at, r.event.event_id)
    ):
        self._consumer.handle(item)
```

- **Respeita a ordem de persistência.** `read_by_type` já devolve cada tipo em
  ordem de persistência ascendente; a reordenação por `recorded_at` recompõe a
  ordem **entre** tipos, que é semanticamente relevante — `user.activity_started`
  seguido de `user.activity_ended` com o mesmo `occurred_at` só resolve
  corretamente se a ordem de registro for respeitada (C12).
- **Não amplia o port.** Usa apenas `read_by_type` e o `recorded_at` que
  `RecordedEvent` já expõe. Nenhum cursor, offset ou `sequence` é adicionado
  (C1).
- **Limitações registradas, com gatilho concreto de revisão:**
  1. dois eventos de tipos diferentes com `recorded_at` **idêntico** não são
     desempatáveis (a coluna `sequence` do adapter não é exposta no domínio) — o
     desempate por `occurred_at`/`event_id` é determinístico, mas não é a ordem de
     persistência real;
  2. a leitura é integral, sem cursor.
  Se qualquer uma dessas passar a alterar o resultado na prática — volume real de
  eventos, ou empate de `recorded_at` observado —, a resposta é acrescentar leitura
  ordenada/por cursor ao port `EventStore` **naquele momento**, com o consumidor
  concreto na mão, e não agora.
- **Por que existe:** a CLI é de vida curta; sem reconstrução, a projeção nasceria
  vazia a cada processo e o contexto derivado de eventos seria invisível.

---

## 8. Snapshots

### 8.1 Modelo (`context/snapshot.py`)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ContextSnapshot:
    snapshot_id: str
    captured_at: datetime  # tz-aware UTC
    context: CurrentContext  # frozen em profundidade


def new_snapshot_id() -> str: ...  # uuid4
def context_fingerprint(context: CurrentContext) -> str: ...  # SHA-256 do documento canônico
```

- **Imutabilidade no domínio:** todo o grafo (`CurrentContext` → subcontextos →
  `Observation`) é `frozen`, como `Event` na Fase 1.
- **Preserva os metadados:** `source`, `observed_at`, `confidence` e `ttl` de cada
  campo vão para o snapshot. `stale` **não** é gravado: é derivado de
  `observed_at + ttl` contra `captured_at`, então um snapshot lido hoje reproduz
  exatamente a freshness que valia na captura, sem duplicar estado.
- **Sem `reason`, sem `correlation_id`/`causation_id`:** um único gatilho existe
  nesta fase (§8.2) e não há fluxo causal que dispare captura (C4); campos sem
  produtor não são criados.

### 8.2 O que torna uma captura relevante

Nunca "a cada leitura". Um único gatilho concreto: **pedido explícito do
composition root** (`jarvis context snapshot`) — jamais o bus, jamais um timer.

Sobre esse gatilho, uma regra de relevância única em
`ContextEngine.capture_snapshot()`: compara `context_fingerprint(atual)` com o do
`latest()` armazenado; **igual ⇒ não persiste** e devolve `None`
(`DEBUG context.snapshot_unchanged`). Impede histórico inflado por capturas
idênticas, é determinístico e testável.

### 8.3 Identidade, serialização e adapter

- **Identidade:** `snapshot_id` uuid4. Não é determinístico por conteúdo porque a
  captura é um ato datado; a regra de relevância já evita o caso degenerado.
- **Serialização** (`context/adapters/snapshot_serialization.py`): documento JSON
  canônico (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`,
  `allow_nan=False`), no estilo de `events/adapters/serialization.py`. Codec
  **explícito por campo** — datetime → ISO-8601 UTC, `timedelta` → segundos.
  Nenhuma reflexão, nenhum pickle. Registro corrompido ⇒
  `ContextSnapshotReadError`, nunca um snapshot meio preenchido.
- **`schema_version`** (int, começa em 1) por linha, para que evolução futura seja
  tratável explicitamente; versão desconhecida ⇒ erro explícito.
- **Adapter** (`context/adapters/sqlite_snapshots.py`): `<data_dir>/context.db`:

```sql
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS context_snapshots (
    sequence       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id    TEXT    NOT NULL UNIQUE,
    captured_at    TEXT    NOT NULL,   -- ISO-8601 UTC
    schema_version INTEGER NOT NULL,
    fingerprint    TEXT    NOT NULL,   -- SHA-256 do documento canônico
    document       TEXT    NOT NULL,   -- JSON canônico do CurrentContext
    expired_at     TEXT               -- NULL = vigente; preenchido = expirado (C7)
);

CREATE INDEX IF NOT EXISTS context_snapshots_captured_at_idx ON context_snapshots(captured_at);

-- Conteúdo imutável: só `expired_at` pode mudar.
CREATE TRIGGER IF NOT EXISTS context_snapshots_block_content_update
BEFORE UPDATE OF snapshot_id, captured_at, schema_version, fingerprint, document
ON context_snapshots
BEGIN SELECT RAISE(ABORT, 'context snapshots are immutable'); END;

CREATE TRIGGER IF NOT EXISTS context_snapshots_block_delete
BEFORE DELETE ON context_snapshots
BEGIN SELECT RAISE(ABORT, 'context snapshots are never deleted'); END;
```

- **Banco separado de `events.db`:** não reutiliza a tabela `events` nem seu
  `user_version` (PHASE-2 §10); os dois componentes evoluem schema
  independentemente. Alternativa (mesmo arquivo, outra tabela) rejeitada por
  acoplar versionamento/migração de dois componentes. Reversível — o port isola.
  **Não** é decisão arquitetural nova: contracts §11 delega a tecnologia a cada
  fase, e ADR-0007 já estabeleceu SQLite + stdlib + port como o padrão do projeto
  (§12.2).
- **`DELETE` bloqueado por trigger**, igual a `events` — expiração é lógica.
- Nenhum tipo de driver (`Connection`, `Row`, cursor) cruza a fronteira; `open()`
  cria diretório e schema idempotentemente e aceita `":memory:"`, como o
  `SqliteEventStore`.

### 8.4 Consulta histórica e expiração

- `read_captured_between(start, end, *, limit, include_expired=False)` — intervalo
  **semiaberto** `[start, end)` sobre `captured_at`, ordem de captura ascendente
  (mesma convenção de `read_occurred_between`).
- `latest()` — o snapshot vigente mais recente, ou `None`.
- `expire_before(cutoff) -> int` — **marca** `expired_at` nos snapshots com
  `captured_at < cutoff` que ainda estejam vigentes, devolve a contagem e emite
  `WARNING context.snapshots_expired` com `cutoff` e total. Nunca é chamado
  automaticamente; não há job, retenção implícita nem TTL de snapshot. O registro
  **continua no banco e continua legível** via `include_expired=True` — nenhuma
  evidência auditável é destruída (C7).

### 8.5 O que snapshots não são

Não substituem Event Store nem Memory. Nenhum evento é reutilizado, mutado ou
regravado. Uma correção produz **nova** projeção e, se capturada, **novo**
snapshot — capturas históricas nunca são editadas (imposto pelo trigger de
`UPDATE`).

---

## 9. Wiring e CLI

### 9.1 Composition root (`cli.py`) — alterações mínimas

`cli.py` continua sendo o único módulo que conhece Core + Infrastructure +
Interfaces. Acréscimos:

- `context_store_path(settings) -> Path` (`<data_dir>/context.db`), espelhando
  `event_store_path`;
- `build_context_engine(...)`: instancia `SystemTimeProvider`,
  `LocalDeviceProvider`, `ContextAggregator`, `ContextEventConsumer` e
  `SqliteContextSnapshotRepository`, devolvendo o `ContextEngine`;
- no caminho `events emit`: `bus.subscribe(consumer, event_types=CONTEXT_EVENT_TYPES)`
  junto do `LoggingEventConsumer` já existente — é o wiring que fecha 2.5;
- `jarvis info` ganha a linha `context_store`.

Core continua sem chamar `load_settings()`. **Nenhuma variável de configuração
nova**: o fuso do `SystemTimeProvider` é parâmetro de construção com default "fuso
local do sistema", então `Settings` e `.env.example` ficam intocados.

### 9.2 Subcomandos `jarvis context` — dois, não quatro

```text
jarvis context show        # inspeciona a projeção atual (refresh + reconstrução do store)
jarvis context snapshot    # captura relevante; imprime "captured <id>" ou "unchanged"
```

- Justificados porque, na Fase 2, a CLI é o **único** consumidor real do Context
  Engine (Agent Runtime é Fase 4) e PHASE-2 §7 atribui ao composition root conectar
  "providers/agregador/consumer". `show` cobre 2.3; `snapshot` cobre o caminho de
  criação de 2.4.
- `show` imprime, por campo: `campo · valor · source · observed_at · fresh|stale`.
  Campos sem observação aparecem como `—` (ausência explícita, nunca inventada).
  Imprimir valores no terminal do próprio usuário é o objetivo do comando; o que
  **nunca** ocorre é valor em **log** (§10.2).
- **`history` e `prune` não são expostos.** `read_captured_between` e
  `expire_before` permanecem APIs internas do port/`ContextEngine`, cobertas por
  testes — cumprem "consulta histórica" e "expiração" de 2.4 sem criar comando
  público sem caso de uso. Expor depois é aditivo e barato.
- Códigos de saída idênticos aos existentes: `0` ok, `2` entrada inválida
  (`InvalidContextError`), `1` falha de infraestrutura (`ContextSnapshotError`).
  Mensagens em `stderr`, sem stack trace.
- Nada de daemon, watcher, `--follow` ou export.

---

## 10. Erros, observabilidade e segurança

### 10.1 Taxonomia (`context/errors.py`)

```text
JarvisError
├── DomainError            (retryable = False)
│   └── InvalidContextError            # observação/payload/campo inválido
└── InfrastructureError    (retryable = True)
    ├── ContextProviderError           # falha declarada de um provider
    └── ContextSnapshotError
        ├── ContextSnapshotWriteError  # falha ao persistir/expirar
        └── ContextSnapshotReadError   # falha ao recuperar/decodificar
```

Espelha a forma de `events/errors.py`. Tradução no adapter: `sqlite3.Error` →
`ContextSnapshotWriteError`/`ContextSnapshotReadError`; `OSError` e afins →
`ContextProviderError`; sempre `raise … from error`. Nenhuma exceção nativa
atravessa a fronteira; nenhum `except Exception` engole falha. Sem `ProviderError`
compartilhado ainda (C10).

### 10.2 Logs estruturados — e o que nunca entra neles

| Registro | Nível | Campos |
|---|---|---|
| `context.provider_failed` | WARNING | `provider`, `error_type` |
| `context.field_updated` | DEBUG | `field`, `source`, `observed_at`, `freshness` |
| `context.conflict` | INFO | `field`, `winner_source`, `loser_source`, `winner_observed_at`, `loser_observed_at` |
| `context.event_applied` | DEBUG | `event_id`, `event_type`, `correlation_id`, `causation_id`, `fields` |
| `context.event_ignored` | DEBUG/INFO | `event_id`, `event_type`, `schema_version`, `reason` |
| `context.snapshot_captured` | INFO | `snapshot_id`, `field_count`, `stale_count` |
| `context.snapshot_unchanged` | DEBUG | — |
| `context.snapshots_expired` | WARNING | `cutoff`, `expired` |

**Nunca logados:** qualquer `Observation.value`, `payload`/`metadata` de evento,
`device_id`, rótulos de lugar/atividade/disponibilidade, identificadores de
conversa/tarefa, e qualquer secret. `correlation_id`/`causation_id` são propagados
sempre que existirem (contracts §14) — são identificadores de fluxo, não conteúdo.
Um teste dedicado planta um valor sensível numa observação e assere sua ausência em
`caplog` em todos os caminhos (merge, conflito, evento, snapshot, expiração),
seguindo o precedente de `test_events_logging_consumer.py` e
`test_payload_is_not_printed_by_list`.

### 10.3 Comportamento seguro diante de falhas

- Provider quebrado ⇒ contexto **degradado, nunca apagado**; o valor antigo
  permanece com seu `observed_at` original e envelhece para `stale` normalmente.
- Consumer quebrado ⇒ evento continua registrado (persistência precede dispatch);
  dead-letter do bus registra a falha; a projeção não fica meio aplicada, porque a
  tradução evento→`ContextUpdate` acontece **antes** de qualquer merge.
- Repositório indisponível ⇒ `ContextSnapshotError` propaga até a CLI (exit `1`);
  a projeção em memória permanece válida.
- Nenhum secret é lido, gravado ou logado; `data/` continua no `.gitignore` e
  `context.db` cai dentro dele.

---

## 11. Plano de testes

Estrutura **plana** em `tests/` (`CLAUDE.md §4`). Nenhum teste toca rede, serviço
externo, credencial, OAuth, relógio real ou dorme.

| Arquivo | Cobre |
|---|---|
| `tests/context_doubles.py` | doubles: `make_observation`, `StubProvider` (devolve um `ContextUpdate` fixo — cobre os papéis Activity/Calendar/Location), `FailingProvider` (erro traduzido ou não), `SpyRepository`, `FakeSnapshotRepository` em memória, `frozen_clock` |
| `test_context_observation.py` | construção; `observed_at` naive ⇒ erro; não-UTC ⇒ normalizado; `confidence` fora de `[0,1]`/NaN ⇒ erro; `source` vazio ⇒ erro; `ttl` não positivo ⇒ erro; rótulo fora do padrão ⇒ erro; `freshness` nos limites exatos (`now == expires_at` ⇒ `STALE`); `ttl=None` ⇒ sempre `FRESH`; imutabilidade (`FrozenInstanceError`) |
| `test_context_model.py` | os 7 subcontextos e `CurrentContext` frozen; defaults ausentes; `as_of` tz-aware; ausência não observada vs. observada (D3); **completude**: `ContextField` cobre exatamente os campos de `ContextUpdate` (quebra se alguém adicionar campo e esquecer o enum) |
| `test_context_freshness.py` | `TtlPolicy` cobre todos os `ContextField`; campo não mapeado ⇒ `InvalidContextError`; TTL é **por campo** (dois campos com TTLs diferentes envelhecem em momentos diferentes); `DEFAULT_TTL_POLICY` não tem TTL global |
| `test_context_projection.py` | merge campo a campo; ausente + presente; `observed_at` mais recente vence, inclusive quando chega "para trás"; **empate ⇒ incumbente permanece**; observação idêntica ⇒ no-op (idempotência); conflito devolvido em `ContextConflict` **e** logado; o valor perdedor não some em silêncio; carimbo de TTL |
| `test_context_aggregator.py` | `refresh` coleta na ordem de registro; `ContextProviderError` degrada e **preserva** o valor anterior; exceção não traduzida propaga; `get_current_context` não faz poll nem I/O; clock injetável define `as_of`; transição `fresh → stale` só pelo avanço do clock |
| `test_context_providers.py` | Time (clock e `tzinfo` injetados, sem `sleep`); Device (função injetada); erro nativo do adapter vira `ContextProviderError`; nenhum provider lê o relógio sozinho; um `StubProvider` prova que o port aceita fontes de Activity/Calendar/Location sem adapter em `src/` |
| `test_context_consumer.py` | os três mapeamentos, um a um; `event_type` não assinado ⇒ ignorado; `schema_version=2` ⇒ ignorado com log; payload faltando campo / com tipo errado / com rótulo inválido ⇒ `InvalidContextError`; idempotência (5 × `handle` == 1 ×); `observed_at` vem de `occurred_at`, **não** de `recorded_at`; `handle` não toca no repositório (`SpyRepository`); **completude**: `CONTEXT_EVENT_TYPES` == chaves do mapa de tradução |
| `test_context_snapshot.py` | `ContextSnapshot` frozen e profundamente imutável; preserva `source`/`observed_at`/`confidence`/`ttl`; `stale` derivável do snapshot lido; `context_fingerprint` estável para conteúdo igual e divergente para diferente |
| `test_context_snapshot_serialization.py` | round-trip exato de um contexto com **todos** os campos preenchidos, incluindo a ausência observada; JSON canônico; documento corrompido ⇒ `ContextSnapshotReadError`; `schema_version` desconhecido ⇒ erro explícito |
| `test_context_sqlite_snapshots.py` | **adapter real**, arquivo em `tmp_path`: save/latest/consulta; `read_captured_between` semiaberto e ascendente; reabrir o banco e recuperar; `UPDATE` de coluna de conteúdo ⇒ abortado pelo trigger; `DELETE` ⇒ abortado; `expire_before` marca só o que precede o cutoff, devolve a contagem, some das consultas default e **continua legível** com `include_expired=True`; expirar duas vezes é idempotente; conexão fechada ⇒ `ContextSnapshotWriteError`/`ReadError`, nunca `sqlite3.Error` cru; `open()` duas vezes é idempotente |
| `test_context_engine.py` | captura relevante (conteúdo igual ⇒ não persiste, devolve `None`); captura após mudança ⇒ persiste; `rebuild_from` reproduz a projeção; expiração delegada; nenhum snapshot gravado durante `handle` |
| `test_context_architecture.py` | fronteira de imports (§5.4), incluindo o teste de não-vacuidade |
| `test_context_integration.py` | **fluxo real, SQLite em arquivo, sem nenhum double:** `Event → EventPublisher → EventBus → ContextEventConsumer → get_current_context() → capture_snapshot → consulta`; provider real + eventos compondo o mesmo contexto; **reconstrução na ordem de persistência == aplicação incremental** (2.5 "Validar consistência"), inclusive com `activity_started`/`activity_ended` emitidos em sequência; reemitir o mesmo evento (`deterministic_event_id`) não altera a projeção; consumer que falha não desfaz o evento nem impede o `LoggingEventConsumer`; snapshot recuperado após reabrir o banco preserva `stale`/`source`/`observed_at` |
| `test_cli.py` (modificado) | `context show` com store vazio (todos os campos `—`) e com eventos; `context snapshot` duas vezes ⇒ segunda reporta `unchanged`; `info` mostra `context_store`; nenhum valor de contexto aparece em log; testes existentes seguem verdes |

**O que os doubles controlam, explicitamente:** `StubProvider` controla *quais*
observações entram e com que `observed_at` (para exercitar conflito e empate sem
depender de fonte real); `FailingProvider` controla *qual* exceção é levantada
(traduzida vs. não traduzida); `frozen_clock` controla a passagem do tempo — única
forma de testar `fresh → stale`; `FakeSnapshotRepository` controla o histórico em
memória; `SpyRepository` só registra chamadas, para provar ausência de I/O em
`handle`. `test_context_sqlite_snapshots.py` e `test_context_integration.py`
**não usam double algum**: store, bus, publisher, consumer, provider e repositório
são os de produção, com bancos em arquivo real.

---

## 12. Documentação e ADRs

### 12.1 Mudanças documentais (todas factuais)

| Arquivo | Mudança |
|---|---|
| `docs/phase-2-plan.md` | **novo** — este documento |
| `docs/context-system.md` | deixa de ser conceitual: passa a descrever o que existe (módulos, `Observation`, TTL real por campo, regra de conflito e seu empate, os três `event_type` projetados, reconstrução e suas limitações, snapshots e expiração lógica, comandos de CLI) + seção "o que não foi implementado, e por quê", no molde de `event-system.md` |
| `docs/README.md` | reclassifica `context-system.md` de "conceitual" para "documentação de implementação (Fase 2)"; acrescenta `phase-2-plan.md` |
| `docs/event-system.md` | corrige a frase sobre leitura por offset "na Fase 2": a necessidade não se materializou; registra o gatilho concreto de revisão (C1/§7.5) |
| `src/jarvis/events/ports.py` | corrige o mesmo forward-reference no docstring do módulo — manutenção factual, sem mudança de comportamento |
| `CLAUDE.md §2` | árvore + parágrafo de estado (C5) |
| `README.md` | status "Fase 2 — Context Engine"; uso de `jarvis context show/snapshot`; menção a `context.db` |
| `ROADMAP.md` | **por último**: checkboxes 2.1–2.5, "FASE 2 CONCLUÍDA", M2 e histórico |
| `PHASE-2.md` | passa a ser versionado (C6); conteúdo intacto |

Não são tocados: `architecture-contracts.md` (a §6 já define o Context Contract e a
implementação apenas o materializa — `CLAUDE.md §8`; e não há ADR novo para indexar
na §15), `docs/adr/README.md`, `config.py`, `.env.example`, `pyproject.toml`,
`uv.lock`.

### 12.2 ADRs — **nenhum ADR novo é necessário**

Avaliação explícita de cada candidata contra os três critérios cumulativos de
[`adr/README.md`](adr/README.md) (difícil de reverter **e** arquitetural **e** com
alternativa real descartada):

| Candidata | Veredito | Por quê |
|---|---|---|
| SQLite em `context.db` para snapshots, atrás de port | **Não** | Reversível de forma barata: o port `ContextSnapshotRepository` isola a tecnologia (contracts §11), e a escolha é explicitamente delegada a cada fase. Não abre terreno arquitetural novo — ADR-0007 já estabeleceu SQLite + stdlib + port como o padrão do projeto, e esta fase apenas o segue. A subdecisão "banco separado em vez de tabela no `events.db`" é organização interna de dois adapters, não relação entre componentes. |
| Expiração de snapshot | **Não** | Com a solução lógica (marca `expired_at`, nada é apagado, `DELETE` bloqueado por trigger, consulta com `include_expired`), não há decisão de auditabilidade difícil de reverter a registrar: o comportamento é aditivo e o registro permanece íntegro. Um ADR só seria necessário se a fase exigisse **remoção física** — e ela não exige (C7). |
| Regra de resolução de conflito | **Não** | O critério principal (`observed_at` mais recente vence, conflito sempre observável) **já é contrato** (contracts §6) — implementá-lo não é decidir nada novo. A única lacuna era o empate, resolvido com a menor regra determinística possível (incumbente permanece), local a `projection.py`, documentada e testada. Elevá-la a ADR criaria regra arquitetural global prematura, sem caso de uso que a pressione (C11). |
| Ordem da reconstrução | **Não** | Respeitar a ordem de persistência que o `EventStore` já garante é aplicar ADR-0004 e contracts §5, não decidir contra eles. Nenhum port é ampliado; as limitações e o gatilho de revisão ficam documentados em `context-system.md` (§7.5). |
| `ContextProvider` / `ContextSnapshotRepository` como ports | **Não** | `ContextSnapshotRepository` é nomeado literalmente em contracts §11; `ContextProvider`, em contracts §3.2. São contratos já aceitos sendo materializados. |

Também **sem ADR**, por serem detalhe reversível e interno a um componente
(excluídos explicitamente por `adr/README.md`): nomes de classes, campos e
comandos; o genérico `Observation[T]`; dataclass em vez de pydantic (já decidido no
D2 da Fase 1); os valores concretos de TTL; a lista inicial de `event_type`
projetados; a estrutura de testes.

---

## 13. Sequência de implementação

Sem checkpoint humano entre subfases. Cada passo termina com **os gates completos
verdes** (§14) e um commit coerente.

| # | Passo | Cria/modifica | Depende de | Validação | Commit |
|---|---|---|---|---|---|
| 1 | Plano e especificação versionados | `docs/phase-2-plan.md`, `PHASE-2.md` (untracked → versionado) | — | árvore limpa | `docs: record phase 2 specification and plan` |
| 2 | Domínio (2.1) | `context/{__init__ (parcial),errors,observation,model,freshness,ports}.py`; `test_context_{observation,model,freshness}.py`; `tests/context_doubles.py` | 1 | gates | `feat: implement context domain` |
| 3 | Providers (2.2) | `context/adapters/{__init__,time_provider,device_provider}.py`; `test_context_providers.py`; doubles ampliados | 2 | gates | `feat: implement context providers` |
| 4 | Agregação (2.3) | `context/projection.py`, `context/aggregator.py`; `test_context_{projection,aggregator}.py` | 2, 3 | gates | `feat: implement context aggregation` |
| 5 | Snapshots (2.4) | `context/snapshot.py`, `context/engine.py` (captura + consulta + expiração), `context/adapters/{snapshot_serialization,sqlite_snapshots}.py`; `test_context_{snapshot,snapshot_serialization,sqlite_snapshots,engine}.py` | 4 | gates | `feat: implement context snapshots` |
| 6 | Integração (2.5) | `context/consumer.py`, `ContextEngine.rebuild_from`, `context/__init__.py` final, `cli.py` (wiring + `context show/snapshot`); `test_context_{consumer,architecture,integration}.py`, `test_cli.py` | 5 | gates + smoke da CLI | `feat: complete context engine` |
| 7 | Documentação | `context-system.md`, `docs/README.md`, `event-system.md` + `events/ports.py` (C1), `CLAUDE.md §2`, `README.md` | 6 | gates | `docs: document context engine implementation` |
| 8 | Marco | `ROADMAP.md` (checkboxes 2.1–2.5, "FASE 2 CONCLUÍDA", M2, histórico) | 7 | gates | `chore: complete context engine milestone` |

Ordem interna espelha a da Fase 1: erros → domínio → ports → adapters → serviço →
wiring → integração. `ContextEngine` nasce no passo 5 com captura/consulta/expiração
e ganha `rebuild_from` no passo 6, quando o consumer existe.

**Nenhum push.** Nenhum `--no-verify`. Nenhum amend de commit publicado.
`pyproject.toml` e `uv.lock` **não** são tocados: tudo é biblioteca padrão
(`dataclasses`, `datetime`, `enum`, `platform`, `uuid`, `hashlib`, `json`,
`sqlite3`, `logging`, `re`; `ast` nos testes).

---

## 14. Gates e Definition of Done

### 14.1 Gates (por passo e no encerramento, sem relaxar regra)

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Smoke da CLI ao final do passo 6:

```bash
uv run jarvis --version
uv run jarvis info                       # mostra event_store e context_store
uv run jarvis context show               # contexto vazio: campos ausentes, nada inventado
uv run jarvis events emit --type user.activity_started --source manual-cli \
    --payload '{"activity":"working"}' --key act-1
uv run jarvis context show               # atividade derivada do evento, via reconstrução
uv run jarvis context snapshot           # captured <id>
uv run jarvis context snapshot           # unchanged
uv run jarvis events list --limit 5      # regressão da Fase 1
```

Inspeção final: `git status` limpo (sem `data/`, sem temporário, sem secret);
`git diff --stat` revisado commit a commit; CI verde no push futuro — **sem push
nesta fase**.

### 14.2 Definition of Done da Fase 2

- [ ] ROADMAP 2.1–2.5: todos os itens implementados e verificados por teste.
- [ ] `CurrentContext` é projeção derivada e **reconstruível**, respeitando a ordem
      de persistência — provado por teste, não por afirmação.
- [ ] Cada campo preserva valor tipado, `observed_at`, `source`, `confidence` e
      validade; todos os datetimes tz-aware.
- [ ] TTL é por campo; vencimento marca `stale` sem descartar; ausência permanece
      ausente e nada é inferido.
- [ ] Conflito resolvido de forma determinística, **devolvido e logado**, nunca
      silencioso; o empate é documentado e testado.
- [ ] Snapshots imutáveis, persistidos, consultáveis historicamente e expiráveis só
      por caminho explícito, lógico e auditável.
- [ ] Consumer síncrono, idempotente, com filtro explícito de tipos, sem I/O em
      `handle` e sem segunda semântica de retry; ordem persistir → deduplicar →
      dispatch preservada.
- [ ] Core não importa `context.adapters`, `events.adapters`, `sqlite3`, `json`,
      `pathlib`, `cli` ou `config` (teste de arquitetura verde).
- [ ] Nenhum provider externo real, nenhuma credencial, nenhum Memory/Agent/Policy/
      Skill/MCP/voz/daemon/asyncio acidental; nenhum adapter em `src/` que aparente
      integração pronta.
- [ ] Nenhum valor de contexto, payload ou secret em log (teste dedicado).
- [ ] Nenhuma dependência nova; `uv.lock` e `pyproject.toml` intocados.
- [ ] Documentação factual atualizada; **nenhum ADR novo** (§12.2), com a
      justificativa registrada.
- [ ] Todos os gates verdes; CLI da Fase 1 e da Fase 2 funcionando.
- [ ] Commits coerentes criados, árvore limpa, `ROADMAP.md` atualizado apenas para
      2.1–2.5, **nenhum push**.

---

## 15. Fora de escopo e riscos

### 15.1 Fora de escopo (conscientemente adiado)

**Fases 3–8:** Memory System, retrieval, embeddings, scoring, preferências
persistentes; Agent Runtime, `Decision`, prompt assembly, `LLMProvider`/
`EmbeddingProvider`; Policy Engine, Skills, Tools, MCP, permissões, confirmação;
voz, GUI, API, daemon, watcher contínuo, broker, `asyncio`, scheduler; OAuth,
credenciais, integração real de calendário/localização/SO; PostgreSQL, pgvector,
Docker, deployment, migrações genéricas.

**Dentro do próprio Context Engine, adiado por falta de consumidor concreto:**

- adapters em `src/` para Activity, Calendar e Location (C2) — chegam com a fonte
  real de cada um;
- produtores para `ConversationContext` e `TaskContext` (C3) — Fases 6 e 7;
- tipos ricos de domínio (entrada de agenda, referência de conversa/tarefa) e enums
  fechados de rótulo (D4);
- eventos de sessão de dispositivo, localização, agenda, conversa e tarefa (C13);
- resolução de conflito plugável por campo e desempate por `confidence`/`source`
  (D5/C11);
- leitura por offset/cursor no `EventStore` e desempate de `recorded_at` idêntico
  (C1/C12) — com gatilho de revisão registrado em §7.5;
- `correlation_id`/`causation_id` no snapshot (C4);
- captura automática de snapshot por evento (violaria a regra de I/O em `handle`);
- remoção física de snapshots, retenção automática e compactação (C7);
- comandos `context history` / `context prune` na CLI (§9.2);
- TTL configurável por `Settings`; upcasting de `schema_version`; métricas e
  tracing (contracts §14 já os coloca fora de escopo).

### 15.2 Riscos e controles

| Risco | Como este plano controla |
|---|---|
| Contexto virar memória disfarçada | TTL obrigatório por campo, projeção derivada e reconstruível, ausência de retrieval/scoring/preferências, e valores restritos a rótulos/identificadores/tempos (D4) |
| `stale` global mascarar dado velho | `Freshness` derivada **por observação**, `TtlPolicy` por `ContextField`, teste que prova que dois campos envelhecem em momentos diferentes |
| Providers "de mentira" parecerem funcionalidade pronta | Só Time e Device ficam em `src/`; Activity/Calendar/Location são port + doubles em `tests/`, com nome e documentação que não sugerem integração (C2) |
| Consumer bloquear o publisher | `handle` puramente local; repositório nunca injetado no consumer; teste com `SpyRepository`; poll só via `refresh()` do composition root |
| Perder explicabilidade | `source`, `observed_at`, `confidence` e `ttl` preservados no snapshot; conflitos devolvidos como dado, não só como log |
| Reconstrução divergir da aplicação incremental | Reconstrução respeita a ordem de persistência (§7.5) e é comparada com a via incremental em teste de integração, incluindo o par `activity_started`/`activity_ended` |
| Assumir ordem irrelevante e errar em silêncio | O plano **não** afirma comutatividade; a ordem é respeitada explicitamente e as limitações do desempate estão documentadas com gatilho de revisão |
| Acoplamento ao SQLite | `ContextSnapshotRepository` como port; nenhum tipo de driver cruza a fronteira; teste de arquitetura por AST |
| Logs exporem dados pessoais | Tabela fixa de campos logáveis (§10.2) e teste que planta um valor sensível e assere sua ausência em todos os caminhos |
| Expiração destruir evidência | Expiração é lógica: marca `expired_at`, `DELETE` bloqueado por trigger, registro continua legível com `include_expired=True` (C7) |
| Abstração especulativa | Exatamente dois ports, ambos nomeados nos contratos; aggregator/projection/consumer/engine permanecem classes concretas; oito campos, três `event_type`, nenhum enum de domínio, nenhum ADR novo |
| Verbosidade das oito merges explícitas virar fonte de bug | Testes de completude que quebram se `ContextField`, `ContextUpdate` e o mapa de eventos saírem de sincronia |
