# Memory System

> Documentação do Memory System, implementado na **Fase 3** do
> [roadmap](../ROADMAP.md). O contrato normativo está em
> [`architecture-contracts.md §7`](architecture-contracts.md#7-memory-contract);
> as decisões desta fase, em [`phase-3-plan.md`](phase-3-plan.md),
> [ADR-0009](adr/0009-sqlite-memory-storage.md) e
> [ADR-0010](adr/0010-immutable-memory-and-supersession.md). Este documento
> explica o *porquê* e descreve o que existe de verdade em
> `src/jarvis/memory/`, sem repetir a tabela de campos do contrato.

## Por que memória, além de contexto

O Context Engine ([context-system.md](context-system.md)) responde "o que é
verdade agora" e expira por TTL. A Memory System responde a uma pergunta
diferente: "o que o Jarvis deveria continuar sabendo mesmo depois que o
contexto que gerou esse conhecimento já expirou?". Um fato específico (uma
observação de ontem) não precisa ser lembrado em detalhe para sempre — mas o
padrão que ele revela ("o usuário prefere reuniões de manhã") deveria
sobreviver ao TTL de qualquer campo de contexto.

## Estrutura

```text
src/jarvis/memory/
├── memory.py         MemoryType, MemoryOrigin, Provenance, Memory, StoredMemory, ids, fingerprint
├── embedding.py       EmbeddingModel, MemoryEmbedding, cosine_similarity
├── errors.py          InvalidMemoryError, EmbeddingProviderError, MemoryRepositoryError
├── ports.py            MemoryRepository, EmbeddingProvider (Protocols), MemoryCriteria
├── ranking.py          RankingWeights, meias-vidas por tipo, RelevanceScore, score()
├── retrieval.py        RetrievalQuery, RetrievalResult, RetrievalOutcome, MemoryRetrieval
├── consolidation.py     find_duplicate, find_contradiction, find_promotions
├── manager.py           MemoryManager (remember, retrieve, ciclo de vida, reembed, consolidate)
└── adapters/
    ├── serialization.py       StoredMemory ↔ registro persistido, codec de vetor
    ├── sqlite_repository.py   SqliteMemoryRepository
    ├── hashing_embeddings.py  HashingEmbeddingProvider
    ├── event_consumer.py      MemoryEventConsumer, MEMORY_EVENT_TYPES
    └── context_bridge.py      CurrentContext → RetrievalQuery
```

A raiz do pacote é Core; `adapters/` é Infrastructure. Nenhum módulo de Core
importa `adapters/`, `sqlite3`, `json`, `pathlib`, `cli` ou `config` —
verificado por `tests/test_memory_architecture.py`.

**Diferença deliberada em relação ao Context Engine:** o Memory Core **não**
importa `jarvis.events` nem `jarvis.context`. Contracts §3.3 lista as
dependências permitidas do Memory System como "Domain, `EmbeddingProvider`
port, `MemoryRepository` port" — o Event System não está nessa lista, ao
contrário da §3.2, que o lista explicitamente para o Context Engine. A
integração dos dois vive inteiramente em `memory/adapters/event_consumer.py` e
`memory/adapters/context_bridge.py`; o Core nunca sabe que eles existem, e o
teste de arquitetura garante isso nos dois sentidos (nem `events/` nem
`context/` sabem que `jarvis.memory` existe).

## `Memory` e `StoredMemory`: dois tipos, não um

Como `Event`/`RecordedEvent` na Fase 1:

- **`Memory`** — a afirmação: conteúdo, tipo, proveniência, validade,
  importância. **Imutável** depois de construída.
- **`StoredMemory`** — `Memory` + o estado de ciclo de vida que só o
  repositório atribui (`recorded_at`, `confidence` corrente, acesso, reforço,
  supersessão, invalidação).

Não existe `update(memory)` genérico — cada mutação de ciclo de vida é um
método nomeado (`reinforce`, `invalidate`, `supersede`, `replace_embedding`).
A ausência de um método genérico torna estrutural, não convencional, a regra
de `PHASE-3.md §7`: corrigir uma memória cria uma **nova** memória, que
supersede a anterior — a anterior nunca é reescrita. Ver
[ADR-0010](adr/0010-immutable-memory-and-supersession.md).

### Seis tipos, mesmo backend

`EPISODIC`, `SEMANTIC`, `PREFERENCE`, `PROCEDURAL`, `WORKING`, `TASK` — um
único repositório, semânticas diferentes impostas por invariantes
condicionais do domínio:

| Invariante | Por quê |
|---|---|
| `WORKING` exige `valid_until` | sem prazo, seria memória permanente disfarçada |
| `TASK` exige `scope` | sem tarefa, não é task memory |
| `PREFERENCE` exige `subject` | sem `subject`, não há como detectar que a preferência mudou |
| origem `AGENT` nunca alega `confidence == 1.0` | uma inferência do agente nunca é certeza — a distinção que `PHASE-3.md §6` exige entre fato afirmado e fato inferido |

`importance` é fixado na criação e nunca muda; `confidence` **corrente** (em
`StoredMemory`) muda com `reinforce`. `Memory.confidence` preserva o valor
**inicial** afirmado, como parte da evidência histórica.

### `Provenance`

`Provenance(origin, reference)` — `origin` é uma de `user`, `event`, `agent`,
`system`, `imported`; `reference` é opaco (tipicamente um `event_id`). É o que
responde "de onde isto veio?" e, principalmente, o que impede uma inferência
do agente de ser lida depois como uma afirmação do usuário.

### Rótulos, identificadores e tempos — nunca texto livre demais

`subject` é um slug fechado (`^[a-z0-9]+(?:[._-][a-z0-9]+)*$`, ≤ 64
caracteres) — é a chave de contradição, não uma frase. `content` é o único
campo de texto livre; `entities`/`tags`/`derived_from` são tuplas
normalizadas (deduplicadas e ordenadas na construção).

## Embeddings

### `EmbeddingProvider`, independente de `LLMProvider`

Port próprio ([ADR-0002](adr/0002-llm-provider-abstraction.md)): trocar o
modelo de raciocínio do futuro Agent Runtime não deveria arriscar quebrar a
busca semântica já indexada, e vice-versa.

```python
class EmbeddingProvider(Protocol):
    @property
    def model(self) -> EmbeddingModel: ...
    def embed(self, text: str) -> tuple[float, ...]: ...
```

`EmbeddingModel(provider, model, dimensions)` é a identidade do espaço
vetorial — a chave de comparação. **Vetores só são comparados quando o modelo
coincide exatamente**; nunca há comparação silenciosa entre espaços
diferentes (contracts §7).

### `HashingEmbeddingProvider`: similaridade lexical, não semântica

O único adapter desta fase. Produz vetores por *hashing* de trigramas de
caracteres do texto normalizado (minúsculas, sem acento, espaços colapsados),
L2-normalizados. **Determinístico** — o mesmo texto sempre produz o mesmo
vetor — e sem nenhuma dependência ou serviço externo, para que o Memory
System funcione sem nenhum LLM configurado (`PHASE-3.md §17`).

É honesto sobre o que é: mede sobreposição lexical, não significado. Um
provider de vendor real continua sendo escopo de uma fase futura: a Fase 4
trouxe credenciais e um `LLMProvider` de nuvem, mas `EmbeddingProvider` é port
**separado** ([ADR-0002](adr/0002-llm-provider-abstraction.md)), e trocá-lo
tornaria `jarvis memory add` dependente de rede e quota, além de exigir
reindexar tudo que já foi gravado.

### Geração, falha e incompatibilidade

- Gerado **na criação** (`remember`), síncrono. `WORKING` não recebe embedding
  por padrão — vive horas, é recuperada por `scope`, e gastar uma chamada de
  embedding nela seria custo sem retorno; `embed=True` explícito sobrepõe.
- Falha do provider (`EmbeddingProviderError`) **degrada**: a memória é criada
  sem embedding, com `WARNING context.embedding_failed` — nunca bloqueia a
  criação.
- Candidatos com embedding ausente ou de modelo incompatível **nunca** entram
  no ranking semântico; `RetrievalOutcome.skipped_incompatible` os conta, e
  `jarvis memory reindex` (`MemoryManager.reembed`) regenera só os vetores
  incompatíveis com o modelo corrente — memórias sem embedding (ausência
  intencional) não são tocadas.

## Persistência

`SqliteMemoryRepository` grava em `<JARVIS_DATA_DIR>/memory.db` — banco
**próprio**: três componentes, três bancos ([ADR-0009](adr/0009-sqlite-memory-storage.md)).
A escolha de SQLite sobre PostgreSQL + pgvector (previsto no `ROADMAP.md`) foi
medida, não suposta — varredura exata de cosseno em Python puro leva ~109 ms
para 10 mil memórias em 256 dimensões, uma escala muito maior do que um
assistente pessoal acumula. Ver o ADR para a comparação completa e o gatilho
de escalada.

O embedding é uma coluna `BLOB` (`float32` little-endian); a busca semântica
filtra candidatos por SQL (tipo, validade, `subject`, modelo de embedding) e
calcula o cosseno **no Core**, por varredura exata.

### Imutabilidade, com duas exceções nomeadas

Um trigger aborta `UPDATE` nas colunas de conteúdo. Duas exceções escapam
dele, deliberadamente, porque são operações de ciclo de vida com nome
próprio, não reescrita de conteúdo:

- **`valid_until`** — fechado uma vez por `supersede`, para que a vigência de
  uma memória contraditada feche exatamente quando a nova começa;
- **as colunas de `embedding`** — substituídas só por `replace_embedding`.

### `forget` vs. `purge` — a assimetria deliberada

Ao contrário de `events` e `context_snapshots`, **não há trigger de
`DELETE`**: memória pode conter dado pessoal, e `purge` precisa poder apagá-la
de verdade — o direito de apagar que `PHASE-3.md §16` exige. `forget`
("esquecer") invalida logicamente e preserva evidência; `purge` ("apagar")
remove fisicamente e é sempre explícito, nunca automático. Ver
[ADR-0010](adr/0010-immutable-memory-and-supersession.md).

### `supersede`: dois tempos, não um

`supersede(memory_id, *, by, until, moment)` separa **quando a vigência
antiga fecha** (`until` — tempo de domínio, tipicamente `valid_from` da nova
memória, que pode ser retroativo quando vem de um evento) de **quando o
registro foi de fato atualizado** (`moment` — tempo de processamento, sempre
real). Sem essa separação, duas memórias derivadas de eventos processados no
mesmo instante de relógio (mas com `occurred_at` diferentes) não teriam como
decidir qual vigência fecha a outra.

## Retrieval

### Uma API, dois modos

`PHASE-3.md §11` exige que lookup estruturado e busca semântica não se
confundam. A escolha: `RetrievalQuery(text=None|str, criteria, limit)` — a
presença de `text` distingue os dois modos, e os candidatos vêm sempre do
mesmo lugar (`MemoryRepository.search`, filtrado por `MemoryCriteria`).

```python
jarvis.memory.retrieve(RetrievalQuery(criteria=MemoryCriteria(subject="preference.language")))
jarvis.memory.retrieve(RetrievalQuery(text="o que ele usa para programar?"))
```

### Filtros estruturados

`MemoryCriteria`: tipo, `subject`, `scope`, tags (todas presentes), entidades
(todas presentes), janela de `created_at`, importância mínima, vigência
(`active_at`), inclusão de invalidadas/superadas, compatibilidade de modelo de
embedding. Tags/entidades são refinadas em Python sobre o já filtrado por SQL
— sem depender de extensão JSON1 para portabilidade.

**Vigência por padrão:** só memórias ativas em `active_at` entram, salvo
pedido explícito (`include_invalidated`/`include_superseded`) — o default
seguro que impede uma preferência revogada de voltar a influenciar uma
decisão por descuido.

## Ranking: `relevance`, nunca armazenada

Contracts §7 é explícito: `relevance` é "calculada em tempo de retrieval,
nunca armazenada". A fórmula, em `memory/ranking.py`:

```text
relevance(m) = Σ wᵢ · termᵢ(m)  /  Σ wᵢ        (i sobre os termos presentes)
```

| Termo | Definição | Peso |
|---|---|---|
| `semantic` | `max(0, cos(consulta, memória))` — só existe com consulta textual | 0.45 |
| `recency` | `0.5 ** (idade / meia-vida do tipo)`, idade = `now - updated_at` | 0.20 |
| `importance` | `memory.importance` | 0.20 |
| `confidence` | `stored.confidence` (corrente) | 0.15 |

**Renormalização:** num lookup estruturado, o termo semântico sai da soma e
os pesos restantes são renormalizados por `Σ wᵢ` — a diferença entre "não
perguntei sobre semântica" e "a semântica é péssima".

**Meia-vida por tipo** (não um único decay global):

| Tipo | Meia-vida |
|---|---|
| `WORKING` | 2 h |
| `TASK` | 7 dias |
| `EPISODIC` | 30 dias |
| `PREFERENCE` | 180 dias |
| `SEMANTIC` / `PROCEDURAL` | 365 dias |

A âncora é `updated_at`, **não** `last_accessed_at`: reforçar uma memória a
rejuvenesce (houve evidência nova); consultá-la, não — ancorar em acesso
criaria um viés de popularidade (o que já foi recuperado ganha por ter sido
recuperado).

`RelevanceScore` carrega o total **e** o detalhamento de cada termo —
`jarvis memory search --explain` o imprime, tornando "por que isto apareceu?"
respondível sem depurar código. Desempate determinístico:
`(-total, -created_at, memory_id)`.

## Ciclo de vida

```text
Candidata → validação (sem I/O) → criação → persistência → retrieval → acesso
                                                  ↓             ↓         ↓
                                             reforço      supersessão  invalidação/expiração
```

- **Criação** (`remember`) — valida, aplica consolidação inline (dedup +
  contradição), gera embedding, persiste. `created_at` pode vir de fora
  (tempo de domínio, ex. `event.occurred_at`); `recorded_at` é sempre do
  repositório (tempo de processamento).
- **Acesso** (`record_access`) — uso deliberado, não curiosidade:
  `retrieve()` nunca chama isto por conta própria. `last_accessed_at` não
  influencia o ranking.
- **Reforço** (`reinforce`) — curva assintótica `c ← c + (cap − c)·α`,
  `cap=0.99`, `α=0.34`. A partir de 0,50: 0,67 → 0,78 → 0,85 → 0,90 — cresce
  rápido no começo, satura perto do teto, nunca alcança 1,0.
- **Esquecimento** (`forget`) — invalidação lógica, com motivo.
- **Remoção** (`purge`) — física e irreversível, só por pedido explícito.
- **`forget_scope`** — invalida em bloco as memórias de uma tarefa encerrada
  (`TASK`), sem precisar de um segundo armazenamento.

## Consolidação: três regras contáveis, nunca inferência

`PHASE-3.md §24`: "o Memory System não deve tentar ser inteligente". Nenhuma
das três regras usa julgamento — só contagem e comparação de `fingerprint`.

### Deduplicação e contradição — inline, em `remember`

- **Duplicata:** a **mesma origem** (`provenance.reference`) reafirmando o
  mesmo conteúdo (mesmo tipo/`subject`/`scope`/fingerprint) — o caso de
  reprocessar um evento. Reforça a existente em vez de criar linha nova.
- **Contradição:** mesmo `subject`, conteúdo diferente, **qualquer** origem —
  o caso "prefere Python" vs. "prefere Rust". Supersede a anterior.

`reference` entra na chave de duplicata, mas **não** na de contradição: duas
ocorrências genuinamente distintas do mesmo fato (fontes diferentes) não
colapsam numa só — é o que sustenta a contagem de promoção abaixo. Duas
resubmissões da mesma fonte, sim.

### Promoção episódica → semântica — explícita, via `consolidate()`

Nunca automática (`PHASE-3.md §5`). `MemoryManager.consolidate()` promove um
grupo de memórias `EPISODIC` ativas com o mesmo `(subject, fingerprint)`
quando há **ao menos 3 ocorrências de ao menos 2 `provenance.reference`
distintos**. A nova memória `SEMANTIC` tem `origin=SYSTEM`, `derived_from`
apontando para as episódicas, e `confidence = min(0.95, média + 0.05·(n−1))`.

Idempotente por construção: se já existir uma `SEMANTIC` ativa com o mesmo
`(subject, fingerprint)`, o grupo é ignorado — chamar `consolidate()` duas
vezes não promove a mesma coisa duas vezes.

## Integração com o Event System — direção única: entrada

O Memory System **não emite eventos** nesta fase. Contracts §3.3 não lista o
Event System entre as dependências permitidas do Memory; emitir exigiria
violar isso ou criar um port sem segundo implementador. O que seria auditado
(criação, supersessão, invalidação) já está no próprio banco de memória,
imutável e datado.

`MemoryEventConsumer` (`memory/adapters/event_consumer.py`) traduz dois tipos
de evento, o menor conjunto que demonstra o fluxo:

| `event_type` | Payload | Memória |
|---|---|---|
| `user.stated_preference` | `subject`, `content`, `confidence?` | `PREFERENCE`, `origin=USER` |
| `user.noted_fact` | `content`, `subject?`, `entities?`, `tags?` | `EPISODIC`, `origin=EVENT` |

`memory_id = deterministic_memory_id(source="event", natural_key=event_id)` —
uma segunda linha de defesa contra duplicação além do fingerprint: se a
checagem de conteúdo por algum motivo não bastar, a `UNIQUE` do repositório
recusa a reinserção em vez de duplicar em silêncio. `created_at` vem de
`event.occurred_at` — tempo de domínio, o mesmo papel que `observed_at` tem
no Context Engine.

`handle()` **faz I/O deliberadamente**, ao contrário do
`ContextEventConsumer`: gravar memória é o efeito pretendido do evento, não
um efeito colateral. Aceitável enquanto o único produtor for o CLI e a
escrita local em SQLite continuar sub-milissegundo; o gatilho de revisão é o
mesmo do [ADR-0008](adr/0008-synchronous-in-process-event-bus.md) — watchers
contínuos de alto volume, não uma introdução local de `asyncio`.

Payload malformado ⇒ `InvalidMemoryError` (permanente) ⇒ dead-letter sem
retry, sem desfazer o evento já registrado.

## Escrita vinda do Agent Runtime

O terceiro produtor de memória, além de `jarvis memory add` e do consumer de
eventos: `Decision.memory`, aplicada pelo **composition root** — nunca pelo
runtime, que continua sem escrever nada
([ADR-0018](adr/0018-memory-writes-outside-the-policy-engine.md)).

| entrada | `origin` | `reference` |
|---|---|---|
| `agent ask` / `agent chat` | `USER` | nenhuma |
| `agent react` | `EVENT` | o `event_id` do gatilho |

Sem `reference` no caminho do usuário porque `find_duplicate` exige a **mesma**
`reference`: apontar para um `decision_id` novo a cada turno faria cada
repetição da mesma afirmação virar linha nova em vez de reforço. No caminho do
evento a referência é a mesma que o `MemoryEventConsumer` grava, então as duas
rotas convergem na mesma memória em vez de duplicá-la.

`MemoryProposal` (em `agent/decision.py`) é mais permissivo que `Memory`: não
tem `scope` nem `valid_until`, então uma proposta `task`, `working`, ou
`preference` sem `subject` passa na validação da decisão e é recusada aqui. A
recusa é da proposta, não do turno — o CLI imprime o motivo e segue.

## Ponte com o Context Engine

`context_to_query` (`memory/adapters/context_bridge.py`) traduz
`CurrentContext` numa `RetrievalQuery`, restrito aos campos de **estado do
usuário** — `place`, `activity`, `availability` — frescos e observados, como
tags `campo:valor` (ex. `place:home`). `device_id`/`utc_offset` ficam de
fora: são identidade técnica do dispositivo, não algo que uma memória algum
dia teria como tag, e como `MemoryCriteria.tags` exige **todas** as tags
presentes (AND), incluí-los zeraria `--from-context` na prática. Campos
ausentes, `stale` ou não-textuais (`next_entry_at`, um datetime) são
ignorados.

## Uso pelo CLI

```bash
jarvis memory add --type preference --subject preference.language \
    --content "prefere Python para scripts" --confidence 0.9

jarvis memory get <memory_id>                 # registra acesso
jarvis memory list --type preference [--include-superseded]
jarvis memory search "o que ele usa para programar?" --explain
jarvis memory search --from-context           # usa o contexto atual como filtro
jarvis memory forget <memory_id> --reason "..."
jarvis memory forget <memory_id> --reason "..." --purge   # irreversível
jarvis memory reindex                         # regenera embeddings incompatíveis
```

Códigos de saída seguem o padrão das Fases 1–2: `0` ok, `2` entrada inválida
(`InvalidMemoryError`), `1` falha de infraestrutura
(`MemoryRepositoryError`/`EmbeddingProviderError`).

## Observabilidade e dados sensíveis

Registros: `memory.embedding_failed`, `memory.reembed_failed`,
`memory.consolidated`, `memory.purged`, `memory.event_ignored`,
`memory.event_applied`. **Nenhum carrega `content`** — só identificadores,
tipos de erro e contagens; `tests/test_memory_privacy.py` planta conteúdo
reconhecível e assere a ausência dele em todos os caminhos de log. Mensagens
de validação não repetem o valor recusado — lição direta da Fase 2, aplicada
aqui desde o início.

## `LLMProvider` vs. `EmbeddingProvider`

Ver seção "Embeddings" acima. O mesmo vendor pode, na prática, implementar os
dois ports — coincidência de infraestrutura, não acoplamento arquitetural
entre eles.

## Preferências não vivem em `Settings`

Preferências do usuário ("não notificar depois das 22h") são modeladas como
memória do tipo `PREFERENCE` — não como configuração estática. A diferença:
preferências têm proveniência e `confidence`, podem mudar/decair, e são
escritas em runtime a partir do que o sistema aprende — nenhuma dessas
propriedades faz sentido para `Settings`. Ver
[ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md).

## O que não foi implementado, e por quê

- **PostgreSQL + pgvector** — a medição mostrou desnecessário nesta escala;
  ver [ADR-0009](adr/0009-sqlite-memory-storage.md) para o gatilho de
  escalada.
- **Adapter de embedding de vendor** — uma fase futura; a Fase 4 deixou o
  `EmbeddingProvider` local de propósito (ver acima).
- **Emissão de eventos de memória** — sem consumidor real; Fase 7, quando o
  Agent Runtime puder agir sobre memória (a Fase 4 apenas *propõe* lembrar).
- **Consolidação por inferência semântica** (agrupar conteúdos parecidos sem
  `subject` comum) — exige julgamento que só o Agent Runtime terá;
  `PHASE-3.md §24` proíbe o Memory System de tentar ser "inteligente".
- **Grafo de relações** além de `superseded_by`/`derived_from` — sem
  consumidor.
- **Reranking, feedback de uso, aprendizado de pesos** — seria o "sistema de
  recomendação complexo" que `PHASE-3.md §13` proíbe.
- **Criptografia em repouso e multiusuário** — `PHASE-3.md §16`
  desaconselha nesta fase; o banco vive em `data/`, já ignorado pelo Git.
- **Migrações versionadas** — `PRAGMA user_version` marca o ponto de
  partida, como nas Fases 1 e 2.
- **`jarvis memory history`/consulta histórica dedicada** — `search`/`list`
  já cobrem os casos de uso reais desta fase.

## Documentos relacionados

- Contrato normativo: [architecture-contracts.md §7](architecture-contracts.md#7-memory-contract)
- Limites do componente: [architecture-contracts.md §3.3](architecture-contracts.md#33-memory-system)
- Plano da fase: [phase-3-plan.md](phase-3-plan.md)
- Persistência: [ADR-0009](adr/0009-sqlite-memory-storage.md)
- Imutabilidade e supersessão: [ADR-0010](adr/0010-immutable-memory-and-supersession.md)
- Separação LLM/Embedding: [ADR-0002](adr/0002-llm-provider-abstraction.md)
- Preferências vs. configuração: [ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md)
- Visão geral: [architecture.md](architecture.md)
