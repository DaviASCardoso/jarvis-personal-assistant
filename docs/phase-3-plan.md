# Plano de implementação — Fase 3: Memory System

> Plano técnico da **Fase 3** do [roadmap](../ROADMAP.md), produzido em sessão de
> planejamento dedicada. Complementa `PHASE-3.md` (especificação da fase) — o
> `ROADMAP.md` continua sendo a fonte de verdade sobre escopo, e
> [`architecture-contracts.md`](architecture-contracts.md) + [ADRs](adr/) sobre
> arquitetura. Este documento **não redefine** contrato nenhum: decide *como*
> materializar em código o que já está decidido.
>
> **Estado:** aguardando revisão. Nenhum código foi escrito nesta sessão.

---

## 1. Resumo executivo

A Fase 3 transforma o contrato de memória
([contracts §7](architecture-contracts.md#7-memory-contract)) em um subsistema
real: memórias tipadas e persistentes, com proveniência rastreável, validade
temporal, importância e confiança distintas, recuperação estruturada e semântica,
e um ranking determinístico e explicável.

Cinco decisões governam o plano:

1. **Persistência em SQLite** (`<data_dir>/memory.db`), com embeddings como `BLOB`
   e busca vetorial por varredura de cosseno no Core sobre candidatos já filtrados
   por SQL. **Isto diverge do ROADMAP 3.2**, que prevê PostgreSQL + pgvector — a
   divergência está analisada na §7.1, formalizada na §8 (ADR-0009) e listada na
   §29 como item que exige decisão do usuário antes da implementação.
2. **Conteúdo de memória é imutável.** Correção e contradição não fazem
   `UPDATE ... SET content`: criam uma memória nova que **supersede** a anterior,
   que permanece legível. O estado mutável de ciclo de vida vive num tipo separado
   (ADR-0010).
3. **Zero dependência nova e zero serviço externo.** O `EmbeddingProvider` ganha um
   adapter local e determinístico (`HashingEmbeddingProvider`); providers de vendor
   pertencem à Fase 4, quando houver credenciais e configuração para eles.
4. **Memory não conhece o Event System.** Contracts §3.3 não lista o Event System
   entre as dependências permitidas do Memory. O fluxo evento → memória exigido
   pela 3.7 é feito por um **adapter de entrada**, e o Memory Core permanece
   ignorante de eventos, contexto, LLM e banco.
5. **O ranking é uma soma ponderada de quatro termos**, com o detalhamento de cada
   termo devolvido junto do resultado. Nada de ML, treinamento ou heurística opaca.

Resultado esperado: `jarvis memory add/get/list/search/forget/reindex` funcionando
sobre um banco real, com retrieval explicável e testes determinísticos que provam
as invariantes — sem Agent Runtime, LLM, Policy, Skills, MCP ou voz.

---

## 2. Estado atual do repositório

- **Commit inspecionado:** `a52528f` (`chore: complete context engine milestone`),
  branch `main`, sincronizado com `origin/main`.
- **Fases concluídas:** 0 (Foundation), 1 (Event System), 2 (Context Engine).
- **Testes:** 361 passando. Gates verdes (`uv sync --locked`, `ruff format
  --check`, `ruff check`, `mypy --strict`, `pytest`).
- **Dependência de runtime única:** `pydantic-settings`.
- **Pendência não relacionada:** `JARVIS_Arquitetura.html` untracked na raiz, de
  antes da Fase 2. Não é escopo desta fase; permanece intocado.

```text
src/jarvis/
├── __init__.py  __main__.py  cli.py  config.py  errors.py
├── events/      event.py errors.py ports.py bus.py publisher.py  + adapters/
└── context/     observation.py model.py freshness.py errors.py ports.py
                 projection.py aggregator.py consumer.py engine.py  + adapters/
tests/           estrutura plana, factories.py + context_doubles.py
docs/            architecture{,-contracts}.md, event-system.md, context-system.md,
                 memory-system.md (conceitual), phase-{1,2}-plan.md, adr/0001–0008
```

### 2.1 O que a Fase 3 consome do que já existe

| Peça | Onde | Como a Fase 3 usa |
|---|---|---|
| `JarvisError` → `DomainError` / `InfrastructureError` | `errors.py` | raiz da taxonomia de erros de memória |
| `Event`, `RecordedEvent` | `events/event.py` | entrada do adapter evento → memória |
| `EventConsumer` (Protocol: `name`, `handle`) | `events/ports.py:66` | o adapter de entrada o satisfaz estruturalmente |
| `EventBus.subscribe(consumer, *, event_types=...)` | `events/bus.py:102` | assinatura com lista fechada de tipos |
| `CurrentContext`, `iter_fields` | `context/model.py` | ponte contexto → consulta de memória (3.7) |
| `SqliteEventStore` / `SqliteContextSnapshotRepository` | `*/adapters/` | padrão de adapter SQLite a repetir |
| `cli.py` (composition root) | `cli.py` | único módulo que conhece Core + Infra + Interfaces |
| `tests/test_*_architecture.py` | `tests/` | padrão de teste de fronteira por AST |

### 2.2 Pendência de material

`PHASE-3.md` **não está no repositório** — foi anexado à sessão. O primeiro passo da
implementação é gravá-lo na raiz e versioná-lo, como foi feito com `PHASE-1.md`
(conflito C6 da Fase 1) e `PHASE-2.md` (C6 da Fase 2). Sem isso a
"Regra de conclusão" de árvore limpa não fecha e a próxima sessão perde a
especificação.

---

## 3. Escopo

As sete subfases do ROADMAP, executadas como uma unidade:

| Subfase | Resultado |
|---|---|
| 3.1 Memory Domain | `Memory`, `StoredMemory`, os seis tipos, metadados, proveniência, validade |
| 3.2 Persistent Memory Storage | port `MemoryRepository` + adapter SQLite + serialização + schema |
| 3.3 Memory Retrieval | lookup estruturado, busca semântica, filtros, geração de candidatos |
| 3.4 Memory Scoring | `relevance` combinada, determinística e explicável |
| 3.5 Memory Consolidation | deduplicação, reforço, vínculos entre memórias, promoção contável |
| 3.6 Memory Lifecycle | reforço, decay, expiração, forget, delete, acesso |
| 3.7 Memory Integration | evento → memória, contexto → memória relevante, fluxo ponta a ponta |

---

## 4. Fora de escopo

**Fases 4+:** Agent Runtime, `LLMProvider`, raciocínio, prompt assembly, `Decision`;
Policy Engine, Skills, Tool Router, MCP; voz (wake word, STT, TTS); GUI, API,
daemon, watcher contínuo, `asyncio`, scheduler; integrações externas (Gmail,
calendário, WhatsApp); automação do computador; autenticação multiusuário;
deployment, cloud, sistema distribuído; treinamento ou fine-tuning de modelos.

**Dentro do próprio Memory, adiado por falta de consumidor concreto** (detalhado na
§27): adapters de embedding de vendor; reranking, HNSW/IVF ou qualquer índice
aproximado; consolidação por inferência semântica; criptografia em repouso;
migrações versionadas; emissão de eventos de memória; grafo de relações entre
memórias além de `supersedes`.

---

## 5. Requisitos derivados do roadmap

Cada item de 3.1–3.7, o arquivo que o materializa, o teste e o critério de aceitação.

### 3.1 — Memory Domain → `feat: implement memory domain`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Definir `Memory` | `memory/memory.py` | `test_memory_domain.py` | frozen; conteúdo imutável; validação no `__post_init__` |
| Memória episódica / semântica / preferência / procedural / working / task | `memory/memory.py` | idem | `MemoryType` (StrEnum) + regras de validação por tipo (§15) |
| Definir metadados | `memory/memory.py` | idem | campos obrigatórios/opcionais conforme §9.2 |
| Definir confidence | `memory/memory.py` | idem | `0 ≤ c ≤ 1`; origem `agent` não pode alegar `1.0` |
| Definir importance | `memory/memory.py` | idem | `0 ≤ i ≤ 1`; **imutável** após a criação |
| Definir timestamps | `memory/memory.py` | idem | `created_at`, `valid_from` imutáveis; `recorded_at`/`updated_at`/`last_accessed_at` só no `StoredMemory` |
| Definir expiration | `memory/memory.py` | idem | `valid_until` opcional; `expired_at(now)` é predicado derivado, não coluna |

### 3.2 — Persistent Memory Storage → `feat: implement persistent memory storage`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Definir banco de dados | ADR-0009 | — | **SQLite** (§7.1); divergência do roadmap registrada na §29 |
| Configurar PostgreSQL / pgvector | — | — | **não realizado**; adiado com justificativa (§29) |
| Criar schema | `memory/adapters/sqlite_repository.py` | `test_memory_sqlite_repository.py` | tabela `memories`, índices por uso real, trigger de imutabilidade |
| Criar migrations | — | — | `PRAGMA user_version = 1`, como nas Fases 1 e 2; sem ferramenta de migração (§29) |
| Implementar repository | `memory/ports.py` + adapter | idem | port trafega entidades de domínio; nenhum tipo de driver cruza a fronteira |
| Criar testes | — | idem | round-trip real em arquivo, imutabilidade atacada por fora do adapter |

### 3.3 — Memory Retrieval → `feat: implement memory retrieval`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Busca semântica | `memory/retrieval.py` | `test_memory_retrieval.py` | embedding da consulta → cosseno sobre candidatos compatíveis |
| Busca temporal | `memory/ports.py` (`MemoryCriteria`) | `test_memory_sqlite_repository.py` | janela semiaberta sobre `created_at` e filtro de validade |
| Busca por entidades | idem | idem | match exato em `entities` |
| Filtros | idem | idem | tipo, subject, scope, tags, entidades, validade, importância mínima |
| Ranking inicial | `memory/retrieval.py` | `test_memory_retrieval.py` | ordenação por similaridade, antes do score combinado da 3.4 |
| Criar testes | — | idem | determinísticos, com clock e embeddings injetados |

### 3.4 — Memory Scoring → `feat: implement memory scoring`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Definir relevância | `memory/ranking.py` | `test_memory_ranking.py` | calculada no retrieval, **nunca** persistida |
| Definir recência | idem | idem | meia-vida por tipo, ancorada em `updated_at` |
| Definir importância / confidence | idem | idem | termos independentes, com pesos distintos |
| Relevância temporal | idem | idem | memória fora de `[valid_from, valid_until)` não é candidata |
| Scoring combinado | idem | idem | soma ponderada renormalizada (§13) |
| Testar ranking | — | idem | ordem estável e explicável; empates desempatados de forma determinística |

### 3.5 — Memory Consolidation → `feat: implement memory consolidation`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Definir consolidação | `memory/consolidation.py` | `test_memory_consolidation.py` | operação **explícita**, nunca automática |
| Detectar padrões | idem | idem | contagem determinística sobre `subject` + fingerprint; sem inferência |
| Criar memórias semânticas | idem | idem | promoção por repetição (§16.4); anotada na §29 |
| Relacionar memórias | `memory/memory.py` | idem | `superseded_by` + `derived_from` |
| Controlar confidence | idem | idem | reforço assintótico limitado |
| Evitar duplicações | idem | idem | fingerprint de conteúdo normalizado |

### 3.6 — Memory Lifecycle → `feat: implement memory lifecycle`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Reinforcement | `memory/manager.py` | `test_memory_manager.py` | `confidence` sobe de forma limitada; `reinforced_count++` |
| Decay | `memory/ranking.py` | `test_memory_ranking.py` | **computado no retrieval**, nunca grava; anotado na §29 |
| Expiration | `memory/memory.py` | `test_memory_domain.py` | derivada de `valid_until`; nada é apagado |
| Forget | `memory/manager.py` | `test_memory_manager.py` | invalidação lógica com motivo, evidência preservada |
| Delete | idem | idem | remoção física, explícita e irreversível (privacidade) |
| Atualização | idem | idem | só estado de ciclo de vida; conteúdo nunca muda |
| Registrar origem | `memory/memory.py` | `test_memory_domain.py` | `Provenance` obrigatória |

### 3.7 — Memory Integration → `feat: complete persistent memory system`

| Item | Arquivo | Teste | Critério |
|---|---|---|---|
| Integrar Event System | `memory/adapters/event_consumer.py` | `test_memory_event_consumer.py` | direção **entrada**; Memory Core não conhece eventos (§17) |
| Integrar Context Engine | `memory/adapters/context_bridge.py` | `test_memory_context_bridge.py` | `CurrentContext` → `RetrievalQuery` |
| Fluxo evento → memória | idem | idem | tipos fechados, idempotente, sem I/O em `handle` |
| Fluxo contexto → memória relevante | idem | `test_memory_integration.py` | contexto vira filtros/consulta |
| Testar recuperação contextual | — | `test_memory_integration.py` | ponta a ponta com SQLite em arquivo |

---

## 6. Contratos que serão materializados

| Contrato | Onde | Como |
|---|---|---|
| [§7 Memory Contract](architecture-contracts.md#7-memory-contract) | `memory/memory.py` | seis tipos; metadados obrigatórios e opcionais; `relevance` calculada, nunca armazenada; embedding registra provider/versão |
| [§3.3 Limites do Memory System](architecture-contracts.md#33-memory-system) | `memory/` + teste de arquitetura | depende apenas de Domain, `MemoryRepository` e `EmbeddingProvider`; **não** conhece `LLMProvider`, Skills, Policy, Tool Router — nem Event System ou Context |
| [§11 Persistence Boundary](architecture-contracts.md#11-persistence-boundary) | `memory/ports.py` + adapter | `MemoryRepository` como port; nenhum tipo de driver atravessa |
| [§4 LLM Independence](architecture-contracts.md#4-llm-independence) | `memory/ports.py` | `EmbeddingProvider` separado; erros traduzidos para taxonomia do Core |
| [§12 Configuration Boundary](architecture-contracts.md#12-configuration-boundary) | `memory/memory.py` | preferências são memória, não `Settings` |
| [§13 Error Contract](architecture-contracts.md#13-error-contract) | `memory/errors.py` | domínio permanente / infraestrutura retryable |
| [§14 Observability](architecture-contracts.md#14-observability-contract) | todo o pacote | log estruturado, `correlation_id` quando existir, **nunca** conteúdo |
| [ADR-0002](adr/0002-llm-provider-abstraction.md) | `memory/ports.py` | `EmbeddingProvider` é port próprio, com identidade de modelo |
| [ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md) | `MemoryType.PREFERENCE` | preferências com proveniência e confidence |

---

## 7. Decisões arquiteturais

Formato: **decisão → motivo → alternativas → impacto → reversibilidade**.

### 7.1 D1 — Persistência: SQLite em `memory.db`, busca vetorial por varredura

**Decisão.** Um único banco SQLite (`<JARVIS_DATA_DIR>/memory.db`) guarda memórias e
embeddings. O embedding é uma coluna `BLOB` (`array('f')` little-endian) com
`embedding_provider`, `embedding_model` e `embedding_dimensions` ao lado. A busca
semântica é feita **no Core**: o repositório devolve os candidatos já filtrados por
SQL (tipo, validade, subject, tags, modelo de embedding compatível), e o Core
calcula o cosseno por varredura sobre esse conjunto.

**Motivo — medido, não suposto.** O argumento decisivo é a escala real de um
assistente pessoal. Varredura de cosseno em Python puro (`array` + `map`), neste
mesmo ambiente (CPython 3.13.14, Windows AMD64):

| memórias × dimensões | tempo |
|---|---|
| 1 000 × 256 | 11 ms |
| 10 000 × 256 | **109 ms** |
| 10 000 × 768 | 321 ms |
| 50 000 × 768 | 1,6 s |

Dez mil memórias é muito para um assistente pessoal de um usuário só, e 109 ms é
irrelevante para uma CLI ou para um ciclo de agente. O índice aproximado que o
pgvector oferece resolve um problema que este projeto não tem, e ainda por cima
troca exatidão por velocidade — enquanto a varredura é **exata e determinística**,
que é exatamente o que a §18 de `PHASE-3.md` exige dos testes.

**Comparação concreta das alternativas:**

| Critério | A — PostgreSQL + pgvector | B — SQLite + varredura (escolhida) | B' — SQLite + `sqlite-vec` | C — vector store separado |
|---|---|---|---|---|
| Instalação | serviço externo + Docker ou instalação local | nenhuma (stdlib) | wheel extra + `load_extension` | serviço ou dependência pesada |
| Dependências novas | driver (`psycopg`) + serviço | **zero** | `sqlite-vec` | cliente + servidor |
| Desenvolvimento local | subir e manter o serviço | abrir um arquivo | idem SQLite | idem A |
| Testes | precisa de instância real ou fixture pesada | `:memory:`, instantâneo | idem, com risco de extensão | mock ou serviço em CI |
| CI | serviço adicional no workflow | nenhuma mudança no `ci.yml` | risco por plataforma | serviço adicional |
| Persistência | robusta, multiusuário | arquivo único, suficiente para 1 processo | idem | externa |
| Busca vetorial | madura, com índice ANN | exata por varredura, ~109 ms @10k | ANN embutido | madura |
| Performance esperada | excelente e desnecessária | suficiente com folga | boa | excelente e desnecessária |
| Manutenção | upgrades, backup, tuning | copiar um arquivo | acompanhar versão da extensão | mais um sistema |
| Reversibilidade | — | **alta**: o port isola; migrar = novo adapter + export/import | alta | média |
| Impacto futuro | dois bancos e duas operações | um arquivo por componente, como já é | idem | mais superfície |

**Alternativas descartadas, com o motivo:**

- **PostgreSQL + pgvector (A)** — descartada *para esta fase*. Traz um serviço
  externo, Docker (que o [README](../README.md) evita deliberadamente) e custo
  operacional permanente para resolver um gargalo que a medição mostra não existir.
  A regra 11 do roadmap ("não adicionar infraestrutura complexa sem necessidade
  concreta") e `architecture-contracts.md §1` a proíbem sem necessidade
  demonstrada, e a necessidade não foi demonstrada — foi refutada. O próprio
  [ADR-0007](adr/0007-sqlite-event-store.md) já previu que "a Fase 3 pode adotá-lo
  para Memory", condicionalmente, não obrigatoriamente.
- **`sqlite-vec` (B')** — descartada por ora, mas **verificada**:
  `sqlite3.enable_load_extension` funciona neste ambiente, então continua sendo o
  próximo passo natural. Adicioná-la agora seria uma dependência e um formato de
  índice a manter para ganhar velocidade que não falta. Fica registrada como o
  gatilho de escalada: se a varredura passar de ~300 ms em uso real, troca-se o
  cálculo dentro do adapter, sem tocar no Core.
- **Vector store separado (C)** — descartada: acrescenta um segundo sistema de
  armazenamento e a necessidade de mantê-lo consistente com o relacional, sem
  nenhum requisito que peça isso.

**Impacto.** O projeto passa a ter três arquivos SQLite (`events.db`, `context.db`,
`memory.db`), cada um atrás do seu port — coerente com o que já existe. Nenhuma
mudança em `pyproject.toml`, `uv.lock` ou `ci.yml`.

**Reversibilidade.** Alta no código (o port isola tudo); média nos dados (migrar
exigiria export/import). **É registrada como [ADR-0009](#8-adrs-necessários) e
diverge do ROADMAP 3.2 — ver §29.**

### 7.2 D2 — Conteúdo imutável; ciclo de vida em um tipo separado

**Decisão.** Dois tipos, como `Event`/`RecordedEvent` na Fase 1:

- **`Memory`** — o que um produtor afirma. Imutável e sem estado de ciclo de vida.
- **`StoredMemory`** — `Memory` + estado mutável, construído **apenas** pelo
  repositório.

O conteúdo (`content`, `type`, `subject`, `scope`, `provenance`, `created_at`,
`valid_from`, `importance`) nunca muda depois de persistido. Não existe um
`update(memory)` genérico: existem operações nomeadas de ciclo de vida
(`record_access`, `reinforce`, `invalidate`, `supersede`, `purge`).

**Motivo.** `PHASE-3.md §7` proíbe explicitamente `UPDATE memory SET content = ...`
sem semântica definida, e `§5` exige que evidência histórica não seja apagada em
silêncio. Dois tipos tornam isso **estrutural** em vez de disciplina de código: não
há um caminho no qual o conteúdo de uma memória possa ser reescrito. A ausência de
`update()` genérico é o que impede a operação errada de existir.

**Alternativas.** (a) Uma entidade mutável com repositório disciplinado — rejeitada,
porque a proibição vira convenção; (b) linhas versionadas com `version` incremental
— rejeitada, porque duplica o que `supersedes` já expressa, com mais complexidade
de consulta.

**Impacto.** Toda correção cria uma linha nova. Cresce o volume, o que é aceitável
na escala do projeto e é o preço da auditabilidade.

**Reversibilidade.** Baixa depois que houver dados reais → **ADR-0010**.

### 7.3 D3 — `importance` imutável, `confidence` mutável

`importance` é uma propriedade da afirmação ("o quanto isto merece ser
preservado"), fixada por quem cria. `confidence` é uma crença sobre a veracidade, e
crença muda com evidência: reforço a aumenta, contradição a deixa registrada na
memória superada. Decay **não** grava — é o termo de recência, calculado no
retrieval (§13).

Isso mantém a distinção que `PHASE-3.md §4` exige e evita o pior efeito colateral
possível: reescrever `confidence` a cada leitura, tornando o histórico irrecuperável.

### 7.4 D4 — `EmbeddingProvider` com um adapter local e determinístico

**Decisão.** O port é definido nesta fase e implementado por
`HashingEmbeddingProvider`: vetor de dimensão 256 obtido por *hashing* de n-gramas
de caracteres do conteúdo normalizado, com normalização L2. Identidade do modelo:
`provider="hashing"`, `model="hashing-v1"`.

**Motivo.** `PHASE-3.md §17` exige que o Memory funcione **sem nenhum LLM
configurado**, e a Fase 4 é quem introduz credenciais e configuração de provider.
Um adapter local resolve isso com zero dependência, é determinístico (o mesmo texto
sempre produz o mesmo vetor, o que torna todo teste de retrieval reproduzível) e é
honesto sobre o que é: similaridade **lexical**, não semântica. O nome, a docstring
e a documentação dizem isso — o mesmo critério aplicado na Fase 2, quando Activity,
Calendar e Location ficaram como port + double em vez de virarem adapters que
aparentassem integração pronta.

**Alternativas.** (a) Só o port, sem adapter — deixaria a busca semântica sem como
ser exercitada de ponta a ponta nesta fase; (b) adapter de vendor (OpenAI etc.) —
exigiria credencial, rede e configuração que pertencem à Fase 4, e quebraria o
determinismo dos testes; (c) modelo local de verdade (`sentence-transformers`) —
dependência de centenas de MB e download de pesos, desproporcional.

**Reversibilidade.** Alta: um adapter novo em Infrastructure, mais `reindex` para
reprocessar os vetores (§11.4). Sem ADR — é escolha de adapter, reversível e
interna a um componente.

### 7.5 D5 — O Memory Core não conhece Event System nem Context Engine

**Decisão.** `src/jarvis/memory/*.py` (Core) importa apenas `jarvis.memory` e
`jarvis.errors`. A integração exigida pela 3.7 acontece em **adapters de entrada**:
`memory/adapters/event_consumer.py` e `memory/adapters/context_bridge.py`.

**Motivo.** Contracts §3.3 lista as dependências permitidas do Memory System:
"Domain, `EmbeddingProvider` port, `MemoryRepository` port". O Event System **não**
está lá — ao contrário do Context Engine, cuja §3.2 lista explicitamente "Event
System (como consumidor, somente leitura)". A assimetria é do contrato, e o plano a
respeita em vez de a apagar. Em Ports & Adapters, um consumer que traduz eventos em
chamadas de caso de uso é um adapter *driving*, e é exatamente onde ele pertence.

**Consequência importante:** o Memory System **não emite eventos** nesta fase (§17).

### 7.6 D6 — Contradição por supersessão, com `subject` como chave

Duas memórias válidas do mesmo `type` e mesmo `subject` com conteúdos diferentes são
uma contradição. A resolução não apaga nada: a nova memória é criada, e a antiga
recebe `superseded_by` e `valid_until = nova.valid_from`. Ambas continuam
consultáveis; o retrieval devolve apenas as vigentes por padrão.

`subject` é **informado por quem cria**, nunca inferido. É isso que mantém a
detecção determinística e impede o sistema de inventar que dois textos "falam da
mesma coisa".

---

## 8. ADRs necessários

Avaliação contra os três critérios cumulativos de [`adr/README.md`](adr/README.md)
(difícil de reverter **e** arquitetural **e** com alternativa real descartada):

### ADR-0009 — SQLite como armazenamento do Memory System

- **Precisa?** Sim. Difícil de reverter depois que houver memórias reais gravadas;
  arquitetural (define a fronteira de persistência de um componente central); com
  alternativa real e documentada no roadmap sendo descartada.
- **Contexto:** ROADMAP 3.2 prevê PostgreSQL + pgvector; a Fase 1 escolheu SQLite
  por princípio de simplicidade operacional (ADR-0007); o projeto é pessoal e de
  processo único.
- **Decisão:** SQLite em `memory.db`, embeddings como `BLOB`, busca vetorial exata
  por varredura no Core sobre candidatos pré-filtrados por SQL.
- **Alternativas:** PostgreSQL + pgvector; SQLite + `sqlite-vec`; vector store
  separado — com a tabela comparativa e a medição da §7.1.
- **Consequências:** três bancos SQLite, um por componente; gatilho explícito de
  escalada (varredura acima de ~300 ms em uso real → `sqlite-vec` dentro do
  adapter, depois PostgreSQL se houver múltiplos processos); **supersede
  parcialmente a intenção do ROADMAP 3.2**, que precisa ser anotado (§29).

### ADR-0010 — Memória imutável, com supersessão em vez de sobrescrita

- **Precisa?** Sim. Define para sempre o que "corrigir uma memória" significa;
  difícil de reverter depois que houver histórico; alternativas reais (mutação
  in-place, linhas versionadas) descartadas.
- **Contexto:** `PHASE-3.md §5/§7` exige semântica explícita para contradição e
  proíbe apagar evidência; o Event System já estabeleceu imutabilidade
  (ADR-0004) e o Context Engine, expiração lógica.
- **Decisão:** conteúdo imutável; `Memory`/`StoredMemory` separados; contradição
  resolvida por supersessão datada; `forget` invalida logicamente; `purge` remove
  fisicamente **apenas** por pedido explícito do usuário, como direito de apagar
  dado pessoal — a assimetria em relação a eventos e snapshots é deliberada e fica
  registrada aqui.
- **Consequências:** auditabilidade completa; crescimento de linhas; consultas
  precisam filtrar vigência por padrão.

### Sem ADR, por serem reversíveis e internos ao componente

O adapter de embedding local; os pesos e meias-vidas do ranking (constantes num
módulo só); os nomes de campos, comandos e módulos; a estrutura dos testes; a
escolha de `frozen dataclass` em vez de pydantic (já decidida na Fase 1, D2); a
lista inicial de `event_type` consumidos.

---

## 9. Modelo de domínio

### 9.1 Tipos

```python
class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PREFERENCE = "preference"
    PROCEDURAL = "procedural"
    WORKING = "working"
    TASK = "task"


class MemoryOrigin(StrEnum):
    USER = "user"  # o usuário afirmou
    EVENT = "event"  # derivada de um fato registrado
    AGENT = "agent"  # inferência do agente — nunca confidence 1.0
    SYSTEM = "system"  # produzida por uma regra determinística (consolidação)
    IMPORTED = "imported"  # trazida de fora


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """De onde a informação veio, com detalhe suficiente para auditar."""

    origin: MemoryOrigin
    reference: str | None = None  # event_id, correlation_id, id de importação…


@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryEmbedding:
    vector: tuple[float, ...]
    provider: str
    model: str
    dimensions: int
    created_at: datetime

    def is_comparable_to(self, other: "MemoryEmbedding") -> bool: ...
```

`Provenance` é uma **estrutura**, não apenas uma categoria — resposta explícita à
pergunta de `PHASE-3.md §6`. Duas chaves bastam para responder "de onde isto veio?"
e, principalmente, para distinguir uma inferência do agente de uma afirmação do
usuário; um terceiro campo livre não teria consumidor nesta fase.

### 9.2 `Memory` — a afirmação imutável

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Memory:
    memory_id: str
    type: MemoryType
    content: str
    provenance: Provenance
    created_at: datetime  # tz-aware, UTC
    importance: float = 0.5  # 0..1
    confidence: float = 0.8  # 0..1
    valid_from: datetime | None = None  # default: created_at
    valid_until: datetime | None = None
    subject: str | None = None  # slug; chave de contradição
    scope: str | None = None  # task_id / conversation_id
    entities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()  # memory_ids que a originaram
    embedding: MemoryEmbedding | None = None

    def fingerprint(self) -> str: ...  # SHA-256 do conteúdo normalizado
    def is_valid_at(self, moment: datetime) -> bool: ...
```

**Invariantes** (violação ⇒ `InvalidMemoryError`):

1. `memory_id` não vazio; `content` não vazio depois de `strip`.
2. `0 ≤ importance ≤ 1` e `0 ≤ confidence ≤ 1`, ambos finitos.
3. `created_at` e `valid_from`/`valid_until` timezone-aware, normalizados para UTC.
4. `valid_until`, se presente, é **estritamente** posterior a `valid_from`.
5. `subject`, quando presente, é um slug (`^[a-z0-9]+(?:[._-][a-z0-9]+)*$`, ≤ 64) —
   é chave de contradição, não texto livre.
6. `provenance.origin is AGENT ⇒ confidence < 1.0`. Uma inferência não é certeza;
   é a materialização do que `PHASE-3.md §6` pede para impedir.
7. `type is WORKING ⇒ valid_until is not None`. Working memory sem prazo é memória
   permanente disfarçada.
8. `type is TASK ⇒ scope is not None`. Task memory sem tarefa não é task memory.
9. `type is PREFERENCE ⇒ subject is not None`. Sem `subject` não há como detectar
   que a preferência mudou — e preferência que muda em silêncio é o pior caso do
   ADR-0006.
10. `embedding`, se presente, tem `len(vector) == dimensions` e `dimensions > 0`.
11. `entities`/`tags` são tuplas de strings não vazias, sem duplicatas, ordenadas
    na construção (torna o fingerprint e os testes estáveis).

### 9.3 `StoredMemory` — a afirmação + o ciclo de vida

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class StoredMemory:
    memory: Memory
    recorded_at: datetime  # atribuído pelo repositório
    updated_at: datetime  # última mudança de ciclo de vida
    confidence: float  # corrente (reforço a altera)
    last_accessed_at: datetime | None = None
    access_count: int = 0
    reinforced_count: int = 0
    superseded_by: str | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None

    def is_active_at(self, moment: datetime) -> bool: ...  # válida ∧ não invalidada ∧ não superada
```

`confidence` aparece nos dois: em `Memory` é o valor **inicial** afirmado
(imutável, parte da evidência histórica); em `StoredMemory` é o valor **corrente**.
Isso é deliberado — permite responder "com quanta confiança isto foi afirmado
originalmente?" e "com quanta confiança acreditamos nisso hoje?", que são perguntas
diferentes. `importance` não se repete porque não muda (D3).

### 9.4 Resumo de mutabilidade

| Campo | Mutável? | Quem altera |
|---|---|---|
| `memory_id`, `type`, `content`, `subject`, `scope`, `provenance`, `created_at`, `valid_from`, `importance`, `entities`, `tags`, `derived_from` | **não** | ninguém; correção cria memória nova |
| `embedding` | só por `reembed` | `MemoryManager.reembed` |
| `confidence` (corrente) | sim | `reinforce` |
| `valid_until` | sim, **uma vez** | `supersede` (fecha a vigência) |
| `updated_at`, `last_accessed_at`, `access_count`, `reinforced_count` | sim | operações de ciclo de vida |
| `superseded_by`, `invalidated_at`, `invalidation_reason` | sim, **uma vez** | `supersede` / `invalidate` |
| `relevance` | **não existe como campo** | calculada no retrieval |

---

## 10. Persistência

### 10.1 Port `MemoryRepository`

```python
class MemoryRepository(Protocol):
    def add(self, memory: Memory, *, recorded_at: datetime) -> StoredMemory: ...
    def get(self, memory_id: str) -> StoredMemory | None: ...
    def search(self, criteria: MemoryCriteria) -> Sequence[StoredMemory]: ...
    def record_access(self, memory_id: str, *, moment: datetime) -> StoredMemory: ...
    def reinforce(self, memory_id: str, *, confidence: float, moment: datetime) -> StoredMemory: ...
    def invalidate(self, memory_id: str, *, reason: str, moment: datetime) -> StoredMemory: ...
    def supersede(self, memory_id: str, *, by: str, moment: datetime) -> StoredMemory: ...
    def replace_embedding(
        self, memory_id: str, embedding: MemoryEmbedding, *, moment: datetime
    ) -> StoredMemory: ...
    def purge(self, memory_id: str) -> bool: ...
```

Nove métodos, cada um com consumidor real nesta fase. Não há `update` genérico
(D2), paginação, contagem nem agregação — ninguém as usa.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MemoryCriteria:
    """Filtros estruturados. Todos opcionais; combinam por AND."""

    types: frozenset[MemoryType] | None = None
    subject: str | None = None
    scope: str | None = None
    tags: frozenset[str] | None = None  # todas presentes
    entities: frozenset[str] | None = None  # todas presentes
    created_from: datetime | None = None  # [from, until)
    created_until: datetime | None = None
    minimum_importance: float | None = None
    active_at: datetime | None = None  # vigência; default do manager = agora
    include_invalidated: bool = False
    include_superseded: bool = False
    embedding_model: tuple[str, str] | None = None  # (provider, model) — candidatos comparáveis
    limit: int | None = None
```

`active_at` é o que materializa "busca por validade" e "relevância temporal"; o par
`embedding_model` é o que permite ao Core pedir **apenas candidatos comparáveis**,
sem trazer vetores incompatíveis para a memória do processo.

### 10.2 Schema SQLite

```sql
PRAGMA journal_mode = WAL;
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS memories (
    sequence             INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id            TEXT    NOT NULL UNIQUE,
    type                 TEXT    NOT NULL,
    content              TEXT    NOT NULL,
    content_fingerprint  TEXT    NOT NULL,
    subject              TEXT,
    scope                TEXT,
    origin               TEXT    NOT NULL,
    provenance_reference TEXT,
    created_at           TEXT    NOT NULL,
    recorded_at          TEXT    NOT NULL,
    valid_from           TEXT    NOT NULL,
    valid_until          TEXT,
    importance           REAL    NOT NULL,
    initial_confidence   REAL    NOT NULL,
    confidence           REAL    NOT NULL,
    entities             TEXT    NOT NULL,   -- array JSON canônico
    tags                 TEXT    NOT NULL,   -- array JSON canônico
    derived_from         TEXT    NOT NULL,   -- array JSON canônico
    embedding            BLOB,               -- float32 little-endian
    embedding_provider   TEXT,
    embedding_model      TEXT,
    embedding_dimensions INTEGER,
    embedding_created_at TEXT,
    updated_at           TEXT    NOT NULL,
    last_accessed_at     TEXT,
    access_count         INTEGER NOT NULL DEFAULT 0,
    reinforced_count     INTEGER NOT NULL DEFAULT 0,
    superseded_by        TEXT,
    invalidated_at       TEXT,
    invalidation_reason  TEXT
);

CREATE INDEX IF NOT EXISTS memories_type_idx        ON memories(type);
CREATE INDEX IF NOT EXISTS memories_subject_idx     ON memories(subject);
CREATE INDEX IF NOT EXISTS memories_scope_idx       ON memories(scope);
CREATE INDEX IF NOT EXISTS memories_fingerprint_idx ON memories(content_fingerprint);
CREATE INDEX IF NOT EXISTS memories_created_at_idx  ON memories(created_at);

-- O conteúdo e a proveniência são imutáveis: corrigir é criar outra memória.
CREATE TRIGGER IF NOT EXISTS memories_block_content_update
BEFORE UPDATE OF memory_id, type, content, content_fingerprint, subject, scope,
                 origin, provenance_reference, created_at, valid_from, importance,
                 initial_confidence, entities, tags, derived_from
ON memories
BEGIN
    SELECT RAISE(ABORT, 'memory content is immutable');
END;
```

**Sem trigger de `DELETE`, deliberadamente** — e a assimetria em relação a `events`
e `context_snapshots` é o ponto: memória guarda dado pessoal, e o usuário precisa
poder apagá-lo de verdade. Apagar é `purge`, explícito e irreversível; esquecer é
`invalidate`, que preserva a evidência. Registrado no ADR-0010.

Cinco índices, um por filtro realmente usado. Nenhum índice especulativo.

### 10.3 Serialização

`memory/adapters/serialization.py`, no molde dos dois adapters existentes:

- `StoredMemoryRecord` (`TypedDict`) espelha as colunas; `to_record` / `from_record`
  traduzem — o domínio nunca vê coluna nem JSON.
- Datas: `astimezone(UTC).isoformat()`; leitura com `fromisoformat`.
- `entities` / `tags` / `derived_from`: array JSON canônico (`sort_keys`,
  separadores compactos).
- **Vetor:** `array("f", vector)`, forçado a little-endian (`byteswap()` quando
  `sys.byteorder == "big"`), `.tobytes()`. Na leitura, valida
  `len(blob) == dimensions * 4` antes de decodificar; divergência ⇒
  `MemoryReadError`.
- Registro corrompido vira `MemoryReadError`, nunca uma `StoredMemory` meio
  preenchida.

---

## 11. `EmbeddingProvider`

### 11.1 Contrato

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingModel:
    """Identidade do espaço vetorial. Dois vetores só se comparam se isto coincidir."""

    provider: str
    model: str
    dimensions: int


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> EmbeddingModel: ...

    def embed(self, text: str) -> tuple[float, ...]:
        """Vetor L2-normalizado, com exatamente `model.dimensions` posições.

        Falha ⇒ `EmbeddingProviderError` (infraestrutura, retryable). O adapter
        traduz a exceção nativa; nenhuma exceção de SDK atravessa a fronteira.
        """
        ...
```

| Aspecto | Decisão |
|---|---|
| **Entrada** | uma string; o Core normaliza (trim + colapso de espaços) antes de chamar |
| **Saída** | `tuple[float, ...]` L2-normalizada, tamanho `dimensions` |
| **Dimensionalidade** | declarada pelo provider, validada pelo Core a cada chamada |
| **Identificação do modelo** | `EmbeddingModel(provider, model, dimensions)`, gravada junto do vetor |
| **Versionamento** | dentro de `model` (`hashing-v1`); mudar o algoritmo exige mudar a string |
| **Erros** | `EmbeddingProviderError` (`InfrastructureError`, retryable) |
| **Timeout** | **não** nesta fase — o único adapter é local e síncrono; um adapter de rede o adicionará junto com a sua configuração, na Fase 4 |
| **Indisponibilidade** | a memória é criada **sem** embedding e permanece plenamente utilizável no lookup estruturado; um `WARNING` registra o ocorrido e `reindex` a completa depois |
| **Geração** | síncrona, no momento da criação, dentro do `MemoryManager` |

### 11.2 Quando o embedding é gerado

Na criação (`remember`), se houver provider injetado. `WORKING` **não** recebe
embedding por padrão: vive horas, é recuperada por `scope`, e gastar uma chamada de
embedding nela seria custo sem retorno. Configurável por parâmetro explícito.

### 11.3 Adapter local

`HashingEmbeddingProvider` — n-gramas de caracteres (3-gramas) do texto normalizado
(minúsculas, sem acentos, espaços colapsados), cada n-grama mapeado por
`blake2b(ngram, digest_size=8)` para um índice em `[0, 256)` e um sinal, acumulados
e normalizados em L2. Determinístico, sem dependência, sem rede.

**É similaridade lexical, não semântica** — e a documentação, a docstring e a saída
de `jarvis memory search` dizem isso. É honesto e suficiente para exercitar todo o
caminho de retrieval de ponta a ponta; o provider real chega na Fase 4.

### 11.4 Incompatibilidade e mudança de modelo

Regra: **vetores só são comparados quando `(provider, model, dimensions)` coincidem
exatamente.** Nunca há comparação silenciosa entre espaços diferentes — é a
exigência de contracts §7 e de `PHASE-3.md §8`.

Consequências operacionais:

1. A consulta semântica filtra candidatos por `embedding_model` já no SQL.
2. Memórias com embedding de outro modelo, ou sem embedding, **não** entram no
   ranking semântico; continuam totalmente acessíveis no lookup estruturado.
3. `retrieve()` devolve `skipped_incompatible`, e a CLI avisa: *"N memórias fora do
   modelo atual; rode `jarvis memory reindex`"*. Nada é silencioso.
4. `MemoryManager.reembed(provider)` regenera vetores das memórias ativas cujo
   modelo divergir, uma a uma, e devolve quantas foram atualizadas. `replace_embedding`
   é a única operação que altera o embedding — o conteúdo continua imutável.

---

## 12. Retrieval

### 12.1 Duas operações, não uma confusão

`PHASE-3.md §11` exige que lookup estruturado e busca semântica não se confundam.
A solução: **uma API, dois modos explícitos**, distinguidos pela presença de `text`.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalQuery:
    text: str | None = None  # None ⇒ lookup puramente estruturado
    criteria: MemoryCriteria = MemoryCriteria()
    limit: int = 10
    now: datetime | None = None  # injetável; default: clock do manager
```

- `text is None` → **lookup estruturado**: filtros SQL, ordenação pelo score sem o
  termo semântico.
- `text is not None` → **retrieval semântico**: os mesmos filtros geram os
  candidatos, o texto é embutido pelo provider, e o cosseno entra no score.

Uma API única em vez de duas evita a duplicação de todos os filtros e deixa
explícito que o semântico **não substitui** o estruturado: ele acrescenta um termo.

### 12.2 Fluxo

```text
RetrievalQuery
   ↓  criteria + (provider, model) quando houver texto
MemoryRepository.search()          ← candidate generation, em SQL
   ↓  Sequence[StoredMemory] já filtrada por tipo/validade/tags/modelo
embed(text) quando houver texto    ← EmbeddingProvider
   ↓
cosseno por candidato              ← varredura exata, no Core
   ↓
score combinado (§13)
   ↓
ordenação + limite
   ↓
RetrievalOutcome(results, scanned, skipped_incompatible)
```

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalResult:
    memory: StoredMemory
    score: RelevanceScore  # com o detalhamento de cada termo


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalOutcome:
    results: tuple[RetrievalResult, ...]
    scanned: int
    skipped_incompatible: int
```

### 12.3 Filtros de vigência (default seguro)

Por padrão só entram memórias **ativas em `now`**: `valid_from ≤ now`,
`valid_until` ausente ou `> now`, não invalidadas e não superadas. Incluir as
demais exige pedido explícito (`include_invalidated`, `include_superseded`). Isso
impede que uma preferência revogada volte a influenciar uma decisão por descuido.

### 12.4 Acesso

`retrieve()` **não** registra acesso por si só: registrar N acessos a cada consulta
poluiria `last_accessed_at` e `access_count` com curiosidade em vez de uso. O
registro é explícito (`MemoryManager.record_access(memory_id)`), acionado por quem
efetivamente **usou** a memória — na Fase 4, o Agent Runtime. `jarvis memory get`
registra acesso, porque ali houve uso deliberado.

---

## 13. Ranking

### 13.1 Fórmula

Para uma memória `m`, no instante `now`, com consulta opcional `q`:

```text
relevance(m) = Σ wᵢ · termᵢ(m)  /  Σ wᵢ        (i sobre os termos presentes)
```

Quatro termos, todos normalizados em `[0, 1]`:

| Termo | Definição | Peso |
|---|---|---|
| `semantic` | `max(0, cos(e_q, e_m))` — só existe se houver consulta textual e embedding compatível | 0,45 |
| `recency` | `0.5 ** (age_hours / half_life(type))`, com `age = now − updated_at` | 0,20 |
| `importance` | `m.importance` | 0,20 |
| `confidence` | `m.confidence` (corrente) | 0,15 |

**Renormalização.** Num lookup estruturado (`text is None`) o termo semântico não
existe; em vez de valer zero — o que achataria todos os resultados —, ele sai da
soma e os pesos restantes são renormalizados por `Σ wᵢ`. É a diferença entre
"não perguntei sobre semântica" e "a semântica é péssima".

**Por que estes pesos.** `semantic` domina porque responde à única pergunta que a
consulta faz ("isto é sobre o que eu perguntei?"). `recency` e `importance` pesam
igual: uma memória antiga e importante deve competir de igual para igual com uma
recente e trivial. `confidence` é o menor porque desempata: com tudo mais igual,
uma memória duvidosa fica abaixo de uma segura, sem que uma dúvida moderada
elimine um resultado pertinente. Todos ficam em `ranking.py`, ajustáveis, testados
e injetáveis via `RankingWeights`.

### 13.2 Meias-vidas por tipo

`PHASE-3.md §13` pergunta se o decay depende do tipo. Depende — é a diferença entre
os tipos que justifica não tratá-los como registros idênticos:

| Tipo | Meia-vida | Racional |
|---|---|---|
| `WORKING` | 2 h | vive dentro de uma tarefa/conversa |
| `TASK` | 7 dias | dura o que a tarefa durar |
| `EPISODIC` | 30 dias | um acontecimento perde pertinência rápido |
| `PREFERENCE` | 180 dias | muda, mas devagar |
| `SEMANTIC` | 365 dias | conhecimento consolidado |
| `PROCEDURAL` | 365 dias | "como fazer" envelhece pouco |

Memória "permanente" não é um caso especial: é meia-vida longa, e `recency` tende a
zero sem nunca chegar lá — o que preserva a ordenação relativa entre memórias
antigas em vez de igualá-las todas.

**Âncora = `updated_at`, não `last_accessed_at`.** Reforçar uma memória a rejuvenesce
(houve evidência nova); consultá-la, não. Ancorar em acesso criaria um laço de
retroalimentação no qual o que já foi recuperado uma vez continua ganhando por ter
sido recuperado — um viés de popularidade que ninguém pediu e que seria muito
difícil de diagnosticar depois.

### 13.3 Explicabilidade e determinismo

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RelevanceScore:
    total: float
    semantic: float | None  # None quando não houve consulta textual
    recency: float
    importance: float
    confidence: float
    weights: RankingWeights
```

O detalhamento acompanha cada resultado, e `jarvis memory search --explain` o
imprime. Assim "por que esta memória apareceu?" é respondível sem depurar código.

**Desempate determinístico:** `(-total, -created_at, memory_id)`. Duas execuções
sobre os mesmos dados produzem exatamente a mesma ordem — requisito de teste, não
detalhe.

---

## 14. Memory lifecycle

```text
Candidata → validação → criação → persistência → retrieval → acesso
                                        ↓             ↓         ↓
                                    reforço      supersessão  invalidação/expiração
```

| Etapa | Operação | Efeito |
|---|---|---|
| **Criação** | `MemoryManager.remember(...)` | valida (§9.2), gera embedding se houver provider, aplica consolidação (§16), persiste. `recorded_at` é do repositório |
| **Validação** | no `__post_init__` de `Memory` | erro **antes** de qualquer I/O |
| **Persistência** | `repository.add` | `memory_id` `UNIQUE`; reinserção do mesmo id é erro explícito, não no-op silencioso |
| **Retrieval** | `retrieve()` | não muta nada |
| **Acesso** | `record_access` | `last_accessed_at = now`, `access_count += 1`. **Não** altera `updated_at`: acesso não é evidência nova |
| **Reforço** | `reinforce` | `confidence ← min(0.99, c + (0.99 − c)·0.34)`; `reinforced_count += 1`; `updated_at = now` |
| **Expiração** | derivada | `valid_until ≤ now` ⇒ fora do retrieval por padrão. **Nada é escrito, nada é apagado** |
| **Invalidação (`forget`)** | `invalidate` | `invalidated_at`, `invalidation_reason`; a memória continua legível com `include_invalidated` |
| **Supersessão** | `supersede` | `superseded_by`, `valid_until = nova.valid_from` |
| **Remoção (`delete`)** | `purge` | remoção física, irreversível, só por pedido explícito |

**Curva de reforço.** `c ← c + (cap − c)·α`, com `cap = 0.99` e `α = 0.34`: a partir
de 0,50 a sequência é 0,67 → 0,78 → 0,85 → 0,90. Cresce rápido no começo, satura
perto do teto e **nunca** chega a 1,0 — nenhuma quantidade de repetição transforma
uma crença em certeza absoluta.

**`updated_at` vs. `last_accessed_at`.** `updated_at` marca mudança de estado
(criação, reforço, supersessão, invalidação) e é a âncora da recência.
`last_accessed_at` marca leitura e **não** influencia score algum (§13.2). A
distinção existe para que o histórico de uso seja observável sem contaminar o
ranking.

---

## 15. Tipos de memória

Um único backend, semânticas diferentes — exatamente o que `PHASE-3.md §14` pede.
Seis tabelas ou seis repositórios seriam seis vezes o mesmo código com um `WHERE`
diferente.

| Tipo | Obrigatório | Embedding | Meia-vida | Expiração típica |
|---|---|---|---|---|
| `EPISODIC` | — | sim | 30 d | `valid_until` opcional |
| `SEMANTIC` | — | sim | 365 d | raramente expira |
| `PREFERENCE` | `subject` | sim | 180 d | por supersessão |
| `PROCEDURAL` | — | sim | 365 d | raramente expira |
| `WORKING` | `valid_until` | **não** | 2 h | TTL obrigatório |
| `TASK` | `scope` | sim | 7 d | `forget_scope` quando a tarefa termina |

`forget_scope(scope, reason)` invalida em bloco todas as memórias de uma tarefa
encerrada — a operação que `PHASE-3.md §14` descreve ("pode expirar quando a tarefa
termina") sem precisar de um segundo armazenamento.

Working memory não recebe embedding porque é recuperada por `scope`, não por
similaridade, e some em horas: gerar vetor para ela é custo sem retorno.

---

## 16. Contradições e provenance

### 16.1 O caso do enunciado

```text
A: "Usuário prefere Python."  subject=preference.programming_language  confidence=0.9
B: "Usuário prefere Rust."    subject=preference.programming_language  confidence=0.8
```

Detecção: mesmo `type`, mesmo `subject`, `fingerprint` diferente, ambas ativas.
Resolução (**não** é `UPDATE`):

1. `B` é criada normalmente, com a sua própria proveniência e confiança.
2. `A` recebe `superseded_by = B.memory_id` e `valid_until = B.valid_from`.
3. `A` continua consultável (`include_superseded=True`) — a evidência de que o
   usuário já preferiu Python, e quando isso mudou, não se perde.
4. O retrieval padrão devolve só `B`.

**Confiança menor não impede supersessão.** A memória mais nova ganha vigência
porque é mais nova, e a confiança dela entra no ranking, não na decisão de vigência.
Deixar a mais antiga vencer por confiança faria o sistema ignorar o usuário quando
ele mudasse de ideia com hesitação — o oposto do desejado. Se a nova crença for
fraca, ela ranqueia mal; isso é o suficiente.

### 16.2 Duplicata

Mesmo `type` + mesmo `fingerprint` + mesmo `subject`, ambas ativas ⇒ **não** cria
linha nova: reforça a existente e devolve ela. É o que impede que reprocessar um
evento infle o banco (e é a razão de o fingerprint ser indexado).

### 16.3 Proveniência

Toda memória carrega `Provenance(origin, reference)`. O uso mais importante é
distinguir `USER` de `AGENT`: uma inferência do agente nunca deve ser lida depois
como uma afirmação do usuário — daí também a invariante 6 da §9.2
(`AGENT ⇒ confidence < 1.0`). `reference` guarda o `event_id` quando a memória vem
de um evento, tornando "de onde veio isto?" respondível até o fato original no
Event Store.

### 16.4 Consolidação determinística

`consolidate(now)` é **explícito** (CLI/API), nunca automático, e aplica exatamente
três regras contáveis:

1. **Deduplicação** — §16.2.
2. **Contradição** — §16.1.
3. **Promoção episódica → semântica** — quando ≥ 3 memórias `EPISODIC` **ativas**
   compartilham `subject` e `fingerprint`, vindas de ≥ 2 `provenance.reference`
   distintos, cria-se uma memória `SEMANTIC` com aquele conteúdo,
   `provenance.origin = SYSTEM`, `derived_from` apontando para as originais e
   `confidence = min(0.95, média(confidences) + 0.05·(n − 1))`.

A regra 3 é contagem, não inferência: o `subject` é informado por quem criou a
memória, e o sistema apenas observa repetição. É a leitura honesta de "detectar
padrões / criar memórias semânticas" (ROADMAP 3.5) sem LLM e sem heurística opaca —
e está anotada na §29, porque é menos do que a frase do roadmap poderia sugerir.

---

## 17. Integração com Event System

**Direção única: evento → memória.** O Memory System não emite eventos nesta fase.

**Por quê.** Contracts §3.3 não lista o Event System entre as dependências
permitidas do Memory. Emitir exigiria ou violar isso, ou criar um port de
notificação com um único implementador — a abstração especulativa que contracts §1
proíbe. Além disso, `PHASE-3.md §15` alerta contra avalanche de eventos, e o que
seria auditado (criação, supersessão, invalidação) **já está** no próprio banco de
memória, de forma imutável e datada. Eventos sobre memória passam a ter consumidor
quando o Agent Runtime agir sobre ela (Fases 4/7). Anotado na §29.

**Adapter de entrada** (`memory/adapters/event_consumer.py`), no molde do
`ContextEventConsumer`:

| `event_type` | Payload | Memória criada |
|---|---|---|
| `user.stated_preference` | `subject` (slug), `content`, `confidence?` | `PREFERENCE`, `origin=USER`, `reference=event_id` |
| `user.noted_fact` | `content`, `subject?`, `entities?`, `tags?` | `EPISODIC`, `origin=EVENT`, `reference=event_id` |

Dois tipos, e não dez: é o menor conjunto que demonstra o fluxo e cobre os dois
casos que importam — uma preferência (que contradiz e supersede) e um fato episódico
(que consolida por repetição). Fontes reais (email, calendário) pertencem às fases
das capacidades correspondentes.

Regras, herdadas do que já funciona na Fase 2:

- assinatura no bus com `event_types=MEMORY_EVENT_TYPES` (lista fechada; sem
  catch-all);
- `schema_version != 1` ⇒ ignorado com log explícito (contracts §5);
- payload malformado ⇒ `InvalidMemoryError` (`DomainError`, permanente) ⇒ o bus
  registra e manda para dead-letter na primeira tentativa, sem retry; o evento
  continua no Event Store;
- **idempotência**: `memory_id = deterministic_memory_id(source="event",
  natural_key=event_id)`. Reentregar o mesmo evento tenta criar a mesma memória, e a
  deduplicação por fingerprint a converte em reforço — não em linha nova;
- `handle()` faz I/O? **Sim, e aqui está a diferença em relação ao Context Engine:**
  gravar memória é o efeito pretendido, não um efeito colateral. O bus é síncrono
  (ADR-0008) e a escrita é local em SQLite (sub-milissegundo), então isso é
  aceitável — mas fica **registrado como risco** (§26) com gatilho claro: se
  surgirem watchers contínuos de alto volume, a gravação passa a precisar de fila,
  e essa é a condição de revisão do ADR-0008, não uma introdução local de `asyncio`.

### 17.1 Integração com o Context Engine

`memory/adapters/context_bridge.py` traduz `CurrentContext` em `RetrievalQuery`:
campos observados e ativos viram `tags`/`entities` (ex. `place=home` → tag
`place:home`; `activity=working` → tag `activity:working`), e campos ausentes ou
`stale` são ignorados. Fica em `adapters/` porque conhece dois componentes; o
Memory Core continua sem saber que Context existe. `jarvis memory search
--from-context` o exercita.

---

## 18. CLI

Seis subcomandos, cada um amarrado a um requisito:

```bash
jarvis memory add --type preference --content "prefere Python" \
    --subject preference.programming_language [--importance 0.7] [--confidence 0.9] \
    [--origin user|event|agent|system|imported] [--reference ID] \
    [--tags a,b] [--entities x,y] [--valid-until ISO] [--scope ID] [--no-embedding]

jarvis memory get <memory_id>                    # registra acesso
jarvis memory list [--type T] [--subject S] [--scope S] [--tag T] [--entity E]
                   [--include-invalidated] [--include-superseded] [--limit N]
jarvis memory search "<texto>" [--type T] [--limit N] [--explain] [--from-context]
jarvis memory forget <memory_id> --reason "<motivo>" [--purge]
jarvis memory reindex
```

- `search --explain` imprime o detalhamento de cada termo do score — é o que torna o
  ranking auditável na prática (§13.3).
- `forget` invalida; `forget --purge` apaga fisicamente, com confirmação explícita
  na mensagem de saída de que a operação é irreversível.
- `reindex` regenera embeddings incompatíveis; é o caminho de recuperação depois de
  uma troca de modelo (§11.4).
- `add` sem provider disponível cria a memória sem embedding e avisa.
- Códigos de saída idênticos aos existentes: `0` ok; `2` entrada inválida
  (`InvalidMemoryError`); `1` falha de infraestrutura (`MemoryRepositoryError`,
  `EmbeddingProviderError`). Mensagens em `stderr`, sem stack trace.
- `jarvis info` ganha a linha `memory_store`.

A CLI é **ferramenta de diagnóstico**, não antecipação do Agent Runtime: não decide,
não resume, não conversa.

---

## 19. Estrutura de arquivos

### Criados — código

```text
src/jarvis/memory/__init__.py                    API pública do componente
src/jarvis/memory/errors.py                      InvalidMemoryError, MemoryRepositoryError, EmbeddingProviderError
src/jarvis/memory/memory.py                      MemoryType, MemoryOrigin, Provenance, Memory, StoredMemory, ids, fingerprint
src/jarvis/memory/embedding.py                   EmbeddingModel, MemoryEmbedding, cosine_similarity
src/jarvis/memory/ports.py                       MemoryRepository, EmbeddingProvider, MemoryCriteria
src/jarvis/memory/ranking.py                     RankingWeights, meias-vidas, RelevanceScore, score()
src/jarvis/memory/retrieval.py                   RetrievalQuery, RetrievalResult, RetrievalOutcome, MemoryRetrieval
src/jarvis/memory/consolidation.py               deduplicação, contradição, promoção
src/jarvis/memory/manager.py                     MemoryManager (remember, retrieve, ciclo de vida, reembed, consolidate)
src/jarvis/memory/adapters/__init__.py
src/jarvis/memory/adapters/serialization.py      Memory ↔ registro persistido, codec de vetor
src/jarvis/memory/adapters/sqlite_repository.py  SqliteMemoryRepository
src/jarvis/memory/adapters/hashing_embeddings.py HashingEmbeddingProvider
src/jarvis/memory/adapters/event_consumer.py     MemoryEventConsumer, MEMORY_EVENT_TYPES
src/jarvis/memory/adapters/context_bridge.py     CurrentContext → RetrievalQuery
```

### Criados — testes

```text
tests/memory_doubles.py                     StubEmbeddingProvider, FailingEmbeddingProvider,
                                            FakeMemoryRepository, make_memory, frozen_clock
tests/test_memory_domain.py                 invariantes, tipos, timestamps, validade, imutabilidade
tests/test_memory_errors.py                 hierarquia + classificação retryable
tests/test_memory_embedding.py              cosseno, compatibilidade, normalização
tests/test_memory_serialization.py          round-trip, codec de vetor, corrupção
tests/test_memory_sqlite_repository.py      persistência, filtros, trigger, purge, erros
tests/test_memory_ranking.py                cada termo, pesos, renormalização, desempate
tests/test_memory_retrieval.py              estruturado vs. semântico, candidatos, incompatíveis
tests/test_memory_manager.py                ciclo de vida completo
tests/test_memory_consolidation.py          deduplicação, contradição, promoção
tests/test_memory_hashing_embeddings.py     determinismo, dimensão, normalização
tests/test_memory_event_consumer.py         mapeamento, filtro, idempotência, payload inválido
tests/test_memory_context_bridge.py         contexto → consulta; stale/ausente ignorado
tests/test_memory_architecture.py           fronteira de imports + independência de LLM
tests/test_memory_privacy.py                conteúdo nunca em log nem em mensagem de erro
tests/test_memory_integration.py            fluxo real ponta a ponta com SQLite em arquivo
```

### Modificados

```text
src/jarvis/cli.py                composition root: memory store, engine, subcomandos, wiring do consumer
tests/test_cli.py                cobertura dos novos subcomandos
docs/memory-system.md            conceitual → documentação de implementação
docs/README.md                   reclassifica memory-system.md; acrescenta phase-3-plan.md
docs/adr/README.md               índice: 0009, 0010
docs/architecture-contracts.md   §15: acrescenta 0009 e 0010 à lista de ADRs
CLAUDE.md                        §2: árvore e estado factuais
README.md                        status da fase + uso de `jarvis memory`
ROADMAP.md                       checkboxes 3.1–3.7, M3, histórico + anotações da §29
PHASE-3.md                       passa a ser versionado (§2.2)
```

### Criados — documentação

```text
docs/phase-3-plan.md                                    este documento
docs/adr/0009-sqlite-memory-storage.md                  D1
docs/adr/0010-immutable-memory-and-supersession.md      D2
```

**Nenhuma dependência nova.** Tudo com biblioteca padrão: `sqlite3`, `json`,
`hashlib` (blake2b/sha256), `array`, `math`, `uuid`, `dataclasses`, `enum`,
`datetime`, `unicodedata`, `logging`, `re`; `ast` nos testes. `pyproject.toml`,
`uv.lock` e `ci.yml` ficam intocados.

---

## 20. Ordem exata de implementação

Sem checkpoint humano entre subfases. Cada passo termina com **todos os gates
verdes** e um commit coerente.

| # | Passo | Cria/modifica | Valida |
|---|---|---|---|
| 1 | Especificação e plano versionados | `PHASE-3.md`, `docs/phase-3-plan.md` | árvore limpa |
| 2 | **Domínio (3.1)** | `memory/{__init__ (parcial),errors,memory,embedding}.py`; `tests/memory_doubles.py`, `test_memory_{domain,errors,embedding}.py` | gates |
| 3 | **Persistência (3.2)** | `memory/ports.py`, `memory/adapters/{__init__,serialization,sqlite_repository}.py`; `test_memory_{serialization,sqlite_repository}.py` | gates |
| 4 | **Retrieval (3.3)** | `memory/retrieval.py`, `memory/adapters/hashing_embeddings.py`; `test_memory_{retrieval,hashing_embeddings}.py` | gates |
| 5 | **Scoring (3.4)** | `memory/ranking.py` + integração no retrieval; `test_memory_ranking.py` | gates |
| 6 | **Consolidação (3.5)** | `memory/consolidation.py`, `memory/manager.py` (remember); `test_memory_consolidation.py` | gates |
| 7 | **Ciclo de vida (3.6)** | `memory/manager.py` (completo); `test_memory_manager.py` | gates |
| 8 | **Integração (3.7)** | `memory/adapters/{event_consumer,context_bridge}.py`, `memory/__init__.py` final, `cli.py`; `test_memory_{event_consumer,context_bridge,architecture,privacy,integration}.py`, `test_cli.py` | gates + smoke |
| 9 | **Documentação** | ADR-0009, ADR-0010, `memory-system.md`, `docs/README.md`, `adr/README.md`, contracts §15, `CLAUDE.md`, `README.md` | gates |
| 10 | **Marco** | `ROADMAP.md` (checkboxes, M3, histórico, anotações) | gates |

Ordem interna espelha as Fases 1 e 2: erros → domínio → ports → adapters → serviço
→ wiring → integração. `manager.py` nasce no passo 6 com `remember` e cresce no 7.

Dependência entre passos: 4 precisa de 3 (candidatos vêm do repositório); 5 precisa
de 4 (o score entra no retrieval); 6 precisa de 5 (a promoção usa comparação); 8
precisa de tudo.

---

## 21. Estratégia de testes

Estrutura **plana** em `tests/` (`CLAUDE.md §4`). Nenhum teste toca rede, serviço
externo, credencial, relógio real ou dorme. Clock e `EmbeddingProvider` são sempre
injetados.

| Arquivo | Cobre |
|---|---|
| `test_memory_domain.py` | as 11 invariantes da §9.2, uma a uma; `created_at` naive ⇒ erro; não-UTC ⇒ normalizado; `valid_until ≤ valid_from` ⇒ erro; `AGENT` com `confidence=1.0` ⇒ erro; `WORKING` sem `valid_until` ⇒ erro; `TASK` sem `scope` ⇒ erro; `PREFERENCE` sem `subject` ⇒ erro; imutabilidade (`FrozenInstanceError`); `entities`/`tags` ordenadas e sem duplicata; `fingerprint` estável sob variação de espaços e maiúsculas; `is_valid_at` nos limites exatos do intervalo semiaberto |
| `test_memory_errors.py` | hierarquia; `InvalidMemoryError` permanente; `MemoryRepositoryError`/`EmbeddingProviderError` retryable |
| `test_memory_embedding.py` | cosseno de vetores conhecidos (ortogonais → 0, idênticos → 1, opostos → −1); `is_comparable_to` divergindo em provider, model e dimensão; vetor de tamanho errado ⇒ erro |
| `test_memory_serialization.py` | round-trip exato com **todos** os campos preenchidos e com todos os opcionais ausentes; codec de vetor preserva valores em float32; blob truncado ⇒ `MemoryReadError`; JSON canônico de `entities`/`tags`; `schema_version` desconhecido ⇒ erro explícito |
| `test_memory_sqlite_repository.py` | **adapter real** em `tmp_path`: add/get; `recorded_at` atribuído pelo repositório; reabrir o arquivo e recuperar; `memory_id` duplicado ⇒ erro; cada filtro de `MemoryCriteria` isoladamente **e** combinados; janela `created_at` semiaberta; `active_at` excluindo expirada/invalidada/superada; filtro por `embedding_model`; `record_access`/`reinforce`/`invalidate`/`supersede` alteram só o que devem; `UPDATE` direto em coluna de conteúdo ⇒ abortado pelo trigger; `purge` remove de fato e devolve `False` para id inexistente; conexão fechada ⇒ `MemoryWriteError`/`MemoryReadError`, nunca `sqlite3.Error` cru; `open()` duas vezes é idempotente |
| `test_memory_ranking.py` | cada termo isolado; `recency` na meia-vida exata vale 0,5; meia-vida difere por tipo; ancoragem em `updated_at` (acesso **não** muda o score); renormalização sem termo semântico; pesos somam 1; ordem estável; desempate por `created_at` e depois `memory_id`; score sempre em `[0, 1]` |
| `test_memory_retrieval.py` | lookup estruturado não chama o provider; retrieval semântico chama uma vez; candidatos incompatíveis não entram no ranking mas são contados em `skipped_incompatible`; memória sem embedding não quebra a consulta semântica; `limit` respeitado após ordenação; vigência default exclui expirada/invalidada/superada; `include_*` as traz de volta; provider indisponível ⇒ `EmbeddingProviderError` propaga sem corromper estado |
| `test_memory_manager.py` | `remember` valida antes de qualquer I/O; embedding gerado na criação e ausente para `WORKING`; provider falhando ⇒ memória criada sem embedding + `WARNING`; `record_access` não muda `updated_at`; curva de reforço (0,50 → 0,67 → 0,78 …) e teto 0,99 nunca atingindo 1,0; `forget` preserva a memória; `purge` remove; `forget_scope` invalida a tarefa inteira; `reembed` só troca vetores incompatíveis e devolve a contagem |
| `test_memory_consolidation.py` | duplicata exata reforça em vez de inserir; conteúdo equivalente com espaçamento diferente conta como duplicata; contradição no mesmo `subject` supersede e fecha `valid_until`; a memória superada continua legível; confiança menor **não** impede supersessão; promoção com 3 episódicas de 2 referências distintas cria a semântica com `derived_from`; 3 episódicas da **mesma** referência **não** promovem; consolidação é idempotente |
| `test_memory_hashing_embeddings.py` | determinismo (mesmo texto ⇒ mesmo vetor, entre execuções); dimensão declarada; norma L2 ≈ 1; textos diferentes ⇒ vetores diferentes; texto vazio ⇒ erro; normalização (acento, caixa, espaço) produz o mesmo vetor; textos com sobreposição lexical têm cosseno maior que textos sem |
| `test_memory_event_consumer.py` | os dois mapeamentos; tipo não assinado ignorado; `schema_version` diferente ignorado com log; payload malformado ⇒ `InvalidMemoryError` permanente; **idempotência**: entregar o mesmo evento 5× resulta em uma memória com `reinforced_count` crescendo, nunca em 5 linhas; `MEMORY_EVENT_TYPES` == chaves do mapa de tradução (teste de completude) |
| `test_memory_context_bridge.py` | contexto com campos ativos vira tags; campo `stale` é ignorado; campo ausente é ignorado; contexto vazio ⇒ consulta sem filtros de tag |
| `test_memory_architecture.py` | varredura AST: Core não importa `sqlite3`, `json`, `pathlib`, `jarvis.memory.adapters`, `jarvis.events`, `jarvis.context`, `jarvis.cli`, `jarvis.config`; imports `jarvis.*` do Core restritos a `jarvis.memory` e `jarvis.errors`; **nenhum módulo do pacote** (Core ou adapter) importa `openai`, `anthropic`, `httpx`, `requests` ou qualquer `jarvis.*.llm`; adapters importam `jarvis.memory.ports`; fora de `adapters/`, só `cli.py` conhece `jarvis.memory.adapters`; teste de não-vacuidade |
| `test_memory_privacy.py` | planta conteúdo reconhecível ("Consulta com a Dra. Marina") e assere ausência em `caplog` em **todos** os caminhos que logam (criação, reforço, supersessão, invalidação, purge, consumo de evento, falha de provider, falha de repositório); mensagens de `InvalidMemoryError` não repetem o conteúdo recusado — lição direta da Fase 2; `fingerprint` não expõe o conteúdo |
| `test_memory_integration.py` | **sem nenhum double**, SQLite em arquivo: `add → embedding → persistência → search semântica → ranking explicável`; evento → consumer → memória → retrieval; preferência contraditória supersede e só a nova aparece no default; reemitir o mesmo evento não duplica; ciclo de tarefa (`scope`) criado e encerrado por `forget_scope`; `reindex` após troca de modelo restaura a busca semântica; reabrir o banco preserva tudo |
| `test_cli.py` (modificado) | `memory add/get/list/search/forget/reindex`; `search --explain` imprime o detalhamento; `forget --purge` remove; ISO inválida ⇒ exit 2 sem stack trace; `info` mostra `memory_store`; conteúdo não aparece em log; testes existentes seguem verdes |

**O que os doubles controlam:** `StubEmbeddingProvider` controla o vetor devolvido
(para montar cenários de similaridade exatos, sem depender do algoritmo de hashing);
`FailingEmbeddingProvider` controla a exceção (traduzida vs. não traduzida);
`FakeMemoryRepository` mantém o histórico em memória para os testes de manager e
consolidação; `frozen_clock` controla a passagem do tempo — única forma de testar
recência, expiração e reforço. Os testes de repositório e de integração **não usam
double algum**.

---

## 22. Estratégia de documentação

| Arquivo | Mudança | Como evitar duplicação |
|---|---|---|
| `docs/memory-system.md` | conceitual → implementação | descreve o que existe (módulos, invariantes, fórmula, ciclo de vida, CLI) e **referencia** contracts §7 em vez de repetir a tabela de metadados |
| `docs/phase-3-plan.md` | novo | registro das decisões e das alternativas descartadas; não repete contrato |
| `docs/adr/0009`, `0010` | novos | apenas contexto → decisão → alternativas → consequências |
| `docs/adr/README.md` | duas linhas no índice | — |
| `docs/architecture-contracts.md` | **§15 apenas** | duas linhas na lista de ADRs; §7 já define o contrato de memória, e a implementação apenas o materializa (`CLAUDE.md §8`) |
| `docs/README.md` | reclassifica `memory-system.md`; acrescenta `phase-3-plan.md` | — |
| `CLAUDE.md §2` | árvore + parágrafo de estado | factual |
| `README.md` | status + uso de `jarvis memory` + nota sobre `memory.db` | — |
| `ROADMAP.md` | checkboxes 3.1–3.7, M3, histórico, anotações da §29 | por último |

Regra de fronteira, já usada nas Fases 1 e 2: **contrato** diz o que vale sempre;
**ADR** diz por que a decisão foi tomada e o que foi descartado; **documentação de
implementação** diz o que existe hoje no código. Nenhum dos três repete o outro —
eles se referenciam.

---

## 23. Estratégia de Git/commits

Dez commits, na ordem da §20. Sem `push`, sem `--force`, sem `--amend` de commit
publicado, sem `--no-verify`. Cada commit deixa a suíte verde e o projeto validável.

| # | Mensagem |
|---|---|
| 1 | `docs: record phase 3 specification and plan` |
| 2 | `feat: implement memory domain` |
| 3 | `feat: implement persistent memory storage` |
| 4 | `feat: implement memory retrieval` |
| 5 | `feat: implement memory scoring` |
| 6 | `feat: implement memory consolidation` |
| 7 | `feat: implement memory lifecycle` |
| 8 | `feat: complete persistent memory system` |
| 9 | `docs: document memory system implementation` |
| 10 | `chore: complete memory system milestone` |

As mensagens 2–8 são exatamente as previstas no `ROADMAP.md` para 3.1–3.7. Ao final,
árvore limpa, nenhum arquivo temporário, nenhum secret, `data/` continua ignorado.

---

## 24. Validação final

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv run jarvis --version
uv run jarvis info                 # mostra event_store, context_store e memory_store
```

Testes específicos da Memory:

```bash
uv run pytest tests/test_memory_domain.py tests/test_memory_ranking.py -q
uv run pytest tests/test_memory_sqlite_repository.py tests/test_memory_integration.py -q
uv run pytest tests/test_memory_architecture.py tests/test_memory_privacy.py -q
```

Smoke real, com `JARVIS_DATA_DIR` apontando para um diretório temporário:

```bash
# 1. Uma preferência declarada pelo usuário
uv run jarvis memory add --type preference --subject preference.programming_language \
    --content "prefere Python para scripts" --origin user --confidence 0.9

# 2. Lookup estruturado
uv run jarvis memory list --type preference

# 3. Busca semântica com o score explicado
uv run jarvis memory search "o que eu costumo usar para programar?" --explain

# 4. Contradição: a nova supersede, a antiga continua legível
uv run jarvis memory add --type preference --subject preference.programming_language \
    --content "prefere Rust para sistemas" --origin user --confidence 0.8
uv run jarvis memory list --type preference                        # só a nova
uv run jarvis memory list --type preference --include-superseded   # as duas

# 5. Evento vira memória, e reemitir não duplica
uv run jarvis events emit --type user.stated_preference --source manual-cli \
    --payload '{"subject":"preference.coffee","content":"prefere café sem açúcar"}' --key p-1
uv run jarvis events emit --type user.stated_preference --source manual-cli \
    --payload '{"subject":"preference.coffee","content":"prefere café sem açúcar"}' --key p-1
uv run jarvis memory list --subject preference.coffee              # uma memória, reforçada

# 6. Esquecer preserva; purgar apaga
uv run jarvis memory forget <id> --reason "usuário pediu"
uv run jarvis memory forget <id> --purge

# 7. Regressão das fases anteriores
uv run jarvis events list --limit 5
uv run jarvis context show
```

Inspeção final: `git status` limpo, `git diff --stat` revisado commit a commit,
**nenhum push**.

---

## 25. Critérios de conclusão

- [ ] ROADMAP 3.1–3.7 implementados e verificados por teste (com as anotações da §29).
- [ ] `Memory` imutável no conteúdo, no domínio **e** na persistência (trigger).
- [ ] `importance` e `confidence` distintos, com ciclos de vida diferentes.
- [ ] `relevance` calculada no retrieval e **nunca** persistida.
- [ ] Proveniência obrigatória; inferência do agente nunca alega certeza.
- [ ] Validade temporal aplicada por padrão em toda consulta.
- [ ] Contradições resolvidas por supersessão datada, sem apagar evidência.
- [ ] Working e Task memory com semântica própria, no mesmo backend.
- [ ] `EmbeddingProvider` como port separado, com identidade de modelo gravada.
- [ ] Embeddings incompatíveis nunca comparados; `reindex` recupera.
- [ ] Retrieval estruturado e semântico distintos e ambos funcionando.
- [ ] Ranking determinístico, explicável e coberto termo a termo.
- [ ] Core não importa banco, `json`, adapters, Event System, Context, LLM SDK
      (teste de arquitetura verde).
- [ ] Nenhum conteúdo de memória em log ou em mensagem de erro (teste dedicado).
- [ ] Memory System funciona **sem nenhum LLM configurado**.
- [ ] CLI de diagnóstico funcionando; `jarvis info` atualizado.
- [ ] Nenhuma dependência nova; `uv.lock` e `pyproject.toml` intocados.
- [ ] ADR-0009 e ADR-0010 criados e indexados; documentação factual atualizada.
- [ ] `uv sync --locked`, `ruff format --check`, `ruff check`, `mypy`, `pytest`
      verdes; CI verde.
- [ ] Commits organizados, árvore limpa, **nenhum push** durante a execução.

---

## 26. Riscos

| Risco | Controle |
|---|---|
| Escolher SQLite e descobrir que não escala | Medição documentada (§7.1) + gatilho explícito (~300 ms) + port que isola a troca; `sqlite-vec` já verificado como disponível neste ambiente |
| Divergência do roadmap passar despercebida | §29 + anotação inline no `ROADMAP.md` + ADR-0009 |
| Embedding lexical ser confundido com semântico real | Nome, docstring, documentação e saída da CLI dizem o que é; provider real na Fase 4 |
| Conteúdo pessoal vazar em log | Tabela fixa de campos logáveis + `test_memory_privacy.py` + mensagens de erro sem o valor recusado (lição da Fase 2) |
| `handle()` do consumer fazer I/O e prender o publisher | Escrita local sub-milissegundo; risco registrado (§17) com gatilho = watchers contínuos, que é a condição de revisão do ADR-0008 |
| Crescimento de linhas por imutabilidade | Deduplicação por fingerprint + `purge` explícito; volume irrelevante na escala do projeto |
| Ranking parecer arbitrário | Pesos em um módulo só, injetáveis, testados termo a termo, com `--explain` |
| Reforço inflar confiança indevidamente | Curva assintótica com teto 0,99, testada valor a valor |
| Promoção episódica → semântica criar ruído | Exige ≥ 3 ocorrências de ≥ 2 referências distintas, e só roda por chamada explícita |
| Consumer de evento duplicar memórias | `deterministic_memory_id` + deduplicação por fingerprint, testados juntos |
| Working memory virar memória permanente disfarçada | `valid_until` obrigatório por invariante de domínio |

---

## 27. Decisões deliberadamente adiadas

- **PostgreSQL + pgvector** — quando houver múltiplos processos escrevendo, ou a
  varredura passar do gatilho de ~300 ms.
- **`sqlite-vec` ou índice ANN** — mesmo gatilho, e é o passo anterior a trocar de
  banco.
- **Adapters de embedding de vendor** — Fase 4, junto com credenciais e configuração.
- **Emissão de eventos de memória** — quando o Agent Runtime agir sobre memória
  (Fases 4/7) e houver consumidor real.
- **Consolidação por inferência semântica** (agrupar conteúdos parecidos sem
  `subject` comum) — exige julgamento que só o Agent Runtime terá.
- **Grafo de relações** além de `supersedes`/`derived_from` — sem consumidor.
- **Reranking, feedback de uso, aprendizado de pesos** — seria o "sistema de
  recomendação complexo" que `PHASE-3.md §13` proíbe.
- **Criptografia em repouso e multiusuário** — `PHASE-3.md §16` desaconselha nesta
  fase; o banco vive em `data/`, já ignorado pelo Git.
- **Migrações versionadas** — `PRAGMA user_version` marca o ponto de partida; a
  ferramenta entra quando houver a primeira migração real.
- **Resumo/compactação de memórias antigas** — precisa de LLM.

---

## 28. Compatibilidade com Fases 4+

| Fase | O que a Fase 3 já deixa pronto |
|---|---|
| **4 — Agent Runtime** | `MemoryManager.retrieve(RetrievalQuery)` é a única porta de leitura; `remember` a de escrita. O `LLMProvider` entra ao lado, nunca dentro do Memory. `relevance` continua calculada, então mudar pesos não invalida dado gravado |
| **4 — Embeddings reais** | port já definido; trocar de modelo é um adapter novo + `reindex`; a identidade de modelo gravada impede comparação silenciosa entre espaços |
| **5 — Skills** | contracts §8: a Skill recebe memória como parâmetro explícito; nada no Memory precisa mudar |
| **7 — Proatividade** | `importance`/`confidence` separados já suportam a política de interrupção; `record_access` dá o sinal de uso |
| **8 — Audit** | proveniência, supersessão e invalidação já são um histórico auditável dentro do próprio banco |
| **Context Engine** | a ponte contexto → consulta já existe em `adapters/context_bridge.py` |

Nada nesta fase antecipa comportamento das seguintes: não há decisão, ranqueamento
adaptativo, prompt nem chamada de modelo de raciocínio.

---

## 29. Desvios em relação ao roadmap ou contratos

Quatro divergências, todas em relação ao `ROADMAP.md` — **nenhuma** em relação a
`architecture-contracts.md` ou a ADR aceito. Cada uma precisa de anotação inline no
roadmap, no formato que a subfase 1.4 e a 2.2 já usam.

| # | Item do roadmap | O que o plano faz | Por quê |
|---|---|---|---|
| **D-1** | 3.2 — "Definir banco de dados", "Configurar PostgreSQL", "Configurar pgvector" | **SQLite** em `memory.db`, com busca vetorial exata por varredura. PostgreSQL e pgvector **não** são configurados | Medição (§7.1) mostra 109 ms para 10 000 memórias; a regra 11 do roadmap e contracts §1 proíbem infraestrutura sem necessidade concreta, e a necessidade foi refutada, não apenas não demonstrada. **Registrado em ADR-0009** |
| **D-2** | 3.2 — "Criar migrations" | `PRAGMA user_version = 1`, sem ferramenta de migração | Idêntico ao que as Fases 1 e 2 fizeram; introduzir Alembic para um schema novo sem histórico seria ferramenta sem uso |
| **D-3** | 3.5 — "Detectar padrões", "Criar memórias semânticas" | Promoção **contável** (≥ 3 ocorrências, ≥ 2 origens, mesmo `subject` e mesmo conteúdo), explícita e determinística | Detecção de padrão além de contagem exige inferência, e `PHASE-3.md §17/§24` proíbem LLM no Memory e pedem que ele "não tente ser inteligente". A versão inferencial é da Fase 4 |
| **D-4** | 3.7 — "Integrar Event System" | Integração **apenas na direção entrada** (evento → memória). O Memory **não emite** eventos | Contracts §3.3 não lista o Event System entre as dependências permitidas do Memory; emitir exigiria violar o contrato ou criar um port sem segundo implementador. O item do roadmap ("Criar fluxo evento → memória") é justamente a direção implementada |

**D-1 é o único que muda uma escolha tecnológica explícita do roadmap e, portanto, o
único que pede aprovação antes da implementação.** Os outros três são leituras
restritivas de itens ambíguos, resolvidas na direção mais conservadora e anotadas.

Se a decisão for manter PostgreSQL + pgvector, o impacto é contido e conhecido:
troca-se `sqlite_repository.py` por `postgres_repository.py`, acrescenta-se `psycopg`
às dependências, o `ci.yml` ganha um serviço, e o README passa a exigir Docker ou
uma instalação local — o Core, os ports, o domínio, o ranking, o retrieval e todos os
testes que não são do adapter permanecem exatamente como planejados. É precisamente
essa contenção que a regra de dependência existe para garantir.
