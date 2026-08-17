# Jarvis — Roadmap de Desenvolvimento

> Roadmap técnico para desenvolvimento incremental do agente pessoal de IA.
>
> **Duração planejada:** 16 semanas  
> **Metodologia:** uma sessão do Claude Code por subfase  
> **Fluxo:** Planejamento → Revisão → Implementação → Testes → Revisão → Commit  
> **Status inicial:** Em desenvolvimento

---

# Visão geral

O sistema será construído em oito fases (a Fase 9 é uma adição pós-v0.1, ver
nota na própria seção — não fazia parte do plano original de 16 semanas):

- [x] **Fase 0 — Foundation**
- [x] **Fase 1 — Event System**
- [x] **Fase 2 — Context Engine**
- [x] **Fase 3 — Memory System**
- [x] **Fase 4 — Agent Runtime**
- [x] **Fase 5 — Skills + MCP**
- [x] **Fase 6 — Voice**
- [x] **Fase 7 — Proactivity + Autonomy**
- [x] **Fase 8 — Integration + Hardening**
- [x] **Fase 9 — Deepening Reasoning + Autonomy** (adicionada pós-v0.1)

## Metodologia de desenvolvimento

Cada subfase deve ser executada em uma nova sessão do Claude Code.

```text
Nova sessão
    ↓
Exploração do repositório
    ↓
Planejamento
    ↓
Revisão do plano
    ↓
Aprovação
    ↓
Implementação
    ↓
Testes
    ↓
Revisão
    ↓
Commit
    ↓
Atualização deste ROADMAP.md
```

### Regra de conclusão

Uma subfase só pode ser marcada como concluída quando:

- implementação concluída;
- testes relevantes escritos;
- testes passando;
- documentação necessária atualizada;
- arquitetura preservada;
- nenhum problema crítico conhecido;
- commit criado;
- item correspondente marcado como `[x]`.

---

# FASE 0 — FOUNDATION

**Objetivo:** estabelecer a fundação técnica, arquitetural e documental do projeto.

**Período:** Semana 1

## 0.1 — Inicialização do repositório

- [x] Inspecionar ambiente atual
- [x] Inicializar/verificar Git
- [x] Definir estrutura inicial do projeto
- [x] Definir projeto Python
- [x] Criar arquivos iniciais
- [x] Criar `.gitignore`
- [x] Criar `.env.example`
- [x] Criar README inicial

**Commit esperado:**

```text
chore: initialize repository
```

---

## 0.2 — Tooling e ambiente de desenvolvimento

- [x] Definir gerenciador de dependências
- [x] Configurar ambiente virtual
- [x] Configurar formatter
- [x] Configurar linter
- [x] Configurar type checking
- [x] Configurar pytest
- [x] Configurar comandos de desenvolvimento
- [x] Definir estratégia inicial de Docker
- [x] Documentar setup local

**Commit esperado:**

```text
chore: establish development tooling
```

---

## 0.3 — Contratos arquiteturais

- [x] Definir princípios arquiteturais
- [x] Definir limites entre componentes
- [x] Definir regras de dependência
- [x] Definir contratos entre módulos
- [x] Definir política de desacoplamento do LLM
- [x] Definir política de eventos
- [x] Definir política de memória
- [x] Definir política de ferramentas
- [x] Definir política de segurança

**Commit esperado:**

```text
docs: establish architectural contracts
```

---

## 0.4 — CLAUDE.md e regras do agente de desenvolvimento

- [x] Criar `CLAUDE.md`
- [x] Documentar arquitetura
- [x] Documentar estrutura do projeto
- [x] Definir convenções de código
- [x] Definir regras de testes
- [x] Definir regras para alterações arquiteturais
- [x] Definir regras para criação de Skills
- [x] Definir regras para criação de Events
- [x] Definir regras para documentação
- [x] Definir workflow de desenvolvimento com Claude Code

**Commit esperado:**

```text
docs: establish Claude Code development guidelines
```

---

## 0.5 — Documentação arquitetural

Criar:

```text
docs/
├── architecture.md
├── event-system.md
├── context-system.md
├── memory-system.md
├── agent-runtime.md
├── skills.md
├── mcp.md
└── security.md
```

- [x] Criar documentação principal
- [x] Documentar arquitetura de alto nível
- [x] Documentar responsabilidades dos componentes
- [x] Documentar fluxo de dados
- [x] Documentar decisões arquiteturais iniciais
- [x] Criar estrutura para Architecture Decision Records

**Commit esperado:**

```text
docs: establish architectural documentation
```

---

## 0.6 — Testes, CI e Definition of Done

- [x] Definir estrutura de testes
- [x] Criar testes básicos
- [x] Configurar CI
- [x] Executar lint automaticamente
- [x] Executar type checking automaticamente
- [x] Executar testes automaticamente
- [x] Definir Definition of Done
- [x] Definir critérios de qualidade

**Commit esperado:**

```text
test: establish project quality gates
```

---

## 0.7 — Foundation Review

- [x] Auditar estrutura do projeto
- [x] Auditar dependências
- [x] Auditar arquitetura
- [x] Auditar documentação
- [x] Auditar testes
- [x] Verificar reprodutibilidade do ambiente
- [x] Corrigir problemas encontrados
- [x] Confirmar Foundation como estável

**Commit esperado:**

```text
chore: complete foundation milestone
```

### Foundation completa

- [x] **FASE 0 CONCLUÍDA**

---

# FASE 1 — EVENT SYSTEM

**Objetivo:** criar o sistema nervoso do Jarvis: transformar acontecimentos em eventos estruturados e processáveis.

**Período:** Semanas 2–3

## 1.1 — Event Domain

- [x] Definir entidade `Event`
- [x] Definir identificador de evento
- [x] Definir timestamp
- [x] Definir source
- [x] Definir event type
- [x] Definir payload
- [x] Definir correlation ID
- [x] Definir causation ID
- [x] Definir schema version
- [x] Definir regras de imutabilidade

**Commit esperado:**

```text
feat: implement event domain
```

---

## 1.2 — Event Bus

- [x] Definir interface do Event Bus
- [x] Implementar `publish`
- [x] Implementar `subscribe`
- [x] Implementar consumo
- [x] Implementar acknowledgement
- [x] Implementar retry
- [x] Implementar tratamento de falhas
- [x] Criar testes

**Commit esperado:**

```text
feat: implement event bus
```

---

## 1.3 — Event Store

- [x] Definir armazenamento persistente
- [x] Criar schema de eventos
- [x] Implementar persistência
- [x] Implementar consulta por tipo
- [x] Implementar consulta temporal
- [x] Implementar consulta por correlation ID
- [x] Criar testes

**Commit esperado:**

```text
feat: implement persistent event store
```

---

## 1.4 — Event Consumers

- [x] Criar abstração `EventConsumer`
- [x] Implementar consumer básico
- [x] Implementar processamento assíncrono quando necessário — avaliado e
      **não** necessário nesta fase (nenhum consumer é I/O-bound); o bus é
      síncrono por decisão registrada em
      [ADR-0008](docs/adr/0008-synchronous-in-process-event-bus.md)
- [x] Implementar retry
- [x] Implementar dead-letter/error handling
- [x] Criar testes

**Commit esperado:**

```text
feat: implement event consumers
```

---

## 1.5 — Event System Integration

- [x] Integrar Event Domain
- [x] Integrar Event Bus
- [x] Integrar Event Store
- [x] Integrar Consumers
- [x] Criar fluxo completo
- [x] Testar eventos end-to-end

**Commit esperado:**

```text
feat: complete event-driven core
```

### Event System completo

- [x] **FASE 1 CONCLUÍDA**

---

# FASE 2 — CONTEXT ENGINE

**Objetivo:** transformar eventos e dados ambientais em uma representação estruturada do estado atual do usuário e do sistema.

**Período:** Semanas 4–5

## 2.1 — Context Domain

- [x] Definir `CurrentContext`
- [x] Definir `UserContext`
- [x] Definir `EnvironmentContext`
- [x] Definir `DeviceContext`
- [x] Definir `ActivityContext`
- [x] Definir `ScheduleContext`
- [x] Definir `ConversationContext`
- [x] Definir `TaskContext`
- [x] Definir timestamps e validade dos dados

**Commit esperado:**

```text
feat: implement context domain
```

---

## 2.2 — Context Providers

- [x] Criar interface `ContextProvider`
- [x] Criar Time Provider
- [x] Criar Device Provider
- [x] Criar Activity Provider — entregue como **port + double de teste**, não como
      adapter em `src/`: nada de atividade é observável com segurança sem
      introspecção do sistema operacional, que é escopo da subfase 8.1
- [x] Criar Calendar Provider — idem; uma agenda real exigiria OAuth e integração
      externa, proibidos nesta fase (`PHASE-2.md §5`), e um adapter de valor
      declarado pareceria funcionalidade pronta sem ser
- [x] Criar Location Provider — idem; sem rastreamento real, permissão ou serviço
      externo. Ver [context-system.md](docs/context-system.md#providers)
- [x] Criar mocks para testes

**Commit esperado:**

```text
feat: implement context providers
```

---

## 2.3 — Context Aggregation

- [x] Criar Context Aggregator
- [x] Coletar dados dos providers
- [x] Resolver conflitos
- [x] Controlar validade dos dados
- [x] Implementar timestamps
- [x] Criar `get_current_context`
- [x] Criar testes

**Commit esperado:**

```text
feat: implement context aggregation
```

---

## 2.4 — Context Snapshots

- [x] Definir snapshot
- [x] Persistir snapshots relevantes
- [x] Implementar consulta histórica
- [x] Implementar expiração
- [x] Criar testes

**Commit esperado:**

```text
feat: implement context snapshots
```

---

## 2.5 — Context Integration

- [x] Integrar Event System
- [x] Integrar Context Engine
- [x] Atualizar contexto a partir de eventos
- [x] Validar consistência
- [x] Testar fluxo completo

**Commit esperado:**

```text
feat: complete context engine
```

### Context Engine completo

- [x] **FASE 2 CONCLUÍDA**

---

# FASE 3 — MEMORY SYSTEM

**Objetivo:** criar memória persistente, recuperável, contextual e com ciclo de vida.

**Período:** Semanas 6–7

## 3.1 — Memory Domain

- [x] Definir `Memory`
- [x] Definir memória episódica
- [x] Definir memória semântica
- [x] Definir memória de preferências
- [x] Definir memória procedural
- [x] Definir working memory
- [x] Definir task memory
- [x] Definir metadados
- [x] Definir confidence
- [x] Definir importance
- [x] Definir timestamps
- [x] Definir expiration — derivada de `valid_until` (`Memory.is_valid_at`), nunca
      uma coluna separada; nada é apagado quando expira, só deixa de ser vigente

**Commit esperado:**

```text
feat: implement memory domain
```

---

## 3.2 — Persistent Memory Storage

- [x] Definir banco de dados — **SQLite**, não PostgreSQL, decisão registrada em
      [ADR-0009](docs/adr/0009-sqlite-memory-storage.md) com a medição que a
      justifica (varredura de cosseno em Python puro: ~109 ms para 10 mil
      memórias). Diverge do roadmap original; ver `docs/phase-3-plan.md §29`
- [x] Configurar PostgreSQL — **não realizado**, substituído pela decisão acima
- [x] Configurar pgvector — **não realizado**; busca vetorial exata por varredura
      no Core, sobre candidatos pré-filtrados por SQL, sem índice aproximado
- [x] Criar schema
- [x] Criar migrations — `PRAGMA user_version = 1`, sem ferramenta de migração,
      mesmo critério das Fases 1 e 2 (nenhum histórico de schema a migrar ainda)
- [x] Implementar repository
- [x] Criar testes

**Commit esperado:**

```text
feat: implement persistent memory storage
```

---

## 3.3 — Memory Retrieval

- [x] Implementar busca semântica
- [x] Implementar busca temporal
- [x] Implementar busca por entidades
- [x] Implementar filtros
- [x] Implementar ranking inicial
- [x] Criar testes

**Commit esperado:**

```text
feat: implement memory retrieval
```

---

## 3.4 — Memory Scoring

- [x] Definir relevância
- [x] Definir recência
- [x] Definir importância
- [x] Definir confidence
- [x] Definir relevância temporal
- [x] Implementar scoring combinado
- [x] Testar ranking

**Commit esperado:**

```text
feat: implement memory scoring
```

---

## 3.5 — Memory Consolidation

- [x] Definir consolidação
- [x] Detectar padrões — **contagem determinística**, não inferência: ≥3
      ocorrências episódicas ativas do mesmo `(subject, fingerprint)`, vindas de
      ≥2 `provenance.reference` distintos. `PHASE-3.md §17/§24` proíbem LLM no
      Memory System; detecção por similaridade semântica de padrão é Fase 4
- [x] Criar memórias semânticas
- [x] Relacionar memórias — `derived_from`/`superseded_by`
- [x] Controlar confidence
- [x] Evitar duplicações
- [x] Criar testes

**Commit esperado:**

```text
feat: implement memory consolidation
```

---

## 3.6 — Memory Lifecycle

- [x] Implementar reinforcement — curva assintótica (`c ← c + (cap − c)·α`),
      nunca alcança 1.0
- [x] Implementar decay — calculado em tempo de retrieval (`ranking.py`), nunca
      persistido; meia-vida por tipo, ancorada em `updated_at`
- [x] Implementar expiration
- [x] Implementar forget — invalidação lógica, preserva evidência
- [x] Implementar delete — `purge`, remoção física e irreversível, só por pedido
      explícito ([ADR-0010](docs/adr/0010-immutable-memory-and-supersession.md));
      assimetria deliberada em relação a `events`/`context_snapshots`
- [x] Implementar atualização — só estado de ciclo de vida; conteúdo é imutável,
      correção/contradição cria memória nova que supersede a anterior
- [x] Registrar origem das memórias
- [x] Criar testes

**Commit esperado:**

```text
feat: implement memory lifecycle
```

---

## 3.7 — Memory Integration

- [x] Integrar Event System — **direção única: entrada.** Contracts §3.3 não
      lista o Event System entre as dependências permitidas do Memory Core (ao
      contrário da §3.2 para o Context Engine); o Memory System não emite
      eventos nesta fase. Ver `docs/phase-3-plan.md §29`
- [x] Integrar Context Engine — `context_to_query`, restrito aos campos de
      estado do usuário (`place`/`activity`/`availability`)
- [x] Criar fluxo evento → memória — `user.stated_preference`, `user.noted_fact`
- [x] Criar fluxo contexto → memória relevante
- [x] Testar recuperação contextual

**Commit esperado:**

```text
feat: complete persistent memory system
```

### Memory System completo

- [x] **FASE 3 CONCLUÍDA**

---

# FASE 4 — AGENT RUNTIME

**Objetivo:** introduzir o LLM como mecanismo de raciocínio dentro da arquitetura.

**Período:** Semanas 8–9

## 4.1 — LLM Provider

- [x] Criar interface `LLMProvider`
- [x] Criar abstração de mensagens
- [x] Criar abstração de respostas
- [x] Implementar provider inicial
- [x] Configurar credenciais
- [x] Implementar tratamento de erros
- [x] Criar testes

**Commit esperado:**

```text
feat: implement llm provider abstraction
```

---

## 4.2 — Agent Runtime

- [x] Criar `AgentRuntime`
- [x] Definir entradas — `UserMessage` (conversa) e `EventTrigger` (proativo)
- [x] Definir saídas — `AgentTurn`, contendo a `Decision` e o rastro do turno
- [x] Integrar contexto — leitura apenas; quem reconstrói a projeção é o
      composition root, não o agente
- [x] Integrar memória — retrieval apenas. `record_access`/`reinforce` ficam
      para a fase em que a decisão vira ação (`docs/phase-3-plan.md §12.4`)
- [x] Integrar eventos — **direção única: entrada.** O agente consome
      `RecordedEvent` como gatilho e **não** emite eventos; registrar decisões
      de forma consultável é a subfase 7.4. Mesmo critério da 3.7
- [x] Integrar LLM

**Commit esperado:**

```text
feat: implement agent runtime
```

---

## 4.3 — Structured Decisions

- [x] Definir schema de decisão
- [x] Implementar `ignore`
- [x] Implementar `remember`
- [x] Implementar `notify` — é também o tipo de uma **resposta de conversa**;
      o que distingue um alerta de uma réplica é o gatilho, não o tipo
- [x] Implementar `ask`
- [x] Implementar `act`
- [x] Implementar `act_and_notify`
- [x] Implementar validação

> "Implementar" aqui é a **variante validada + o parsing**, não a execução:
> `act` volta como proposta inerte (não há Policy Engine nem Skills até a
> Fase 5), `remember` não grava e `notify`/`ask` não entregam nada (o
> Notification System é a 7.3). Ver `docs/phase-4-plan.md §3` (V-3).
>
> Depois desta subfase: `act` virou execução real na Fase 5 (ADR-0016) e
> `remember` passou a gravar, aplicado pelo composition root (ADR-0018).
> `notify`/`ask` seguem sem entrega até a 7.3.

**Commit esperado:**

```text
feat: implement structured agent decisions
```

---

## 4.4 — Importance Engine

- [x] Definir importance — combinação ponderada das quatro grandezas abaixo
- [x] Definir urgency
- [x] Definir personal relevance — reúsa o `RelevanceScore` da Fase 3
- [x] Definir temporal relevance
- [x] Definir interruption cost — entra **subtraindo**
- [x] Implementar avaliação — **determinística, sem chamada de LLM**
      (`PHASE-4.md §14`): um filtro que chama o modelo não filtra chamadas ao
      modelo. Não há "AI importance model" separado
- [x] Criar testes

**Commit esperado:**

```text
feat: implement importance engine
```

---

## 4.5 — Prompt Assembly

- [x] Criar `PromptBuilder`
- [x] Definir system instructions
- [x] Integrar contexto
- [x] Integrar memória
- [x] Integrar evento
- [x] Integrar capacidades
- [x] Integrar conversa
- [x] Controlar tamanho do contexto
- [x] Criar testes

**Commit esperado:**

```text
feat: implement prompt assembly
```

---

## 4.6 — Agent Loop

Implementar:

```text
observe
→ contextualize
→ retrieve
→ reason
→ decide
→ execute
→ observe result
```

- [x] Implementar ciclo — até `decide`. **`execute` e `observe result` não
      existem nesta fase**: quem executa é Policy → Skill → Tool Router → MCP
      (ADR-0003), e nada disso tem código antes da Fase 5. O ciclo se fecha
      quando esses componentes existirem
- [x] Implementar state handling — `Conversation` imutável, em memória;
      persistir sessão é 6.4
- [x] Implementar erros — retry de transporte separado do reparo de conteúdo
- [x] Implementar timeout
- [x] Implementar logging
- [x] Criar testes end-to-end

**Commit esperado:**

```text
feat: implement agent event loop
```

---

## 4.7 — Agent Integration

- [x] Integrar Events — entrada apenas (ver 4.2); o agente **não** é inscrito
      no bus, porque isso tornaria todo `events emit` uma chamada paga. A
      subscrição pertence ao Trigger Engine (7.1)
- [x] Integrar Context
- [x] Integrar Memory
- [x] Integrar LLM — Gemini em nuvem, tier gratuito
      ([ADR-0011](docs/adr/0011-gemini-rest-llm-adapter.md)); `LLMProvider`
      segue vendor-agnóstico
- [x] Testar evento → contexto → memória → decisão

**Commit esperado:**

```text
feat: complete autonomous reasoning core
```

### Agent Runtime completo

- [x] **FASE 4 CONCLUÍDA**

---

# FASE 5 — SKILLS + MCP

**Objetivo:** permitir que o agente execute ações de forma estruturada e controlada.

**Período:** Semanas 10–11

## 5.1 — Skill Framework

- [x] Criar `Skill`
- [x] Definir capabilities
- [x] Definir permissions
- [x] Definir risk level
- [x] Definir confirmation policy
- [x] Definir execução
- [x] Criar testes

**Commit esperado:**

```text
feat: implement skill framework
```

---

## 5.2 — Skill Registry

- [x] Implementar registro
- [x] Implementar descoberta
- [x] Implementar consulta
- [x] Implementar listagem
- [x] Implementar capabilities
- [x] Criar testes

**Commit esperado:**

```text
feat: implement skill registry
```

---

## 5.3 — Tool Abstraction

- [x] Criar `Tool`
- [x] Criar `ToolResult`
- [x] Criar `ToolError`
- [x] Definir input schema
- [x] Definir output schema
- [x] Definir risk metadata
- [x] Criar testes

**Commit esperado:**

```text
feat: implement tool abstraction
```

---

## 5.4 — MCP Client

- [x] Implementar conexão MCP
- [x] Implementar descoberta de ferramentas
- [x] Validar schemas
- [x] Implementar chamadas
- [x] Implementar erros
- [x] Implementar timeout
- [x] Implementar reconexão
- [x] Criar testes

**Commit esperado:**

```text
feat: implement MCP client
```

---

## 5.5 — Tool Router

Implementar:

```text
Skill
 ↓
Tool Router
 ↓
MCP
 ↓
External Tool
```

- [x] Implementar roteamento
- [x] Validar permissões
- [x] Validar schemas
- [x] Registrar execução
- [x] Tratar erros

**Commit esperado:**

```text
feat: implement tool router
```

---

## 5.6 — System + File Skills

- [x] Criar System Skill
- [x] Criar File Skill
- [x] Definir permissões
- [x] Implementar operações seguras
- [x] Implementar confirmação
- [x] Criar testes

**Commit esperado:**

```text
feat: implement system and file skills
```

---

## 5.7 — Calendar Skill

> Fora de escopo nesta fase: requer OAuth e integração externa; `PHASE-5.md` §43
> a exclui expressamente. A integração futura é suportada por um MCP Server
> registrado, sem alterar o Core.

**Commit esperado:**

```text
feat: implement calendar skill
```
---

## 5.8 — Email Skill

> Fora de escopo nesta fase: requer OAuth e integração externa; `PHASE-5.md` §43
> a exclui expressamente. A integração futura é suportada por um MCP Server
> registrado, sem alterar o Core.

**Commit esperado:**

```text
feat: implement email skill
```
---

## 5.9 — Confirmation System

- [x] Definir níveis de risco
- [x] Definir ações automáticas
- [x] Definir ações que exigem confirmação
- [x] Criar confirmation manager
- [x] Registrar decisões
- [x] Criar testes

**Commit esperado:**

```text
feat: implement confirmation system
```

---

## 5.10 — Skills + MCP Integration

- [x] Integrar Agent Runtime
- [x] Integrar Skill Registry
- [x] Integrar Tool Router
- [x] Integrar MCP
- [x] Testar agente executando uma ação real
- [x] Validar permissões

**Commit esperado:**

```text
feat: complete skill and MCP architecture
```

### Skills + MCP completos

- [x] **FASE 5 CONCLUÍDA**

---

# FASE 6 — VOICE

**Objetivo:** criar interface conversacional por voz com wake word.

**Período:** Semana 12

## 6.1 — Wake Word

- [x] Criar `WakeWordDetector` — port **push**: o loop lê o microfone e alimenta
      o detector, para que o mesmo stream sirva wake word, captura e barge-in
- [x] Definir interface
- [x] Integrar detector — **dois** adapters, ambos sem IA local
      ([ADR-0021](docs/adr/0021-wake-word-without-local-ai.md)):
      `PushToTalkWakeWord` (default; nenhum áudio sai do dispositivo antes de o
      usuário pedir) e `TranscriptionWakeWord` (VAD determinístico → transcrição
      curta → casamento de frase, com orçamento por minuto). Porcupine e
      openWakeWord ficaram fora por serem inferência local, proibida na fase
- [x] Criar testes

**Commit esperado:**

```text
feat: implement wake word interface
```

---

## 6.2 — Speech-to-Text

- [x] Criar `SpeechToText`
- [x] Integrar modelo/provider — Groq (`whisper-large-v3-turbo`) por REST da
      stdlib, sem SDK de vendor
      ([ADR-0022](docs/adr/0022-cloud-speech-over-stdlib-rest.md))
- [x] Implementar captura — ports `AudioSource`/`AudioSink` + adapter
      `sounddevice` em **extra opcional**
      ([ADR-0020](docs/adr/0020-audio-io-ports-and-optional-backend.md)); a suíte
      padrão continua sem áudio, sem rede e sem a dependência
- [x] Implementar transcrição
- [x] Tratar erros — taxonomia própria (`Stt*`), retry respeitando `Retry-After`
- [x] Criar testes

**Commit esperado:**

```text
feat: implement speech-to-text pipeline
```

---

## 6.3 — Text-to-Speech

- [x] Criar `TextToSpeech` — port separado de `SpeechToText`, pelo mesmo critério
      do ADR-0002: dois papéis com ciclos de troca independentes
- [x] Integrar provider — Google Cloud TTS por REST da stdlib, credencial no
      header `x-goog-api-key`, nunca na query string
- [x] Implementar geração — `LINEAR16` (não MP3): evita um decoder e, com ele,
      uma dependência
- [x] Implementar reprodução — o sink abre o stream **na taxa do clip**, o que
      evita reamostrar os 24 kHz da síntese para os 16 kHz da captura
- [x] Criar testes

**Commit esperado:**

```text
feat: implement text-to-speech pipeline
```

---

## 6.4 — Voice Sessions

- [x] Criar `VoiceSession` — imutável, como `Conversation`; persistida em
      `data/voice.db` (quinto banco) como **estado operacional apagável**, nunca
      como evento ([ADR-0025](docs/adr/0025-voice-transcripts-as-operational-state.md)).
      Áudio não é gravado em lugar nenhum; retenção default de 7 dias
- [x] Definir session ID — é também o `correlation_id`, então
      `events list --correlation-id` mostra a conversa inteira
- [x] Integrar conversa — o composition root traduz `VoiceSession` em
      `Conversation` para o prompt; uma história só, em dois formatos
- [x] Controlar timeout — janela de follow-up (dispensa a wake word entre
      turnos), timeout de ociosidade e teto de turnos
- [x] Controlar estado — sete estados, e toda transição é observável pelo painel
- [x] Criar testes

**Commit esperado:**

```text
feat: implement voice sessions
```

---

## 6.5 — Interruption

- [x] Detectar nova fala — limiar próprio, mais alto que o do VAD: sem fone, o
      alto-falante alimenta o microfone
- [x] Interromper TTS — `AudioSink.play` consulta `cancelled()` **entre blocos**;
      o clip restante é descartado, nunca retomado
- [x] Processar novo comando — o áudio capturado durante a interrupção vira o
      começo do próximo enunciado, em vez de obrigar a repetir
- [x] Controlar concorrência — **sem thread, sem lock, sem fila**: é a função de
      cancelamento que lê o microfone. O detector por transcrição fica suspenso
      enquanto o Jarvis fala, senão ele se acorda com a própria voz
- [x] Criar testes

**Commit esperado:**

```text
feat: implement voice interruption
```

---

## 6.6 — Voice Integration

- [x] Integrar wake word
- [x] Integrar STT
- [x] Integrar Agent — por um **port próprio** (`ConversationalAgent`), não por
      import. `jarvis.voice` não conhece `jarvis.agent`, e é isso que torna o
      loop inteiro testável sem LLM, sem banco e sem hardware
- [x] Integrar TTS
- [x] Testar conversa completa

**Commit esperado:**

```text
feat: complete conversational voice interface
```

---

## 6.7 — Observability Panel

> Subfase **acrescentada na Fase 6**. O `PHASE_6_EXECUTION_CONTEXT.md` da fase
> exige um painel de observabilidade ("Isso é obrigatório") que este roadmap não
> previa. Os dois são conciliáveis: o painel é uma *Interface* no sentido de
> Ports & Adapters — um ponto de entrada que **lê** o Core —, não uma capacidade
> nova, e por isso não antecipa a Fase 7. Mesmo precedente de anotar em vez de
> resolver em silêncio usado nas subfases 2.2, 3.2 e 5.7/5.8.

- [x] Criar view models (`PanelSnapshot` e os sete blocos)
- [x] Criar `ObservabilityService` sobre funções de leitura injetadas
- [x] Servir localmente (`http.server`, loopback, SSE com fallback)
- [x] **Somente leitura** — nenhuma rota inicia ação
      ([ADR-0024](docs/adr/0024-observability-panel-as-snapshot-reader.md))
- [x] Notificações — **toast do painel e nada além**. Nenhum port
      `Notification`, nenhum canal de desktop, nenhuma prioridade: isso é a
      subfase 7.3, e implementá-la aqui adiantaria fase. O toast é renderização
      de eventos que já existem no Event Store
- [x] Criar testes

**Commit esperado:**

```text
feat: implement observability panel
```

---

## 6.8 — Voice + Panel Integration

- [x] Um processo residente (`jarvis run`)
      ([ADR-0023](docs/adr/0023-single-resident-process.md))
- [x] Estado ao vivo entre as threads (`LiveState`), com uma **única** thread
      tocando SQLite
- [x] Duas cadências: status a cada transição, snapshot completo por intervalo
- [x] Eventos de sessão alimentando o campo `conversation` do Context Engine —
      que existia desde a Fase 2 sem fonte
- [x] Criar testes

**Commit esperado:**

```text
feat: serve voice and panel from one process
```

### Voice completo

- [x] **FASE 6 CONCLUÍDA**

---

# FASE 7 — PROACTIVITY + AUTONOMY

**Objetivo:** permitir que o agente avalie eventos autonomamente e decida quando agir ou interromper o usuário.

**Período:** Semanas 13–14

## 7.1 — Trigger Engine

- [x] Criar trigger engine
- [x] Integrar eventos
- [x] Definir condições
- [x] Definir triggers
- [x] Criar testes

**Commit esperado:**

```text
feat: implement event trigger engine
```

---

## 7.2 — Interruption Policy

- [x] Considerar importância
- [x] Considerar atividade do usuário — reaproveitado de `ImportanceAssessment.interruption_cost` (Fase 4), não recalculado
- [x] Considerar foco — idem; `focus` já pesa em `interruption_cost`
- [x] Considerar horário — janela de silêncio configurável, hora local derivada de `utc_offset`
- [x] Considerar localização — Location Provider não existe (decisão da 2.2); considerada e registrada como neutra, nunca inventada
- [x] Considerar conversa atual — `ConversationContext.active_id` fresco suprime
- [x] Considerar notificações recentes — cooldown por assunto, histórico injetado por quem chama
- [x] Criar política de interrupção
- [x] Criar testes

**Commit esperado:**

```text
feat: implement interruption policy
```

---

## 7.3 — Notification Manager

- [x] Criar Notification Manager
- [x] Implementar desktop notification — canal console/log estruturado nesta fase, não um toast nativo do SO; decisão registrada em ADR-0028
- [x] Implementar voice notification — via `TextToSpeech`/`AudioSink` já existentes (Fase 6), só fala quando `can_speak_now()`
- [x] Implementar silent mode — suprime tudo abaixo de `URGENT`
- [x] Implementar prioridade — `NotificationPriority` (`low`/`normal`/`high`/`urgent`)
- [x] Criar testes

**Commit esperado:**

```text
feat: implement notification manager
```

---

## 7.4 — Decision Logging

- [x] Registrar decisões — `agent.decision_recorded`, publicado pelo composition root após cada turno (`agent ask`/`chat`/`react`, voz)
- [x] Registrar contexto utilizado — `context_as_of` (o `as_of` da projeção lida naquele turno); não o contexto inteiro, ver ADR-0026
- [x] Registrar memória utilizada — `used_memory_ids` (identidade, nunca conteúdo)
- [x] Registrar razão — `reason`/`message`
- [x] Registrar ações — via `correlation_id` compartilhado com a auditoria da Fase 5, sem duplicar a trilha
- [x] Permitir consulta posterior — `jarvis decisions list [--correlation-id]`; painel (`DecisionCard`) passa a ler histórico persistido, não só o turno em curso
- [x] Criar testes

**Commit esperado:**

```text
feat: implement agent decision logging
```

---

## 7.5 — Background Task Manager

- [x] Criar Task Manager
- [x] Criar estados de tarefa — `pending`/`running`/`retrying`/`succeeded`/`failed`/`cancelled`
- [x] Executar tarefas em background — aciona `ActionExecutor` (ADR-0016), nunca reimplementa a cadeia
- [x] Implementar retry — backoff exponencial configurável, até `max_attempts`
- [x] Implementar cancelamento — só de tarefas não terminais
- [x] Implementar falhas — negação de política/confirmação pendente falha direto (não é transitório); falha de execução tenta de novo até o teto
- [x] Criar testes

Concorrência: nenhuma thread/timer novo — `run_due` é ticado de pontos que já
existem (`jarvis tasks run-due`, início de `jarvis run`, cada ciclo do
painel), ver ADR-0027. O wiring desses pontos de tick no composition root é
da subfase 7.7 ("Integrar tasks").

**Commit esperado:**

```text
feat: implement background task manager
```

---

## 7.6 — Conditional Triggers

Permitir:

```text
quando X acontecer
e Y for verdadeiro
faça Z
```

- [x] Criar condições — seis operadores fechados (`always`/`context_equals`/`context_present`/`payload_equals`/`and`/`or`/`not`), sem `eval`
- [x] Integrar contexto — `context_equals`/`context_present` sobre `CurrentContext`, respeitando frescor
- [ ] Integrar memória — fora do escopo desta subfase: nenhum operador de condição chegou a consultar memória, porque nenhuma regra concreta desta fase precisa disso, e um operador sem caso de uso real seria a abstração especulativa que `architecture-contracts.md §1` proíbe. `docs/phase-7-plan.md §7.6` (aprovado) já não previa este operador. `payload_equals`/`context_equals` cobrem os casos concretos de automação hoje; um `memory_present`/`memory_equals` entra atrás do mesmo `ConditionOp` fechado quando houver uma regra real que precise dele
- [x] Integrar eventos — `ConditionalTriggerConsumer` (`EventConsumer`), mesmo padrão do Trigger Engine (7.1)
- [x] Executar ações — produz `ActionRequest(actor=Actor.SYSTEM, ...)`; **sem LLM nesta trilha** — quem executa continua sendo `ActionExecutor` (ADR-0016), acionado pelo composition root via callback
- [x] Criar testes

**Commit esperado:**

```text
feat: implement conditional triggers
```

---

## 7.7 — Proactivity Integration

- [x] Integrar triggers — `TriggerEventConsumer`/`ConditionalTriggerConsumer` inscritos num `EventBus` compartilhado por `jarvis run` (`_build_proactivity`), só quando `JARVIS_PROACTIVITY_ENABLED` e há allowlist/regra configurada
- [x] Integrar policy — todo caminho proativo (raciocínio e condicional) chega a `ActionExecutor.submit`, que já passa por `PolicyEngine`; nenhum atalho novo
- [x] Integrar notifications — `NotificationManager` entrega o `message` de uma decisão proativa; canal de voz reconstruído em `_serve_voice` com o `TextToSpeech`/`AudioSink` reais, console sempre como fallback
- [x] Integrar memory — o caminho de raciocínio (7.1) chama `AgentRuntime.handle` como `agent react` já fazia: retrieval automático, e a proposta de memória da decisão é persistida (`_persist_memory_proposal`, mesma proveniência de evento que `agent react`)
- [x] Integrar tasks — `TaskManager.run_due` ticado no início de `_run_resident` e a cada `PanelBridge.refresh()`, sobre um `ActionExecutor` construído uma única vez por sessão (ADR-0027); `jarvis tasks list|show|cancel|run-due`
- [x] Testar comportamento proativo completo — `tests/test_proactivity_integration.py` (evento → Trigger Engine → Agent Runtime com LLM substituído → Decision Log → Notification → Action Executor, e o caminho paralelo Conditional Trigger → Action Executor sem LLM) + `tests/test_cli_proactivity.py` (wiring do composition root, `proactivity_enabled=False` idêntico ao pré-Fase-7)

Autonomia real é opt-in em três interruptores independentes
(`JARVIS_PROACTIVITY_ENABLED`, allowlist de triggers/regras não vazia,
`JARVIS_PROACTIVITY_EXECUTE_ACTIONS`) — ver ADR-0029. Sem eles, `jarvis run`
se comporta exatamente como antes da Fase 7.

**Commit esperado:**

```text
feat: enable proactive agent behavior
```

### Proactivity completa

- [x] **FASE 7 CONCLUÍDA**

---

# FASE 8 — INTEGRATION + HARDENING

**Objetivo:** integrar o sistema com o computador e torná-lo confiável, seguro e avaliável.

**Período:** Semanas 15–16

## 8.1 — Computer Context

- [x] Detectar aplicação ativa
- [x] Detectar janela ativa
- [x] Detectar CPU
- [x] Detectar RAM
- [x] Detectar GPU (melhor esforço via `Get-Counter`; ausência é campo ausente, nunca inventado)
- [x] Detectar rede
- [x] Detectar tempo de inatividade
- [x] Detectar processos relevantes
- [x] Integrar ao Context Engine

**Commit esperado:**

```text
feat: implement computer context providers
```

---

## 8.2 — Computer Skill

- [x] Abrir aplicação (`computer.open_app`, só a partir de uma allowlist — ver ADR-0031)
- [x] Fechar aplicação (`computer.close_app`)
- [x] Focar janela (`computer.focus_window`)
- [x] Interagir com interface (escopo restrito a foco/listagem de janela, não automação de mouse/teclado — decisão de escopo documentada em `docs/phase-8-plan.md`)
- [x] Ler tela quando apropriado (escopo restrito à identidade da janela ativa, já entregue por 8.1, não captura de pixels/OCR)
- [x] Executar comandos seguros (`computer.run_command`, allowlist de argv — ADR-0031)
- [x] Implementar permissões (capacidades `computer:read/open/close/run`, negadas por padrão — testado em 8.3)
- [x] Implementar confirmação (`ConfirmationRequirement` declarado por Skill — testado em 8.3)
- [x] Criar testes

**Commit esperado:**

```text
feat: implement computer skill
```

---

## 8.3 — Permission System

- [x] Definir permission model (já existe desde a Fase 5 — `jarvis/policy/`)
- [x] Definir níveis de risco (já existe desde a Fase 5 — `RiskLevel`)
- [x] Definir capabilities (`computer:read/open/close/run`, Fase 8.2)
- [x] Implementar allowlist (`policy_granted_capabilities`, já existe — vazio nega as quatro por padrão)
- [x] Implementar denylist (já existe desde a Fase 5 — `policy_denied_skills`/`policy_denied_effects`)
- [x] Integrar Skills (provado contra o Policy Engine real em `tests/test_computer_permission_integration.py`)
- [x] Integrar MCP (nenhuma mudança necessária — MCP já passa pelo mesmo `PolicyEngine` desde a Fase 5)
- [x] Integrar Computer Skill

**Commit esperado:**

```text
feat: implement permission system
```

---

## 8.4 — Audit Logging

- [x] Registrar ações (já existe desde a Fase 5 — `jarvis/execution/adapters/event_audit.py`)
- [x] Registrar ferramentas (já existe desde a Fase 5 — trilha de `tool.execution_*`)
- [x] Registrar decisões (já existe desde a Fase 7.4 — `jarvis/decisions/`)
- [x] Registrar confirmações (já existe desde a Fase 5 — `action.confirmation_requested`)
- [x] Registrar falhas (já existe desde a Fase 5 — `tool.execution_failed`/`action.failed`)
- [x] Implementar consulta (`jarvis audit show <correlation_id>` — nova consulta unificada sobre o Event Store já existente, sem armazenamento novo)
- [x] Criar testes

**Commit esperado:**

```text
feat: implement audit logging
```

---

## 8.5 — Behavioral Evaluation

Criar cenários de avaliação:

- [x] Email importante durante período de foco
- [x] Email irrelevante
- [x] Reunião próxima
- [x] Solicitação para enviar email (adaptação fiel: nenhuma Skill de e-mail existe em nenhuma fase — o cenário fiel é o modelo propor uma Skill inexistente e o `ActionExecutor` negar, não fingir sucesso)
- [x] Falha de ferramenta
- [x] Memórias contraditórias
- [x] Mudança de preferência
- [x] Situação em que o agente deve permanecer em silêncio

**Commit esperado:**

```text
test: add agent behavioral evaluation suite
```

---

## 8.6 — Failure + Recovery

Testar:

- [x] LLM indisponível
- [x] Banco indisponível
- [x] MCP indisponível
- [x] Timeout
- [x] Evento duplicado
- [x] Evento fora de ordem
- [x] Contexto desatualizado
- [x] Tool failure
- [x] Processo reiniciado
- [x] Recuperação após crash

**Commit esperado:**

```text
test: add failure and recovery scenarios
```

---

## 8.7 — Performance

- [x] Medir latência (`parse_decision`, a única parte determinística e offline do turno do agente — ver nota abaixo)
- [x] Medir retrieval (`scripts/benchmark.py::benchmark_memory_retrieval`, mesmo método do ADR-0009)
- [x] Medir construção de contexto (`benchmark_context_construction`, `ContextAggregator.refresh`)
- [ ] Medir chamadas ao LLM (fora de escopo por desenho: exigiria rede/credencial real contra a regra de `uv run pytest` sem rede/quota — `pyproject.toml`'s marker `external`; a única parte do turno do agente que roda offline e é medida aqui é `parse_decision`)
- [x] Identificar gargalos (nenhum encontrado — números batem com a expectativa do ADR-0009 para a escala de um agente pessoal)
- [ ] Otimizar componentes críticos (nada a otimizar: nenhum gargalo foi encontrado — inventar otimização sem medição violaria `architecture-contracts.md §1`)
- [x] Criar benchmarks (`scripts/benchmark.py` + `tests/test_performance_benchmarks.py`)

**Commit esperado:**

```text
perf: optimize context and memory retrieval
```

---

## 8.8 — Runtime Hardening

- [x] Revisar concorrência (nada novo: Fase 8 é síncrona, mesmo modelo de processo único do ADR-0023)
- [x] Revisar tratamento de erros (providers/backend só capturam a exceção esperada; o resto propaga — mesmo contrato do resto do projeto)
- [x] Revisar timeouts (GPU via PowerShell com timeout fixo; `run_command` usa o timeout do Tool Router, não um valor próprio)
- [x] Revisar retries (`ComputerToolBackend` não implementa retry próprio; `Idempotency.UNSAFE` em open_app/close_app/run_command já impede o router de repetir)
- [x] Revisar logs (nenhum logger novo nos providers/backend/skills — o que loga já existe na camada de execução/router, que já redige o que não pode vazar)
- [x] Revisar dependências (`psutil` é a única nova, sem transitiva inesperada — ADR-0030)
- [x] Revisar limites de segurança (allowlist fechada para open_app/run_command — ADR-0031; achado real na revisão: ver "Corrigir problemas críticos")
- [x] Corrigir problemas críticos (`computer.close_app` podia encerrar o próprio processo do Jarvis se `application` batesse com `python`/`pythonw` — corrigido com exclusão por `pid`, testada em `TestDefaultTerminateNeverKillsItself`)

**Commit esperado:**

```text
refactor: harden agent runtime
```

---

## 8.9 — Documentation Review

- [x] Atualizar arquitetura (`architecture-contracts.md` §3.2/§3.6/§3.7/§15; `architecture.md` §1/§6/§10 — Fase 7 deixou de aparecer como "não implementado", que era uma lacuna pré-existente)
- [x] Atualizar Skills (`skills.md` — catálogo agora com nove Skills)
- [x] Atualizar MCP (`mcp.md` — `ComputerToolBackend` como mais um `ToolBackend`, ao lado do local e do MCP)
- [x] Atualizar memória (nada mudou em `memory/` na Fase 8 — sem alteração necessária em `memory-system.md`)
- [x] Atualizar contexto (`context-system.md` — oitavo subcontexto, três providers novos)
- [x] Atualizar setup (`README.md`, `.env.example` — variáveis e capacidades novas)
- [x] Atualizar troubleshooting (`docs/troubleshooting.md`, novo)
- [x] Atualizar roadmap (este arquivo, subfase a subfase)
- [x] Documentar decisões finais (`docs/computer.md`, novo; ADR-0030/0031)

**Commit esperado:**

```text
docs: complete system documentation
```

---

## 8.10 — Release Review

- [x] Executar todos os testes (281 passam; 4 falhas pré-existentes em `test_voice_vad.py`, causadas por um ajuste local não commitado em `vad.py`/`config.py` anterior a esta sessão, fora de escopo — ver nota abaixo)
- [x] Executar lint (`ruff check .` limpo)
- [x] Executar type checking (`mypy` limpo, 282 arquivos)
- [x] Validar instalação limpa (`uv sync` — resolve e instala `jarvis==0.1.0`)
- [x] Validar configuração (`jarvis info` mostra a política efetiva, incluindo as capacidades `computer:*` ausentes por padrão)
- [x] Validar segurança (`jarvis action run --skill computer.list_processes` nega com `capability_not_granted`, auditável via `jarvis audit show`)
- [x] Validar principais workflows (`jarvis action run`, `jarvis audit show`, `jarvis tools list`, `jarvis skills list` — testados manualmente contra dados reais)
- [x] Validar voz (achado real: `jarvis voice devices` vazava `ModuleNotFoundError` cru sem o extra `voice` — corrigido e testado, ver `TestDevicesWithoutAudioBackend`)
- [x] Validar memória (`jarvis memory list` funcional; suíte de memória passa)
- [x] Validar proatividade (`jarvis info` mostra `proactivity enabled=não` por padrão; suíte de proatividade passa)
- [x] Validar Skills (`jarvis skills list` mostra as nove, com risco/efeitos/capacidades corretos)
- [x] Validar MCP (`jarvis tools list` mostra os dois backends locais; ausência de `mcp.json` não produz erro)
- [x] Confirmar critérios de v0.1 (ver relatório final da fase)

**Commit esperado:**

```text
release: jarvis v0.1
```

### Release

- [x] **FASE 8 CONCLUÍDA**

---

# FASE 9 — DEEPENING REASONING + AUTONOMY

> Fase **acrescentada depois do lançamento v0.1**, fora das oito fases
> originais deste roadmap (linha 14) e das 16 semanas planejadas — mesmo
> precedente de anotar em vez de reescrever silenciosamente o histórico já
> usado nas subfases 2.2, 3.2, 5.7/5.8 e 6.7/6.8. Tema definido pelo usuário:
> aprofundar autonomia/raciocínio do Agent Runtime, não integrações externas
> nem empacotamento. Todo o escopo veio de lacunas já documentadas no próprio
> repositório como decisão consciente e adiada (Fases 4.6, 7.6), nunca
> esquecimento silencioso — ver `docs/architecture-contracts.md` e o
> levantamento desta sessão. Duas lacunas igualmente reais foram
> deliberadamente excluídas (aprendizado de pesos do Importance Engine,
> Calendar/Email Skills) — ver nota ao final da fase.

**Objetivo:** fechar o loop `observe result` que a subfase 4.6 deixou aberto
nos caminhos assíncronos, usar esse fechamento para permitir múltiplos passos
de raciocínio-e-ação em direção a um objetivo sem tornar `Decision` composta,
e permitir que Conditional Triggers consultem memória de longo prazo sem
violar a separação de componentes do Ports & Adapters.

## 9.1 — Action Outcome Feedback

- [x] Extrair `_result_summary`/`_reflect_on_outcome` de `_explain_outcome`
      (reaproveitado por tasks, proatividade e pelo caminho síncrono existente)
- [x] `TaskManager.run_due`/`_run_one` aceitam `on_outcome`, chamado só em
      estado terminal (nunca por tentativa que só agendou retry)
- [x] `_make_task_outcome_callback` fecha o loop no Background Task Manager
      (`jarvis tasks run-due` e o tick de `jarvis run`)
- [x] `on_match` (Trigger Engine) reflete sobre o desfecho de uma ação
      proativa não concluída, registra a segunda decisão e notifica
- [x] Criar testes (`tests/test_tasks_manager.py`,
      `tests/test_cli_proactivity.py`)

**Commit esperado:**

```text
feat: close action outcome feedback loop
```

---

## 9.2 — Goal Pursuit Loop

- [x] `Decision` permanece atômica — ADR-0003 intacto, cada passo passa pela
      Policy Engine individualmente
- [x] `jarvis agent pursue "<objetivo>" [--max-steps N]` — novo subcomando,
      não extensão de `ask`
- [x] `agent_pursue_max_steps` em `Settings` (`JARVIS_AGENT_PURSUE_MAX_STEPS`,
      default 6)
- [x] Cinco critérios de parada: decisão sem ação proposta; teto de passos;
      confirmação pendente (pausa, nunca auto-confirma); negação de política
      (não insiste); proposta idêntica à anterior (salvaguarda barata contra
      repetição)
- [x] Criar testes (`tests/test_cli_agent_pursue.py`)

**Commit esperado:**

```text
feat: implement goal pursuit loop
```

---

## 9.3 — Memory-Aware Conditional Triggers

- [x] Novo ADR documentando a extensão pontual Proactivity↔Memory (leitura,
      unidirecional, só via bridge adapter) — ADR-0032
- [x] Atualizar `architecture-contracts.md §3.17` (remove `jarvis.memory` da
      lista "proibido conhecer", documenta o bridge)
- [x] `proactivity/adapters/memory_bridge.py`, no molde de
      `memory/adapters/context_bridge.py`
- [x] `ConditionOp` ganha `memory_present`/`memory_equals`
- [x] `rules_config.py` aceita o novo operador
- [x] Criar testes (`tests/test_proactivity_conditions.py`,
      `tests/test_proactivity_rules_config.py`,
      `tests/test_proactivity_memory_bridge.py`,
      `tests/test_proactivity_architecture.py` atualizado)

**Commit esperado:**

```text
feat: add memory-aware conditional triggers
```

---

## 9.4 — Proactivity + Reasoning Integration

- [x] Wiring de 9.1/9.3 em `jarvis run`, sem thread nova — já entregue
      diretamente nas subfases 9.1 (`_make_task_outcome_callback` em
      `_tasks_run_due`/`tick_tasks`, `on_match` reflete e notifica) e 9.3
      (`MemoryPresenceBridge` em `_build_proactivity`), sem wiring adicional
      pendente
- [x] Decidido: `agent pursue` **fica só comando manual**. Nenhuma regra real
      hoje pede execução multi-passo disparada por evento sem supervisão
      direta, e um caminho proativo para ele seria a abstração especulativa
      que a regra 11 do roadmap proíbe — autonomia multi-passo sem
      supervisão é um salto de risco maior que o Trigger Engine (que só
      propõe **um** passo por evento), e não há justificativa concreta para
      dar esse salto agora. Revisitar quando houver caso de uso real.
- [x] Teste de regressão: `JARVIS_PROACTIVITY_ENABLED=false` idêntico ao
      pré-Fase-9 (`TestBuildProactivity`, inalterado desde a Fase 7 — ainda
      passa; `TestTasksRunDueClosesTheLoop` prova que 9.1 funciona com
      `Settings()` default, ou seja, independente do interruptor de
      proatividade, como o Background Task Manager já era desde a 7.5)
- [x] Teste end-to-end completo (`tests/test_cli_proactivity.py::
      TestTriggerCallbackClosesTheLoop` — evento → trigger → decisão → ação
      → resultado → segunda decisão → notificação, com `FakeChannel`;
      `tests/test_proactivity_integration.py::
      test_a_quiet_hours_memory_suppresses_a_conditional_trigger` — regra
      `not_(memory_present(...))` suprimindo uma Conditional Trigger)

**Commit esperado:**

```text
feat: integrate goal pursuit and memory-aware proactivity
```

---

## 9.5 — Documentation Review

- [x] Atualizar `docs/agent-runtime.md` (nova seção "Fechamento do loop e
      Goal Pursuit", correção de duas afirmações desatualizadas em
      "Limitações conhecidas"), `docs/proactivity.md` (memória em Conditional
      Triggers, `on_outcome`, Goal Pursuit como comando manual)
- [x] Atualizar `docs/architecture-contracts.md` §3.4 (não §3.15, que é
      Decision Log — corrigido durante a implementação: composition root
      pode reinvocar `AgentRuntime.handle` em sequência limitada); §3.17 já
      atualizado na 9.3
- [x] Atualizar `README.md` (`jarvis agent pursue`, memória em Conditional
      Triggers, status da Fase 9)
- [x] Atualizar este `ROADMAP.md` subfase a subfase (já feito nesta sessão,
      conforme cada uma concluiu)

**Commit esperado:**

```text
docs: document goal pursuit and memory-aware proactivity
```

---

### Fora de escopo (avaliado e excluído, não esquecido)

- **Aprendizado de pesos do Importance Engine**: a subfase 4.4 proibiu
  deliberadamente um "AI importance model"; o cooldown por assunto do
  `NotificationManager` (7.3) já cobre o atrito prático imediato.
- **Calendar/Email Skills (5.7/5.8), empacotamento/Docker**: fora do tema
  escolhido para esta fase.

### Fase 9 completa

- [x] **FASE 9 CONCLUÍDA**

---

# FASE 10 — DELIBERATION, MULTI-ACTION & CONTINUITY

> Fase acrescentada depois da Fase 9, mesmo precedente de anotar em vez de
> reescrever o histórico original (linha 14, e as próprias notas da Fase 9).
> Escopo definido pelo usuário após revisar o sistema em produção: raciocínio
> antes de agir, múltiplas ações por pedido, memória mais autônoma no fim de
> sessão — mais três lacunas levantadas nesta sessão (cegueira ao resultado
> de leitura, checkpoint/resume do Goal Pursuit Loop). Integrações externas
> ficam de fora (usuário longe de casa). Plano completo desta sessão, com
> pesquisa prévia de código citada arquivo:linha em cada subfase.

## 10.1 — Reasoning Field

- [x] `Decision.reasoning: str | None`, obrigatório em `act`/`act_and_notify`
      via `_REQUIRED`, nunca em `_FORBIDDEN`
- [x] `SYSTEM_INSTRUCTION`/schema Gemini pedem `reasoning` antes dos demais
      campos; `JARVIS_LLM_MAX_OUTPUT_TOKENS` 1024→1536
- [x] `parse_decision` extrai o campo
- [x] `cli._print_turn` imprime `raciocínio <texto>` quando presente
- [x] `DecisionRecord`/`decision_event` carregam `reasoning`, mesmo
      tratamento de privacidade que `message` já tem (nunca em log
      estruturado)
- [x] Testes (`test_agent_decision.py`, `test_agent_prompt.py`,
      `test_agent_privacy.py`, `test_agent_gemini.py`)

**Commit esperado:**

```text
feat: add reasoning field to agent decisions
```

---

## 10.2 — Multi-Action por Pedido

- [ ] `_run_agent_loop` extraído em `cli.py`, reaproveitado por `ask`/
      `chat`/`pursue` — refatoração pura, sem mudança de comportamento
- [ ] `--max-steps` em `agent ask` e `agent chat` (default 1)
- [ ] Testes de paridade (refatoração) + testes novos (multi-ação real)

**Commit esperado:**

```text
feat: allow multiple actions per user request in ask and chat
```

---

## 10.3 — Reflexão de Fim de Sessão

- [ ] `_reflect_on_session` — turno extra de `runtime.handle` com a
      `Conversation` completa, reaproveitando `_persist_memory_proposal`
- [ ] `agent_session_reflection_enabled: bool = True` em `config.py`
- [ ] Hook em `_agent_chat` (EOF do stdin) e em `_serve_voice`
      (`on_session(..., started=False)`)
- [ ] Testes

**Commit esperado:**

```text
feat: reflect and remember at session end
```

---

## 10.4 — Resultado de Leitura Deixa de Ser Cego

- [ ] `ReadFileHandler.summary` inclui prévia do conteúdo, capada
- [ ] Testes (skill + integração via `last_action_result`)

**Commit esperado:**

```text
feat: let read skills report content, not just byte counts
```

---

## 10.5 — Checkpoint/Resume do Goal Pursuit Loop

- [ ] Novo pacote `src/jarvis/pursuits/` (`model.py`/`ports.py`/
      `adapters/sqlite_pursuits.py`), mesmo molde de `jarvis/tasks/` —
      sétimo banco `data/pursuits.db`, estado operacional apagável (mesma
      cautela de privacidade do ADR-0014, não Event Store)
- [ ] `cli._agent_pursue` grava checkpoint a cada passo
- [ ] `--resume <pursuit_id>` retoma, com orientação adicional opcional
- [ ] Testes (repositório, checkpoint, resume completo)

**Commit esperado:**

```text
feat: add checkpoint and resume to the goal pursuit loop
```

---

## 10.6 — Documentação

- [ ] `docs/agent-runtime.md`, `README.md`
- [ ] Novo `docs/adr/0033-pursuit-state-as-operational-store.md`
- [ ] `docs/architecture-contracts.md` — entrada para `jarvis.pursuits`
- [ ] `ROADMAP.md` fechado subfase a subfase

**Commit esperado:**

```text
docs: document deliberation, multi-action and continuity
```

### Fase 10 completa

- [ ] **FASE 10 CONCLUÍDA**

---

# MARCOS PRINCIPAIS

## M0 — Foundation

**Semana 1**

```text
[x] Repositório
[x] Tooling
[x] Contratos
[x] CLAUDE.md
[x] Documentação
[x] CI
[x] Testes
```

---

## M1 — Event-Driven Core

**Semana 3**

```text
[x] Events
[x] Event Bus
[x] Event Store
[x] Consumers
```

O sistema consegue perceber acontecimentos estruturados.

---

## M2 — Context-Aware

**Semana 5**

```text
[x] Context
[x] Providers
[x] Aggregation
[x] Snapshots
```

O sistema consegue representar o estado atual.

---

## M3 — Persistent Memory

**Semana 7**

```text
[x] Memory
[x] PostgreSQL — SQLite, ver ADR-0009
[x] Vector search
[x] Retrieval
[x] Consolidation
[x] Lifecycle
```

O sistema consegue lembrar.

---

## M4 — Reasoning Agent

**Semana 9**

```text
[x] LLM — Gemini em nuvem, ver ADR-0011
[x] Agent Runtime
[x] Decisions
[x] Importance
[x] Prompt Assembly
[x] Agent Loop — até `decide`; `execute` depende da Fase 5
```

O sistema consegue raciocinar sobre acontecimentos.

---

## M5 — Actionable Agent

**Semana 11**

```text
[x] Skills
[x] Tools
[x] MCP
[x] Router
[x] Permissions
[x] Confirmation
```

O sistema consegue agir.

---

## M6 — Voice Agent

**Semana 12**

```text
[x] Wake Word — sem IA local, ver ADR-0021
[x] STT — Groq, ver ADR-0022
[x] Agent — por port próprio, sem import
[x] TTS — Google Cloud, ver ADR-0022
[x] Interruption
[x] Painel — subfases 6.7/6.8, acrescentadas na fase
```

O sistema consegue conversar.

---

## M7 — Proactive Agent

**Semana 14**

```text
[x] Triggers
[x] Policies
[x] Notifications
[x] Tasks
[x] Conditional Actions — sem LLM, ver ADR-0029
```

O sistema consegue decidir quando deve falar e agir.

---

## M8 — Jarvis v0.1

**Semana 16**

```text
[x] Computer Awareness
[x] Computer Skill
[x] Security
[x] Audit
[x] Evaluation
[x] Recovery
[x] Performance
[x] Documentation
```

---

## M9 — Deepening Reasoning + Autonomy

**Pós-v0.1 (adicionada fora do plano original de 16 semanas)**

```text
[x] Action Outcome Feedback
[x] Goal Pursuit Loop
[x] Memory-Aware Conditional Triggers
[x] Proactivity + Reasoning Integration
[x] Documentation
```

O sistema fecha o loop `observe result` e persegue objetivos em múltiplos
passos, sem deixar de ser o agente atômico e revisável por decisão que a
Fase 4 desenhou.

---

# ARQUITETURA-ALVO

```text
                         ┌─────────────────────┐
                         │       WORLD         │
                         │                     │
                         │ Email / Calendar    │
                         │ Computer / Voice    │
                         │ Location / Events   │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │    EVENT SYSTEM     │
                         │                     │
                         │ Event Sources       │
                         │ Event Bus           │
                         │ Event Store         │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   CONTEXT ENGINE    │
                         │                     │
                         │ Current Context     │
                         │ Context Providers   │
                         │ Context Snapshots   │
                         └──────────┬──────────┘
                                    │
                       ┌────────────┴────────────┐
                       │                         │
                       ▼                         ▼
              ┌─────────────────┐       ┌─────────────────┐
              │  MEMORY SYSTEM  │       │  AGENT RUNTIME  │
              │                 │       │                 │
              │ Episodic        │       │ LLM             │
              │ Semantic        │◄─────►│ Reasoning       │
              │ Preferences     │       │ Decisions       │
              │ Procedural      │       │ Planning        │
              └────────┬────────┘       └────────┬────────┘
                       │                         │
                       │                         ▼
                       │                ┌─────────────────┐
                       │                │  POLICY ENGINE  │
                       │                │                 │
                       │                │ Permissions     │
                       │                │ Risk            │
                       │                │ Confirmation    │
                       │                └────────┬────────┘
                       │                         │
                       │                         ▼
                       │                ┌─────────────────┐
                       └───────────────►│     SKILLS      │
                                        │                 │
                                        │ Workflows       │
                                        │ Capabilities    │
                                        └────────┬────────┘
                                                 │
                                                 ▼
                                        ┌─────────────────┐
                                        │   TOOL ROUTER   │
                                        └────────┬────────┘
                                                 │
                                                 ▼
                                        ┌─────────────────┐
                                        │      MCP        │
                                        │                 │
                                        │ External Tools  │
                                        │ Services        │
                                        └────────┬────────┘
                                                 │
                                                 ▼
                                              WORLD
```

---

# FLUXO PRINCIPAL

## Evento externo

```text
evento
 ↓
Event Bus
 ↓
Context Engine
 ↓
Memory Retrieval
 ↓
Agent Runtime
 ↓
Decision
 ├── ignore
 ├── remember
 ├── notify
 ├── ask
 ├── act
 └── act + notify
```

## Ação

```text
Decision
 ↓
Policy
 ↓
Skill
 ↓
Tool Router
 ↓
MCP
 ↓
External Tool
 ↓
Action Result
 ↓
Event
 ↓
Context update
 ↓
Memory
```

## Conversação por voz

```text
Wake Word
 ↓
STT
 ↓
Current Context
 +
Conversation
 +
Memory
 ↓
Agent Runtime
 ↓
Decision
 ↓
Skill / Tool
 ↓
Result
 ↓
TTS
```

---

# CRITÉRIO FINAL DO JARVIS v0.1

O sistema será considerado funcional quando conseguir executar de forma confiável este ciclo:

```text
MUNDO
  ↓
EVENTO
  ↓
CONTEXTO
  ↓
MEMÓRIA
  ↓
RACIOCÍNIO
  ↓
DECISÃO
  ↓
POLICY
  ↓
SKILL
  ↓
MCP / TOOL
  ↓
AÇÃO
  ↓
RESULTADO
  ↓
NOVO EVENTO
  ↓
MEMÓRIA
  ↓
CONTEXTO ATUALIZADO
```

E, paralelamente:

```text
USUÁRIO
   ↓
WAKE WORD
   ↓
STT
   ↓
AGENTE
   ↓
CONTEXTO + MEMÓRIA
   ↓
DECISÃO
   ↓
AÇÃO
   ↓
TTS
```

---

# Histórico de progresso

| Data | Subfase | Status | Commit |
|---|---|---|---|
| 2026-08-08 | 0.1 | ✅ | `chore: initialize repository` |
| 2026-08-08 | 0.2 | ✅ | pendente |
| 2026-08-08 | 0.3 | ✅ | pendente |
| 2026-08-08 | 0.4 | ✅ | pendente |
| 2026-08-08 | 0.5 | ✅ | pendente |
| 2026-08-09 | 0.6 | ✅ | `test: establish project quality gates` |
| 2026-08-09 | 0.7 | ✅ | `chore: complete foundation milestone` |
| 2026-08-09 | 1.1 | ✅ | `feat: implement event domain` |
| 2026-08-09 | 1.2 | ✅ | `feat: implement event bus` |
| 2026-08-09 | 1.3 | ✅ | `feat: implement persistent event store` |
| 2026-08-09 | 1.4 | ✅ | `feat: implement event consumers` |
| 2026-08-09 | 1.5 | ✅ | `feat: complete event-driven core` |
| 2026-08-10 | 2.1 | ✅ | `feat: implement context domain` |
| 2026-08-10 | 2.2 | ✅ | `feat: implement context providers` |
| 2026-08-10 | 2.3 | ✅ | `feat: implement context aggregation` |
| 2026-08-10 | 2.4 | ✅ | `feat: implement context snapshots` |
| 2026-08-10 | 2.5 | ✅ | `feat: complete context engine` |
| 2026-08-10 | 3.1 | ✅ | `feat: implement memory domain` |
| 2026-08-10 | 3.2 | ✅ | `feat: implement persistent memory storage` |
| 2026-08-10 | 3.3 | ✅ | `feat: implement memory retrieval` |
| 2026-08-10 | 3.4 | ✅ | `feat: implement memory scoring` |
| 2026-08-10 | 3.5 | ✅ | `feat: implement memory consolidation` |
| 2026-08-10 | 3.6 | ✅ | `feat: implement memory lifecycle` |
| 2026-08-10 | 3.7 | ✅ | `feat: complete persistent memory system` |
| 2026-08-12 | 4.1 | ✅ | `feat: implement llm provider abstraction` |
| 2026-08-12 | 4.2 | ✅ | `feat: implement agent runtime` |
| 2026-08-12 | 4.3 | ✅ | `feat: implement structured agent decisions` |
| 2026-08-12 | 4.4 | ✅ | `feat: implement importance engine` |
| 2026-08-12 | 4.5 | ✅ | `feat: implement prompt assembly` |
| 2026-08-12 | 4.6 | ✅ | `feat: implement agent event loop` |
| 2026-08-12 | 4.7 | ✅ | `feat: complete autonomous reasoning core` |
| 2026-08-13 | 5.1 | ✅ | `feat: add declarative skill framework` |
| 2026-08-13 | 5.2 | ✅ | `feat: add declarative skill framework` |
| 2026-08-13 | 5.3 | ✅ | `feat: add tool contracts and audited routing` |
| 2026-08-13 | 5.4 | ✅ | `feat: add stdio MCP protocol transport` + `feat: add resilient MCP client integration` |
| 2026-08-13 | 5.5 | ✅ | `feat: add tool contracts and audited routing` + `feat: add sandboxed local tool backend` |
| 2026-08-13 | 5.6 | ✅ | `feat: add built-in file and system skills` |
| — | 5.7 | ⬜ | fora de escopo da Fase 5 (OAuth/integração externa) — ver 5.7 |
| — | 5.8 | ⬜ | fora de escopo da Fase 5 (OAuth/integração externa) — ver 5.8 |
| 2026-08-13 | 5.9 | ✅ | `feat: persist pending action state` + `feat: add CLI commands for skills and actions` |
| 2026-08-13 | 5.10 | ✅ | `feat: orchestrate policy-approved skill execution` + `feat: expose executable skills to agent runtime` |
| 2026-08-14 | 6.1 | ✅ | `feat: implement wake word interface` |
| 2026-08-14 | 6.2 | ✅ | `feat: implement speech-to-text pipeline` |
| 2026-08-14 | 6.3 | ✅ | `feat: implement text-to-speech pipeline` |
| 2026-08-14 | 6.4 | ✅ | `feat: implement voice sessions` |
| 2026-08-14 | 6.5 | ✅ | `feat: implement voice interruption` |
| 2026-08-14 | 6.6 | ✅ | `feat: complete conversational voice interface` |
| 2026-08-14 | 6.7 | ✅ | `feat: implement observability panel` (subfase acrescentada — ver 6.7) |
| 2026-08-14 | 6.8 | ✅ | `feat: serve voice and panel from one process` (subfase acrescentada — ver 6.8) |
| 2026-08-17 | 7.1 | ✅ | `feat: implement event trigger engine` |
| 2026-08-17 | 7.2 | ✅ | `feat: implement interruption policy` |
| 2026-08-17 | 7.3 | ✅ | `feat: implement notification manager` |
| 2026-08-17 | 7.4 | ✅ | `feat: implement agent decision logging` |
| 2026-08-17 | 7.5 | ✅ | `feat: implement background task manager` |
| 2026-08-17 | 7.6 | ✅ | `feat: implement conditional triggers` (integração de memória fora de escopo — ver 7.6) |
| 2026-08-17 | 7.7 | ✅ | `feat: enable proactive agent behavior` |
| 2026-08-17 | 8.1 | ✅ | `feat: implement computer context providers` |
| 2026-08-17 | 8.2 | ✅ | `feat: implement computer skill` |
| 2026-08-17 | 8.3 | ✅ | `feat: implement permission system` |
| 2026-08-17 | 8.4 | ✅ | `feat: implement audit logging` |
| 2026-08-17 | 8.5 | ✅ | `test: add agent behavioral evaluation suite` |
| 2026-08-17 | 8.6 | ✅ | `test: add failure and recovery scenarios` |
| 2026-08-17 | 8.7 | ✅ | `perf: optimize context and memory retrieval` (nenhuma otimização foi necessária — ver 8.7) |
| 2026-08-17 | 8.8 | ✅ | `refactor: harden agent runtime` |
| 2026-08-17 | 8.9 | ✅ | `docs: complete system documentation` |
| 2026-08-17 | 8.10 | ✅ | `release: jarvis v0.1` |
| 2026-08-17 | 9.0 | ✅ | `chore: close out phase 8 completion tracking` |
| 2026-08-17 | 9.1 | ✅ | `feat: close action outcome feedback loop` |
| 2026-08-17 | 9.2 | ✅ | `feat: implement goal pursuit loop` |
| 2026-08-17 | 9.3 | ✅ | `feat: add memory-aware conditional triggers` |
| 2026-08-17 | 9.4 | ✅ | `feat: integrate goal pursuit and memory-aware proactivity` |
| 2026-08-17 | 9.5 | ✅ | `docs: document goal pursuit and memory-aware proactivity` |

---

# Regras do roadmap

1. Não pular subfases sem justificativa.
2. Não marcar uma subfase como concluída apenas porque o código "funciona".
3. Toda subfase deve possuir testes adequados.
4. Toda mudança arquitetural relevante deve ser documentada.
5. Uma nova sessão do Claude Code deve ser utilizada para cada subfase.
6. O Claude Code deve explorar o estado atual do repositório antes de planejar.
7. O Claude Code não deve implementar durante a etapa de planejamento.
8. A implementação só começa após aprovação explícita do plano.
9. O roadmap deve ser atualizado após cada subfase concluída.
10. O código deve permanecer executável ao final de cada subfase.
11. Não adicionar infraestrutura complexa sem necessidade concreta.
12. Não acoplar o sistema a um único fornecedor de LLM.
13. Segurança e permissões devem acompanhar a implementação de capacidades.
14. O sistema deve ser construído de forma que uma nova sessão do Claude Code consiga recuperar o contexto lendo o próprio repositório.