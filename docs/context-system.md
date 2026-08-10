# Context Engine

> Documentação do Context Engine, implementado na **Fase 2** do
> [roadmap](../ROADMAP.md). O contrato normativo está em
> [`architecture-contracts.md §6`](architecture-contracts.md#6-context-contract);
> as decisões desta fase, em [`phase-2-plan.md`](phase-2-plan.md). Este documento
> explica o *porquê* e descreve o que existe de verdade em `src/jarvis/context/`,
> sem repetir a tabela de campos do contrato.

## Por que um Context Engine

O Agent Runtime precisa saber "o que está acontecendo agora" para raciocinar de
forma útil — mas eventos brutos ([event-system.md](event-system.md)) são um stream
de fatos pontuais, não um estado consultável. O Context Engine transforma esse
stream (mais dados de providers) em uma **projeção consultável do presente**, onde
cada campo carrega de onde veio, quando foi observado e se ainda vale.

**`CurrentContext` não é fonte de verdade** — é derivado de Events + Providers e
reconstruível a partir deles. Events e Memory são a fonte de verdade.

## Estrutura

```text
src/jarvis/context/
├── observation.py  Observation[T], Freshness, validadores de rótulo/identificador/tempo
├── model.py        ContextField, os 7 subcontextos, CurrentContext, ContextUpdate, iter_fields
├── freshness.py    TtlPolicy, DEFAULT_TTL_POLICY (TTL por campo)
├── errors.py       InvalidContextError, ContextProviderError, ContextSnapshotError
├── ports.py        ContextProvider, ContextSnapshotRepository (Protocols)
├── projection.py   ContextProjection, ContextConflict (merge por campo)
├── aggregator.py   ContextAggregator (coleta, merge, get_current_context)
├── consumer.py     ContextEventConsumer, CONTEXT_EVENT_TYPES
├── engine.py       ContextEngine (reconstrução, captura, histórico, expiração)
└── adapters/
    ├── time_provider.py           SystemTimeProvider
    ├── device_provider.py         LocalDeviceProvider
    ├── snapshot_serialization.py  ContextSnapshot ↔ registro persistido
    └── sqlite_snapshots.py        SqliteContextSnapshotRepository
```

A raiz do pacote é Core; `adapters/` é Infrastructure. Nenhum módulo de Core
importa `adapters/`, `sqlite3`, `json`, `pathlib`, `cli` ou `config` — verificado
por `tests/test_context_architecture.py`, que analisa os imports estaticamente.
`jarvis.events` **é** permitido no Core de contexto: contracts §3.2 lista o Event
System como dependência legítima, na posição de consumidor e leitor. A separação
física global em `domain/`/`infrastructure/` continua **não existindo**.

## `Observation[T]`: o valor com a sua própria proveniência

```python
Observation(value=..., observed_at=..., source=..., confidence=1.0, ttl=None)
```

Todo campo do contexto é um `Observation` ou `None`. Os metadados são **por campo**,
nunca um metadado global do objeto:

- **`observed_at`** — quando a observação foi feita. É um terceiro tempo, distinto
  dos dois do Event System: `occurred_at` diz quando o fato aconteceu,
  `recorded_at` quando foi registrado. Sempre timezone-aware, normalizado para UTC.
- **`source`** — `provider:time`, `event:user.activity_started`, etc.
- **`confidence`** — quão confiável o Context Engine considera aquele valor.
  **Não** participa da resolução de conflito nem da freshness: é metadado de
  proveniência para quem consumir o contexto (tipicamente o Agent Runtime).
- **`ttl`** — carimbado pela projeção a partir da `TtlPolicy`, não declarado pela
  fonte.

`CurrentContext.as_of` é o instante da leitura; `ContextSnapshot.captured_at`, o da
captura.

### Duas ausências diferentes

| Situação | Representação | Significa |
|---|---|---|
| Nunca houve dado | `campo is None` | O sistema não sabe nada. **Nunca infere.** |
| Alguém observou que não há | `Observation(value=None, …)` | Fato positivo, com origem e tempo. |

O caso concreto nesta fase é `user.activity_ended`, que afirma que não há atividade
corrente. Apagar o campo destruiria a proveniência; inventar um rótulo `idle`
afirmaria algo que o evento não disse. `jarvis context show` mostra os dois de
forma distinta: `-` para o primeiro, `(nenhum)` para o segundo.

## Freshness e TTL

O TTL é **por tipo de campo** (`freshness.py`), nunca um TTL global:

| Campo | TTL |
|---|---|
| `utc_offset` | 12 h |
| `place` | 15 min |
| `device_id` | não expira |
| `availability` | 4 h |
| `activity` | 1 h |
| `next_entry_at` | 15 min |
| `conversation` | 30 min |
| `task` | 12 h |

`Freshness` é **derivada na leitura** (`observation.freshness(now)`), nunca
armazenada — um snapshot lido hoje reproduz exatamente a validade que valia na
captura, sem duplicar estado. Um valor vencido vira `stale` e **continua
acessível**: decidir se um dado `stale` serve a uma decisão é de quem consome o
contexto, não deste componente. `DEFAULT_TTL_POLICY` é a única constante de TTL do
sistema, e um campo sem entrada é erro, não default silencioso.

## Conflitos

Para o mesmo campo, **o `observed_at` mais recente vence** (contrato §6). O contrato
não define o empate; a regra adotada é a menor possível: **empate mantém o
incumbente**. É isso que torna a reaplicação da *mesma* observação um no-op, ou
seja, a idempotência exigida do consumer.

O conflito é devolvido como `ContextConflict` **e** logado (`context.conflict`) —
nunca descartado em silêncio. Resolução plugável por campo fica para quando houver
caso de uso concreto.

## Providers

`ContextProvider` é um port: `name` + `observe(now) -> ContextUpdate`. O `now` é
**injetado** — nenhum provider lê o relógio por conta própria, e é isso que permite
testar a transição `fresh → stale` sem esperar de verdade.

Existem dois adapters, e só eles têm dado local genuíno:

- **`SystemTimeProvider`** — observa o **offset UTC em vigor** (ex. `-03:00`), não
  o instante. O instante já é `as_of`; um campo `local_time` seria a mesma
  informação com outro fuso, mudaria a cada leitura e tornaria todo snapshot
  diferente do anterior sem que nada tivesse acontecido.
- **`LocalDeviceProvider`** — `platform.node()` da biblioteca padrão. Hostname
  desconhecido vira **ausência**, não um valor inventado.

**Activity, Calendar e Location não têm adapter em `src/`.** Cada um exigiria
integração externa (agenda autenticada, serviço de localização, introspecção do
sistema operacional) que esta fase proíbe, e um adapter de "valor declarado"
pareceria funcionalidade pronta sem ser. O que existe de verdade para eles é o
port, exercitado por doubles em `tests/context_doubles.py`.

Falha de provider: `ContextProviderError` **degrada** (o provider é pulado, os
valores já conhecidos permanecem e envelhecem normalmente); qualquer outra exceção
**propaga**, porque um adapter que deixa escapar exceção nativa tem bug, e bug não
vira degradação silenciosa.

## Agregação

- `refresh()` faz I/O — pergunta a cada provider, na ordem de registro — e é sempre
  acionado explicitamente pelo composition root, **nunca** pelo Event Bus, cujo
  dispatch é síncrono e não pode ficar preso a um poll (ADR-0008).
- `get_current_context()` não faz poll nem I/O: devolve o que já se sabe, datado
  com `as_of`.

## Eventos projetados

O consumer se inscreve numa lista fechada (`CONTEXT_EVENT_TYPES`); não existe
catch-all que interprete payload arbitrário.

| `event_type` | Payload | Campo | Valor |
|---|---|---|---|
| `user.availability_changed` | `availability` (rótulo) | `availability` | o rótulo |
| `user.activity_started` | `activity` (rótulo) | `activity` | o rótulo |
| `user.activity_ended` | — | `activity` | ausência observada |

São três, e não dez: o menor conjunto que demonstra substituição de valor, ausência
observada e idempotência. Agenda, localização, conversa, tarefa e estado de sessão
pertencem às fases que trouxerem as fontes correspondentes.

Regras uniformes: `observed_at = event.occurred_at` (tempo de domínio, nunca
`recorded_at`), `source = f"event:{event.event_type}"`, `confidence = 1.0` — o
evento afirma o fato, e o Context Engine não reinterpreta nem estima.

| Situação | Comportamento |
|---|---|
| Tipo não assinado | ignorado, com `DEBUG context.event_ignored` |
| `schema_version` diferente de 1 | ignorado, com `INFO context.event_ignored` (contrato §5) |
| Payload malformado | `InvalidContextError` — permanente |

`InvalidContextError` é `DomainError`, logo `retryable = False`: o bus registra e
manda para dead-letter na primeira tentativa, sem retry, porque repetir produziria
o mesmo erro. O evento continua no Event Store — o fato não se perde, e **nenhuma
segunda semântica de retry** é criada aqui.

`handle()` faz apenas trabalho local: traduz o evento e chama o agregador. Nada de
arquivo, banco ou rede — há teste que prova que o repositório não é tocado durante
o dispatch.

## Reconstrução

`ContextEngine.rebuild_from(store)` refaz a projeção a partir dos eventos já
registrados. É o que torna "projeção derivada" verificável em vez de afirmada, e o
que faz `jarvis context show` funcionar num processo novo — a CLI é de vida curta e
a projeção nasceria vazia sem isso.

A ordem importa: `user.activity_started` seguido de `user.activity_ended` só
resolve certo na ordem em que os fatos foram **registrados**. `read_by_type` já
devolve cada tipo em ordem de persistência, e a reconstrução reordena por
`recorded_at` para recompor a ordem *entre* tipos, usando só o que `RecordedEvent`
expõe. Nenhum método novo foi acrescentado ao port `EventStore`.

Limitações conhecidas, com gatilho concreto de revisão: dois eventos de tipos
diferentes com `recorded_at` idêntico não são desempatáveis (a coluna `sequence` do
adapter não é exposta no domínio), e a leitura é integral, sem cursor. Se qualquer
uma das duas passar a alterar o resultado na prática, a resposta é acrescentar
leitura ordenada/por cursor ao port naquele momento — com o consumidor concreto na
mão, e não por antecipação.

## Snapshots

`ContextSnapshot(snapshot_id, captured_at, context)` é uma captura imutável e
datada, para responder "o que o agente sabia quando decidiu X". Preserva `source`,
`observed_at`, `confidence` e `ttl` de cada campo — não reduz a captura a valores
puros. `stale` não é gravado: é derivável de `observed_at + ttl` contra
`captured_at`.

**Relevância:** a captura só acontece por pedido explícito (`jarvis context
snapshot`), nunca a cada leitura, e só é persistida se o conteúdo mudou em relação
à última vigente. O fingerprint mede **o que o sistema acredita** — valor, origem e
confiança por campo — e ignora os tempos, que avançam a cada leitura mesmo quando
nada foi aprendido. Reobservar o mesmo valor deixa o contexto mais fresco, não
diferente.

### Persistência

`SqliteContextSnapshotRepository` grava em `<JARVIS_DATA_DIR>/context.db` — banco
**próprio**, não uma tabela extra de `events.db`: os dois componentes versionam
schema de forma independente, e o Context Engine não tem por que tocar no
`user_version` do Event Store. Duas propriedades são impostas pelo banco:

- **conteúdo imutável** — trigger que aborta `UPDATE` nas colunas de conteúdo;
- **nada é apagado** — trigger que aborta qualquer `DELETE`.

### Expiração é lógica

`expire_before(cutoff)` **marca** `expired_at` e devolve quantas capturas foram
marcadas; nunca é chamado automaticamente, não há job, retenção implícita nem TTL
de snapshot. As marcadas somem das consultas por default e **continuam legíveis**
com `include_expired=True`. Um snapshot é evidência do que o sistema sabia, e
apagá-lo destruiria a resposta da pergunta que ele existe para responder.

## Uso pelo CLI

```bash
jarvis context show       # a projeção atual, campo a campo
jarvis context snapshot   # captura, se algo mudou desde a última
```

```text
as_of 2026-08-10T08:59:03+00:00
availability   -
utc_offset     -03:00      provider:time                 2026-08-10T08:59:03+00:00  fresh
place          -
device_id      notebook    provider:device               2026-08-10T08:59:03+00:00  fresh
activity       (nenhum)    event:user.activity_ended     2026-08-10T08:59:02+00:00  fresh
next_entry_at  -
conversation   -
task           -
```

`show` reconstrói do Event Store, pergunta aos providers e imprime; campos sem
observação aparecem como `-`. `snapshot` imprime `captured <id>` ou `unchanged`.
Códigos de saída seguem os da Fase 1: `0` ok, `2` entrada inválida, `1` falha de
infraestrutura.

`history` e `expire_before` existem como API do `ContextEngine`, cobertas por
testes, mas **não** são expostas como comando: expor sem caso de uso concreto seria
superfície pública sem consumidor. Fazê-lo depois é aditivo.

## Observabilidade e dados sensíveis

Registros emitidos: `context.provider_failed`, `context.field_updated`,
`context.conflict`, `context.event_applied`, `context.event_ignored`,
`context.snapshot_captured`, `context.snapshot_unchanged`,
`context.snapshots_expired`. Todos carregam campo, origem, estado e contagens.

**Nenhum valor de contexto, payload ou secret é logado em nenhum caminho** — e
`tests/test_context_privacy.py` planta valores reconhecíveis e assere a ausência
deles em todos eles. Pelo mesmo motivo, mensagens de validação não repetem o valor
recusado: ele costuma vir de payload de evento, e uma falha vira log com stack
trace no bus.

## Contexto não é memória

| | Context | Memory |
|---|---|---|
| **Horizonte** | presente, expira por TTL | durável, decai/reforça |
| **Fonte** | eventos recentes + providers | consolidação, experiência, retrieval |
| **Papel na decisão** | "o que está acontecendo agora" | "o que o sistema aprendeu" |

O Context Engine não é dono de memória, e a Memory System não é dona de projeção de
estado atual — ver [memory-system.md](memory-system.md).

## O que não foi implementado, e por quê

- **Adapters de Activity, Calendar e Location** — exigiriam integração externa
  proibida nesta fase; existem como port + doubles.
- **Produtores para `ConversationContext` e `TaskContext`** — os subcontextos são
  exigidos pelo ROADMAP 2.1 e existem, mas ficam permanentemente ausentes até o
  Voice Interface (Fase 6) e o Background Task Manager (Fase 7).
- **Tipos ricos de domínio** (entrada de agenda, referência de conversa) e enums
  fechados de rótulo — nenhum consumidor nesta fase, e inventá-los agora seria
  antecipar as fontes das Fases 5–7.
- **Resolução de conflito plugável e desempate por `confidence`/`source`** — sem
  caso de uso que os pressione.
- **Leitura por offset/cursor no `EventStore`** — a necessidade não se materializou;
  ver "Reconstrução".
- **`correlation_id`/`causation_id` no snapshot** — não há, antes do Agent Runtime,
  fluxo causal que dispare uma captura; campo sem produtor é campo morto.
- **Captura automática por evento** — violaria a regra de não fazer I/O em `handle`.
- **Remoção física de snapshots, retenção automática, TTL configurável em
  `Settings`, upcasting de `schema_version`, métricas e tracing.**

## Documentos relacionados

- Contrato normativo: [architecture-contracts.md §6](architecture-contracts.md#6-context-contract)
- Limites do componente: [architecture-contracts.md §3.2](architecture-contracts.md#32-context-engine)
- Plano da fase: [phase-2-plan.md](phase-2-plan.md)
- Modelo de distribuição consumido: [ADR-0008](adr/0008-synchronous-in-process-event-bus.md)
- Visão geral: [architecture.md](architecture.md)
