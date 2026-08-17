# CLAUDE.md

Guia operacional para sessões do Claude Code trabalhando neste repositório.
Este documento não redefine arquitetura — ele traduz decisões já registradas
em regras diretas de "o que fazer" e "o que não fazer". Em caso de dúvida
sobre *por que* uma regra existe, o documento canônico correspondente é a
fonte de verdade, não este arquivo.

## 0. Antes de qualquer coisa

1. **`ROADMAP.md` é a fonte de verdade sobre o que é a subfase atual.** Se uma
   instrução de sessão descrever uma subfase de forma diferente do que está
   escrito em `ROADMAP.md`, o `ROADMAP.md` prevalece — pare e sinalize a
   divergência em vez de presumir qual versão está certa.
2. Leia `README.md`, `ROADMAP.md`, `docs/architecture-contracts.md`, os ADRs
   relevantes em `docs/adr/` e o estado real de `src/`/`tests/` antes de
   planejar qualquer mudança. Não presuma decisão que não esteja documentada.
3. Trabalhe apenas no escopo da subfase autorizada na sessão atual. Não
   adiante trabalho de subfases futuras, mesmo que pareça natural ou
   eficiente fazê-lo agora.

## 1. Arquitetura — resumo operacional

Fonte canônica: [`docs/architecture-contracts.md`](docs/architecture-contracts.md)
e os ADRs em [`docs/adr/`](docs/adr/). Não duplique o conteúdo desses
documentos aqui — consulte-os para qualquer detalhe além do resumo abaixo.

- Regra de dependência (Ports & Adapters, [ADR-0001](docs/adr/0001-ports-and-adapters-dependency-rule.md)):
  **Core** (Domain + Application) nunca importa **Infrastructure** ou
  **Interfaces**. Infrastructure implementa ports definidos pelo Core.
  Interfaces aciona casos de uso do Core. Só o **Composition Root** conhece
  Core, Infrastructure e Interfaces ao mesmo tempo.
- **A separação física em pastas (`domain/`, `application/`,
  `infrastructure/`, `interfaces/`) ainda não existe neste repositório, de
  propósito** — ver "Alternativas consideradas" do ADR-0001. Ela só deve ser
  criada quando uma subfase do roadmap determinar isso explicitamente. Não a
  antecipe especulativamente, mesmo que uma instrução de sessão pareça
  pedir isso — confirme primeiro contra `ROADMAP.md` (ver §0.1).
- O Agent Runtime nunca executa ações diretamente; toda proposta de ação
  passa pelo Policy Engine, autoridade determinística única sobre
  `allow`/`deny`/`require_confirmation` ([ADR-0003](docs/adr/0003-policy-engine-safety-authority.md)).
- Não acoplar a um único fornecedor de LLM: raciocínio depende do port
  `LLMProvider`; embeddings dependem de um port `EmbeddingProvider`
  separado ([ADR-0002](docs/adr/0002-llm-provider-abstraction.md)).
- Eventos são imutáveis; correções são novos eventos, nunca update in-place
  ([ADR-0004](docs/adr/0004-event-immutability-and-timestamps.md)).
- Skill ≠ Tool ≠ MCP Server ≠ MCP Tool — cada um com responsabilidade
  própria; risco/permissão vivem na Skill, nunca na Tool
  ([ADR-0005](docs/adr/0005-skill-tool-mcp-distinction.md)).
- Configuração de sistema, secrets, preferências do usuário e estado
  operacional são quatro categorias distintas que não se misturam
  ([ADR-0006](docs/adr/0006-configuration-vs-preferences-vs-state.md)).

## 2. Estrutura atual do projeto

```text
src/jarvis/
├── __init__.py    # __version__
├── __main__.py    # permite `python -m jarvis`
├── cli.py         # entry point (argparse); composition root
├── config.py      # Settings (pydantic-settings, prefixo JARVIS_)
├── errors.py      # taxonomia base do Core (DomainError, InfrastructureError)
├── events/        # Event System (Fase 1)
│   ├── event.py       # Event, RecordedEvent, JsonValue, geradores de event_id
│   ├── errors.py      # InvalidEventError, EventStoreError, Append/Read
│   ├── ports.py       # EventStore, EventConsumer (Protocols), AppendResult
│   ├── bus.py         # EventBus, RetryPolicy, DeadLetter
│   ├── publisher.py   # EventPublisher (store → bus)
│   └── adapters/      # Infrastructure: serialization, sqlite_store, logging_consumer
├── context/       # Context Engine (Fase 2)
│   ├── observation.py # Observation[T], Freshness, validadores
│   ├── model.py       # ContextField, os 7 subcontextos, CurrentContext, ContextUpdate
│   ├── freshness.py   # TtlPolicy (TTL por campo)
│   ├── errors.py      # InvalidContextError, ContextProviderError, ContextSnapshotError
│   ├── ports.py       # ContextProvider, ContextSnapshotRepository (Protocols)
│   ├── projection.py  # ContextProjection, ContextConflict
│   ├── aggregator.py  # ContextAggregator
│   ├── consumer.py    # ContextEventConsumer, CONTEXT_EVENT_TYPES
│   ├── engine.py      # ContextEngine (reconstrução, captura, histórico, expiração)
│   └── adapters/      # Infrastructure: time/device provider, serialization, sqlite_snapshots
├── memory/        # Memory System (Fase 3)
│   ├── memory.py       # MemoryType, MemoryOrigin, Provenance, Memory, StoredMemory
│   ├── embedding.py    # EmbeddingModel, MemoryEmbedding, cosine_similarity
│   ├── errors.py       # InvalidMemoryError, EmbeddingProviderError, MemoryRepositoryError
│   ├── ports.py        # MemoryRepository, EmbeddingProvider (Protocols), MemoryCriteria
│   ├── ranking.py      # RankingWeights, meias-vidas por tipo, RelevanceScore, score()
│   ├── retrieval.py    # RetrievalQuery, RetrievalResult/Outcome, MemoryRetrieval
│   ├── consolidation.py # find_duplicate, find_contradiction, find_promotions
│   ├── manager.py      # MemoryManager (remember, retrieve, ciclo de vida, reembed, consolidate)
│   └── adapters/       # Infrastructure: sqlite_repository, hashing_embeddings,
│                       #   event_consumer, context_bridge
├── agent/         # Agent Runtime (Fase 4)
│   ├── errors.py       # InvalidDecisionError, LLM*Error, PromptTooLargeError
│   ├── messages.py     # Role, Message, LLMRequest/Response, StopReason, TokenUsage
│   ├── ports.py        # LLMProvider (Protocol)
│   ├── decision.py     # DecisionType, MemoryProposal, ActionProposal, Decision, parse_decision
│   ├── conversation.py # ConversationTurn, Conversation (em memória, não persistida)
│   ├── input.py        # UserMessage, EventTrigger, EventSummary, ActionResultSummary
│   ├── importance.py   # ImportanceWeights/Assessment, assess(), should_reason()
│   ├── prompt.py       # SYSTEM_INSTRUCTION, ReasoningEnvelope, PromptBudget, PromptBuilder
│   ├── runtime.py      # AgentRuntime, AgentTurn, LLMRetryPolicy, GenerationDefaults
│   └── adapters/       # Infrastructure: gemini (REST via urllib, sem SDK)
├── policy/        # Policy Engine (Fase 5)
│   ├── vocabulary.py · rules.py · verdict.py · engine.py · errors.py · ports.py
├── skills/        # Skill Framework (Fase 5)
│   ├── skill.py · registry.py · errors.py
│   └── builtin/       # register_builtin_skills: files.py, system.py
├── tools/         # Tool Abstraction + Router + MCP (Fase 5)
│   ├── tool.py · schema.py · ports.py · registry.py · router.py · access.py · errors.py
│   └── adapters/      # local_backend, mcp_config, mcp_protocol, mcp_stdio, mcp_client
├── execution/     # Action Execution (Fase 5) — único que conhece policy+skills+tools
│   ├── identity.py · model.py · ports.py · events.py · orchestrator.py · consumer.py
│   └── adapters/      # sqlite_actions, event_audit
├── voice/         # Voice Interface (Fase 6) — importa só `jarvis.errors`
│   ├── errors.py · audio.py · ports.py · vad.py · wake.py · session.py · loop.py
│   └── adapters/      # sounddevice_audio, groq_stt, google_tts, wave_io,
│                      #   wake_push_to_talk, wake_transcription, sqlite_sessions, retry
└── interface/     # Observability Interface (Fase 6) — somente leitura
    ├── errors.py · viewmodel.py · service.py · live.py
    └── adapters/      # http_panel, page

tests/               # estrutura plana; `factories.py` monta eventos, e
                     # `context_doubles.py`, `memory_doubles.py`, `agent_doubles.py`,
                     # `action_doubles.py` montam os doubles de teste
docs/
├── README.md · architecture.md · architecture-contracts.md
├── phase-1-plan.md … phase-6-plan.md       # planos aprovados das Fases 1–6
├── event-system.md · context-system.md · memory-system.md · agent-runtime.md
│                                           # documentação de implementação
├── skills.md · mcp.md · security.md · voice.md · interface.md
└── adr/                                    # 0001–0025
```

O projeto concluiu as Fases 1 a 6: existem Event System real (domínio, bus,
store SQLite, consumers), Context Engine real (observações com proveniência e TTL
por campo, providers de tempo e dispositivo, agregação com conflitos explícitos,
consumer de eventos, reconstrução a partir do Event Store e snapshots persistidos),
Memory System real (memória imutável com supersessão, `EmbeddingProvider`
independente de LLM, retrieval estruturado e semântico, ranking explicável,
ciclo de vida completo, consolidação por deduplicação/contradição/promoção,
integração de mão única com Event System e Context Engine), Agent Runtime real
(`LLMProvider` vendor-agnóstico com adapter Gemini em nuvem, `Decision`
estruturada e validada, Importance Engine determinístico pré-LLM, prompt
assembly com orçamento, retry/timeout/observabilidade) e a cadeia de execução
completa (Policy Engine determinístico, Skill Registry com Skills embutidas,
Tool Router, cliente MCP sobre stdio, confirmação de ações de risco e trilha de
auditoria em eventos).

A Fase 6 acrescentou a camada de voz (wake word sem IA local, STT na Groq, TTS no
Google Cloud, sessão persistida com retenção, interrupção) e o painel de
observabilidade local — este **somente leitura**, sem nenhuma rota que inicie
ação. `jarvis.voice` importa de `jarvis` apenas `jarvis.errors`; o resto do
sistema chega por um port próprio implementado no composition root.

**Nota histórica (válida no fim da Fase 6, hoje desatualizada):** nesta altura
do projeto, Notification System e Trigger Engine ainda não existiam. Ambos
foram implementados na Fase 7 (subfases 7.1 e 7.3) e o restante desta seção
(§2) segue sem atualização retroativa desde então — ver `ROADMAP.md` para o
estado real pós-Fase-7/8. À época, a consequência direta era: o Agent Runtime
**propõe e para**; `Decision.act` só virava execução via `--execute` (ou
`JARVIS_VOICE_EXECUTE_ACTIONS`), e `notify`/`ask` não entregavam nada fora do
terminal e do painel — o toast do painel era renderização de evento existente,
não um Notification System.
`cli.py` é o composition root: único módulo que conhece Core,
Infrastructure e Interfaces ao mesmo tempo, único que lê a credencial do LLM, e
também quem aplica `Decision.memory` ao Memory System
([ADR-0018](docs/adr/0018-memory-writes-outside-the-policy-engine.md)) — o
runtime continua sem escrever nada.

O padrão estabelecido na Fase 1 para um componente novo é `src/jarvis/<componente>/`
com módulos de Core na raiz e um subpacote `adapters/` — **não** a separação física
global em `domain/`/`application/`/`infrastructure/`, que continua proibida (§1).
Não crie diretórios ou módulos para componentes que ainda não têm comportamento
real — ver regra 11 do `ROADMAP.md` ("Não adicionar infraestrutura complexa sem
necessidade concreta").

## 3. Convenções de código

Definidas em [`pyproject.toml`](pyproject.toml); não redefina aqui, apenas
cumpra:

- Python 3.13, type hints obrigatórios (mypy `strict = true`).
- Ruff como formatter e linter (`line-length = 100`; regras `E`, `F`, `I`,
  `UP`, `B`, `SIM`, `RUF`).
- Docstrings apenas quando agregam contexto que o código não expressa
  sozinho (módulo/classe já seguem esse padrão no código existente) —
  mesma regra de comentários do restante deste ambiente: não documente o
  óbvio.
- Nenhuma dependência nova (runtime ou dev) sem necessidade concreta do
  escopo da subfase atual.

## 4. Regras de teste

- `pytest` com `testpaths = ["tests"]`, `--strict-markers --strict-config`
  (`pyproject.toml`). Nenhum teste é ignorado silenciosamente.
- Toda subfase precisa de testes relevantes escritos e passando antes de
  ser marcada concluída — regra de conclusão do `ROADMAP.md`, não uma
  preferência de estilo.
- `tests/` hoje espelha `src/jarvis/` em estrutura plana (`test_cli.py`,
  `test_config.py`, `test_main.py`). Não crie `tests/unit/`, `tests/integration/` ou
  `tests/architecture/` antes que exista necessidade concreta — mesma
  lógica da regra 11 do roadmap.
- Nenhum teste depende de rede, banco de dados real ou serviço externo
  nesta fase (não há nenhum desses componentes implementados ainda).

## 5. Regras para mudança arquitetural

- Qualquer mudança que altere direção de dependência, fronteira de
  componente ou o contrato de um port existente deve ser conferida contra
  `docs/architecture-contracts.md` antes de ser implementada.
- Uma decisão nova, difícil de reverter e com alternativa real descartada
  vira ADR — critério completo em [`docs/adr/README.md`](docs/adr/README.md).
  Não crie ADR para detalhe de campo, nome ou formato reversível sem custo.
- Um ADR aceito nunca é editado para refletir mudança de decisão — uma
  mudança gera um novo ADR que marca o anterior como `Superseded by
  ADR-NNNN`.

## 6. Regras para criação de Events (Fase 1 do roadmap)

Ao implementar o Event System, todo `Event`:

- é imutável após persistido; correções são novos eventos com
  `causation_id` apontando para o original, nunca update in-place;
- tem `occurred_at` (tempo de domínio, definido pelo producer) distinto de
  `recorded_at` (atribuído só pelo Event Store, não editável pelo
  producer);
- tem `event_id` idealmente determinístico a partir de uma chave natural
  da source, para que o Event Store trate reinserção como no-op, não erro;
- usa `correlation_id`/`causation_id` para causalidade — a ordenação do
  Event Store (via `recorded_at`) é garantia de leitura estável, não de
  relógio monotônico global.

Detalhe completo: [`architecture-contracts.md §5`](docs/architecture-contracts.md#5-event-contract)
e [ADR-0004](docs/adr/0004-event-immutability-and-timestamps.md).

## 7. Regras para criação de Skills (Fase 5 do roadmap)

Ao implementar Skills:

- `risk` e `confirmation_requirement` são autodeclarações da Skill — nunca
  concedem autorização à própria Skill. A decisão de `allow`/`deny`/
  `require_confirmation` é exclusiva do Policy Engine, que pode divergir da
  autodeclaração (ex. denylist estática mais restritiva).
- Uma Skill nunca executa sua parte de risco sem um `PolicyApproval`
  correspondente.
- Uma Skill recebe Context/Memory como parâmetro explícito — não os busca
  por conta própria.
- Uma Skill pode compor múltiplas Tools; risco e permissão vivem na Skill,
  nunca na Tool ou no MCP Server.

Detalhe completo: [`architecture-contracts.md §8`](docs/architecture-contracts.md#8-skill-contract),
[ADR-0003](docs/adr/0003-policy-engine-safety-authority.md) e
[ADR-0005](docs/adr/0005-skill-tool-mcp-distinction.md).

## 8. Regras de documentação

- Duas categorias com regras diferentes (ver [`docs/README.md`](docs/README.md)):
  **contratos** (`architecture-contracts.md`, `adr/`) existem *antes* do
  código que restringem; **documentação de implementação** (`event-system.md`,
  `memory-system.md` etc., a partir da subfase 0.5) é criada junto da
  funcionalidade que descreve, não antes.
- Não crie documentação de componente para algo que ainda não tem
  comportamento real implementado.
- Atualize `docs/architecture-contracts.md` ou crie um ADR apenas quando a
  implementação introduzir uma decisão arquitetural genuinamente nova — não
  quando ela apenas materializa o que já está documentado.
- `JARVIS_Arquitetura.html` (não versionado, ver `.gitignore`) é material de
  apresentação: existe só para mostrar o projeto visualmente a outras pessoas.
  Não é fonte de verdade sobre arquitetura, escopo ou estado do roadmap, não
  precisa ser atualizado junto do código e não deve ser lido para planejar
  nem para decidir implementação. Ignore-o.

## 9. Workflow de Git e commits

- **Workflow recomendado por subfase** (não uma limitação técnica do Claude
  Code, mas o processo que este projeto segue): Explorar repositório →
  Planejar → Revisar plano com o usuário → Aprovação explícita → Implementar
  → Testar → Revisar → Commit → Atualizar `ROADMAP.md`. O agente deve
  respeitar o escopo da subfase autorizada na sessão atual
  independentemente de quantas sessões forem necessárias para completá-la.
- Prefixos de commit já em uso no histórico: `chore`, `docs`, `feat`,
  `test`, `refactor`, `perf`, `release` — mensagem no imperativo, curta,
  seguindo o padrão de "Commit esperado" de cada subfase em `ROADMAP.md`.
- Nunca commitar sem aprovação explícita do usuário na sessão corrente.
  Aprovação em uma sessão anterior não vale para a sessão atual.
- Nunca usar `--no-verify`, bypass de assinatura, `git push --force` para
  `main`, ou amend de commit já publicado, sem pedido explícito do usuário.
- `ROADMAP.md` só é atualizado (checkboxes + tabela de histórico) para a
  subfase efetivamente concluída e validada nesta sessão — nunca para
  subfases futuras.

## 10. Limites de autonomia do agente

- Implementar exatamente o escopo aprovado da subfase atual — não menos
  (deixando a "Regra de conclusão" do roadmap sem cumprir), não mais
  (adiantando subfases futuras ou criando abstração especulativa).
- Nunca presumir decisão arquitetural não documentada; sinalizar
  explicitamente qualquer ambiguidade ou conflito encontrado entre a
  instrução recebida e `ROADMAP.md`/`architecture-contracts.md`/ADRs, em vez
  de resolver silenciosamente a favor de uma leitura.
- Não criar classes vazias, interfaces vazias, repositories falsos,
  services sem comportamento, factories genéricas, container de DI, ou
  qualquer abstração sem consumidor real — princípio explícito da 0.3
  (`architecture-contracts.md §1`) e do `ROADMAP.md` (regra 11).
- **Não fazer o Agent Runtime aplicar as decisões que produz.** Ele monta
  contexto, raciocina e devolve uma `Decision`; quem aplica é sempre o
  composition root — `ActionExecutor` para `Decision.action`
  ([ADR-0016](docs/adr/0016-action-execution-orchestrator.md)), `MemoryManager`
  para `Decision.memory`
  ([ADR-0018](docs/adr/0018-memory-writes-outside-the-policy-engine.md)); a
  notificação depende do Notification System (7.3), que ainda não existe. Dar
  esse atalho ao runtime quebraria o [ADR-0003](docs/adr/0003-policy-engine-safety-authority.md)
  e os testes estruturais de `tests/test_agent_architecture.py`.
- Manter o código executável ao final de cada subfase: `uv run pytest`,
  `uv run ruff check`, `uv run ruff format --check` e `uv run mypy` devem
  passar, e o CLI (`uv run jarvis`) deve continuar funcionando.

## 11. Segurança

- Nenhum secret (`JARVIS_*_API_KEY` e equivalentes) é logado, commitado ou
  incluído em texto claro em evento, memória ou audit log — mesmo mecanismo
  de leitura de configuração (env/`.env`), regra adicional de nunca vazar
  ([ADR-0006](docs/adr/0006-configuration-vs-preferences-vs-state.md)).
- O LLM nunca é a autoridade final de segurança sobre uma ação — essa
  responsabilidade é exclusiva do Policy Engine, determinístico, sem
  chamada de LLM na própria decisão de autorização
  ([ADR-0003](docs/adr/0003-policy-engine-safety-authority.md)).
- `.gitignore` já cobre `.env`, `.env.*` (exceto `.env.example`) e
  `data/` — não adicione segredo real a nenhum arquivo versionado, nem
  mesmo em exemplo ou teste.
