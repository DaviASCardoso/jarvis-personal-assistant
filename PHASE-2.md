# Fase 2 — Context Engine

> Especificação operacional da Fase 2 do Jarvis. Preparada a partir do estado
> publicado do repositório em `c40cb547e65e411323134e39caa3d1206c032bf2`.
> Ela complementa, mas não substitui, `ROADMAP.md`, `CLAUDE.md`,
> `docs/architecture-contracts.md` e os ADRs aceitos.

## 1. Objetivo

Implementar o Context Engine: o componente que transforma eventos já registrados
e observações de fontes de contexto em uma projeção consultável do estado atual
do usuário e do sistema.

O resultado da fase deve permitir responder, de forma estruturada, **o que o
sistema sabe agora**, com a origem, instante de observação, confiança e estado de
validade de cada dado. Também deve permitir congelar essa visão em snapshots
imutáveis e consultá-los historicamente.

O Context Engine não é memória, não toma decisões, não chama LLM e não executa
ações. É uma projeção de presente, derivada e reconstruível.

## 2. Fontes normativas e precedência

Em caso de divergência, siga esta ordem:

1. `ROADMAP.md` — escopo e itens obrigatórios da fase;
2. `CLAUDE.md` — regras operacionais do repositório;
3. `docs/architecture-contracts.md`, sobretudo §§ 1–6, 11, 13 e 14;
4. ADRs aceitos, em especial ADR-0001, ADR-0004, ADR-0007 e ADR-0008;
5. `docs/context-system.md` e `docs/event-system.md`;
6. implementação e testes existentes;
7. este documento.

Se uma divergência impedir uma implementação segura, registre-a no plano e pare
para orientação; não a resolva silenciosamente. Decisões arquiteturais novas,
difíceis de reverter, exigem ADR novo conforme `docs/adr/README.md`.

## 3. O que existe ao iniciar

A Fase 1 entrega:

- `Event` imutável e `RecordedEvent` separado; somente o Event Store define
  `recorded_at`;
- `EventStore` como port e `SqliteEventStore` como adapter persistente;
- `EventBus` concreto, síncrono e em processo;
- `EventPublisher`, cuja ordem é **persistir → deduplicar → dispatch**;
- `EventConsumer` com `handle(recorded_event)` e inscrição opcional por tipo;
- retry limitado e dead-letter do bus; falha de um consumer não desfaz um evento
  já gravado;
- CLI como composition root atual.

Consequência: o Context Engine deve ser um consumer síncrono e rápido. Nenhum
consumer desta fase deve fazer I/O externo bloqueante durante `handle`. Polls de
providers são acionados explicitamente pelo agregador/composition root, não pelo
bus. Se isso deixar de ser adequado, a condição de revisão é a do ADR-0008, não
uma introdução local de `asyncio`.

## 4. Escopo obrigatório

O roadmap divide a fase em cinco resultados, a serem planejados e executados como
uma unidade:

| Entrega | Resultado |
|---|---|
| 2.1 Context Domain | `CurrentContext`, seus sete subcontextos e metadados temporais. |
| 2.2 Context Providers | port `ContextProvider`, providers Time, Device, Activity, Calendar e Location, além de doubles de teste. |
| 2.3 Context Aggregation | coleta, merge, conflitos, freshness/TTL e `get_current_context`. |
| 2.4 Context Snapshots | modelo, persistência, consulta histórica e expiração. |
| 2.5 Context Integration | consumer de eventos, wiring e fluxo ponta a ponta. |

Os commits podem ser incrementais e coerentes, mas a conclusão só ocorre quando
todos os itens acima, documentação, gates e atualização factual do roadmap forem
concluídos. Não faça push nesta fase.

## 5. Limites explícitos

Não implementar nesta fase:

- Memory System, recuperação, embeddings, scoring ou preferências persistentes;
- Agent Runtime, decisões, prompt assembly ou LLM/Embedding Provider;
- Policy Engine, Skills, Tools, MCP, permissões ou confirmações;
- integrações reais autenticadas com calendário, localização, SO ou nuvem, salvo
  se o repositório já trouxer uma exigência explícita e segura;
- watchers/daemons contínuos, filas, broker, `asyncio`, scheduler, API/GUI/voz;
- banco de produção, PostgreSQL, pgvector, Docker ou migrações genéricas;
- inferência: ausência de dado deve permanecer ausente, não ser preenchida por
  heurística.

Os providers iniciais devem ser locais, determinísticos ou adaptadores mínimos
testáveis. Para Calendar/Location/Activity, a interface e mocks podem existir sem
credencial nem chamada externa. Não finja que uma integração real existe.

## 6. Modelo e invariantes do domínio

### 6.1 `CurrentContext`

É uma visão do agora e deve agrupar, quando aplicável:

- `UserContext`;
- `EnvironmentContext`;
- `DeviceContext`;
- `ActivityContext`;
- `ScheduleContext`;
- `ConversationContext`;
- `TaskContext`.

Os nomes exatos, tipos e campos pertencem ao plano, mas cada valor observável
precisa preservar seus próprios metadados. Não use um grande `dict[str, Any]`
como substituto do domínio tipado.

### 6.2 Valor contextual observado

Cada valor que veio de provider ou evento deve carregar, no mínimo:

- valor tipado (ou ausência explícita);
- `observed_at`: quando a observação ocorreu;
- `source`: provider ou evento de origem;
- `confidence`: confiança associada à observação;
- regra de TTL/freshness do campo;
- estado derivado de validade (`fresh`/`stale`, ou equivalente explícito).

`observed_at` não é `occurred_at` nem `recorded_at`: o primeiro descreve a
observação incorporada ao contexto; os demais pertencem ao fato de origem e ao
registro dele. Todos os datetimes devem ter timezone.

### 6.3 Freshness e ausência

- TTL é definido **por tipo de campo**, nunca por `CurrentContext` inteiro.
- Quando o TTL vence, o valor vira `stale`; não desaparece nem é silenciosamente
  renovado.
- Decidir se `stale` serve a uma decisão futura é do consumidor (por exemplo,
  Agent Runtime), não deste componente.
- Sem observação, o campo é `None`/ausente. O Context Engine não inventa valores.

Evite TTL global e magic numbers espalhados. Uma política simples e local de TTL
por campo é suficiente; só introduza abstração adicional se houver mais de um
consumidor concreto.

### 6.4 Conflitos

Para a mesma informação, a regra padrão é **`observed_at` mais recente vence, por
campo**. O conflito precisa ficar observável/registrado; não descarte a informação
perdedora em silêncio. Estratégias plugáveis por campo são futuras até um caso de
uso concreto justificá-las.

Empate de `observed_at`, dados inválidos, confiança incompatível e semântica de
substituição devem receber uma regra determinística, pequena e testada. Se a regra
não decorrer dos contratos existentes e impactar o histórico/auditoria, trate-a
como decisão a avaliar para ADR.

### 6.5 `ContextSnapshot`

Um snapshot é uma captura imutável, datada e autocontida de `CurrentContext`, para
responder o que o sistema acreditava saber em um ponto do passado. Deve preservar
os metadados dos campos, inclusive `stale`, `source` e `observed_at`; não reduza a
captura a valores puros.

Snapshot não substitui Event Store nem Memory. Correções criam uma nova projeção ou
novo snapshot — não alteram uma captura histórica já persistida.

## 7. Arquitetura e fronteiras

Repita o padrão físico da Fase 1: `src/jarvis/context/` para Core e
`src/jarvis/context/adapters/` para detalhes concretos. Não crie prematuramente
as quatro camadas top-level. Um teste arquitetural deve impedir o Core de importar
`context.adapters`, `sqlite3`, settings ou bibliotecas de provider.

O domínio/Core pode conhecer apenas modelos, ports e erros próprios. O adapter de
persistência implementa um port de snapshot; o adapter pode usar SQLite se esta for
a escolha mínima e justificada, mas não deve vazar SQL, cursor ou linha de banco.

`cli.py` permanece o composition root: carrega Settings, instancia adapters,
conecta providers/agregador/consumer e assina o consumer no bus. Core não chama
`load_settings()`.

Não declare um port apenas por simetria. Há motivos concretos para:

- `ContextProvider`: várias fontes independentes;
- repositório de snapshots: fronteira de persistência exigida pelo contrato.

O agregador, consumer e representação do domínio podem permanecer concretos se
não houver segunda implementação ou consumidor real que justifique uma interface.

## 8. Providers

Um `ContextProvider` entrega observações contextualizadas, não valores crus. O
contrato planejado deve tornar explícitos: identidade/origem, quais campos produz,
quando foi observado, confiança, falha e possibilidade de ausência.

Providers exigidos pelo roadmap:

- Time: fonte local/determinística; relógio injetável nos testes;
- Device: estado mínimo e verificável do dispositivo, sem automação do SO;
- Activity: somente o dado que pode ser obtido com segurança no escopo;
- Calendar: interface/double sem OAuth ou integração de produção;
- Location: interface/double sem rastreamento real, permissão ou serviço externo.

O agregador não deve depender de subclasses concretas. Erros de infraestrutura dos
providers devem ser traduzidos para a taxonomia do Core; uma falha de provider não
deve apagar valores previamente conhecidos. A política exata de degradar/propagar
precisa ser explícita, determinística e coberta por testes.

## 9. Agregação e integração com eventos

O agregador é dono de:

1. solicitar/receber observações dos providers;
2. validar e normalizar a entrada no domínio;
3. combinar por campo;
4. aplicar freshness/TTL no momento de leitura;
5. registrar conflitos sem expor dados sensíveis nos logs;
6. devolver `get_current_context()`.

O consumer de contexto recebe somente `RecordedEvent`, pois o bus garante que ele
é durável e não duplicado. Ele deve filtrar explicitamente apenas os tipos que o
Context Engine sabe projetar. O plano deve nomear esses tipos e a transformação
para os campos; não use catch-all que interprete payloads arbitrários.

`handle()` deve ser idempotente para o mesmo evento. Como o publisher evita
redispatch de duplicata, essa propriedade é proteção adicional contra chamadas
diretas, reprocessamento e evolução futura — não uma desculpa para ignorar o
contrato da Fase 1. Consumo de evento deve atualizar a projeção de forma
determinística e não realizar I/O bloqueante.

Persistência vem antes de dispatch. Portanto, se o consumer falhar, o Event Store
continua como registro recuperável do fato; retry/dead-letter seguem as regras já
existentes do bus. Não introduza uma segunda semântica de retry no Context Engine.

## 10. Snapshots e persistência

O roadmap pede persistir snapshots relevantes, consulta histórica e expiração.
O plano deve definir, usando os contratos atuais:

- o que torna um snapshot relevante (somente gatilhos concretos, nunca captura a
  cada leitura por padrão);
- identidade, timestamp de captura e relação opcional com `correlation_id`/
  `causation_id` quando ela existir;
- serialização estável de valores e metadados;
- repository port mínimo: salvar, consultar histórico e expirar;
- semântica de expiração: nunca apagar silenciosamente uma evidência que precise
  ser auditável; se remoção for necessária, deve ser explícita e testável;
- imutabilidade no domínio e no armazenamento.

SQLite é aceitável para o primeiro adapter apenas se o plano demonstrar que reutiliza
a simplicidade operacional atual e mantém a fronteira por port. Não reutilize a
tabela `events` como tabela de snapshots nem altere eventos imutáveis.

## 11. Erros, logs e dados sensíveis

Use a taxonomia existente: erros de domínio são distintos de infraestrutura; adapter
traduz exceções nativas e não as deixa vazar pelo Core. Não use `except Exception`
para engolir erro. Classifique retryable/permanent conforme o contrato.

Logs são estruturados e carregam `correlation_id` quando disponível. Registre
identidade de provider, campo, estado de freshness e conflito, mas não valores de
contexto/payloads que possam conter dados pessoais. Não persistir secrets,
credenciais, tokens ou localização precisa em logs/eventos/snapshots por acidente.

## 12. Testes e critérios observáveis

Além dos testes já existentes, a fase deve cobrir comportamento, não contagem:

- construção/validação/imutabilidade dos modelos;
- datetime aware, ausência e metadados por campo;
- TTL por campo e transição fresh → stale com clock injetável;
- resolução de conflito por `observed_at`, inclusive empate definido;
- providers e suas falhas/ausências com doubles determinísticos;
- agregação de múltiplas fontes sem inferência;
- consumer: filtro de tipos, atualização determinística, idempotência e falha;
- snapshots: captura fiel, imutabilidade, round-trip real no adapter, histórico e
  expiração;
- integração Event → EventPublisher → EventBus → Context Consumer →
  `get_current_context()` → snapshot/reconsulta;
- testes de fronteira arquitetural Core → adapters e de que nenhum Core usa
  SQLite/settings;
- regressão da CLI e da suíte da Fase 1.

Os testes de integração devem usar o adapter real escolhido, sem API externa,
credencial ou clock real. Não durma em testes: injete clock e qualquer função de
tempo necessária.

## 13. Documentação e roadmap

Atualize documentação somente para refletir o que existe:

- `docs/context-system.md`: detalhes de implementação, API e limitações reais;
- `CLAUDE.md`: árvore/estado factual, se a fase mudar o que ele descreve;
- `docs/README.md` e README apenas se comandos/estrutura pública mudarem;
- ADR novo somente se uma decisão arquitetural relevante não estiver coberta.

Não reescreva contratos aceitos para acomodar detalhes de implementação. Marque
apenas os itens 2.1–2.5 e a conclusão da Fase 2 depois dos gates e commits; não
toque fases futuras.

## 14. Gates e Definition of Done

Antes de encerrar, executar sem relaxar regras:

```text
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

A Fase 2 está concluída apenas quando:

- todos os itens 2.1–2.5 do roadmap estão implementados e testados;
- `CurrentContext` é projeção derivada, não fonte de verdade;
- cada campo preserva origem, observação, confiança e validade;
- conflito e stale são explícitos, nunca silenciosos;
- snapshots são imutáveis, persistidos e consultáveis historicamente;
- integração com Event System respeita persistir → deduplicar → dispatch;
- Core não importa adapters/SQLite/configuração;
- não há provider externo real, Memory, Agent, Policy ou escopo futuro acidental;
- documentação factual está atualizada, ADRs necessários existem;
- todos os gates e CI estão verdes;
- commits coerentes existem, a árvore está limpa e nenhum push foi feito.

## 15. Riscos a controlar

| Risco | Controle esperado |
|---|---|
| Contexto virar memória disfarçada | TTL, projeção derivada e proibição de retrieval/preferências. |
| Campo global stale mascarar dado velho | metadados e TTL por campo. |
| Provider externo ampliar escopo/segurança | adapters mínimos, mocks e nenhum OAuth/API real. |
| Consumer bloquear o publisher | `handle` puramente local e síncrono; polling fora do bus. |
| Perder explicabilidade | source, observed_at, confidence e conflitos preservados no snapshot. |
| Acoplamento ao SQLite | repository port e adapter isolado. |
| Logs exporem dados pessoais | logs estruturados de metadados, sem valores/payloads. |
| Abstração especulativa | ports somente onde há múltiplas fontes ou persistência concreta. |

