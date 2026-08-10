# Jarvis — Roadmap de Desenvolvimento

> Roadmap técnico para desenvolvimento incremental do agente pessoal de IA.
>
> **Duração planejada:** 16 semanas  
> **Metodologia:** uma sessão do Claude Code por subfase  
> **Fluxo:** Planejamento → Revisão → Implementação → Testes → Revisão → Commit  
> **Status inicial:** Em desenvolvimento

---

# Visão geral

O sistema será construído em oito fases:

- [x] **Fase 0 — Foundation**
- [x] **Fase 1 — Event System**
- [x] **Fase 2 — Context Engine**
- [x] **Fase 3 — Memory System**
- [ ] **Fase 4 — Agent Runtime**
- [ ] **Fase 5 — Skills + MCP**
- [ ] **Fase 6 — Voice**
- [ ] **Fase 7 — Proactivity + Autonomy**
- [ ] **Fase 8 — Integration + Hardening**

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

- [ ] Criar interface `LLMProvider`
- [ ] Criar abstração de mensagens
- [ ] Criar abstração de respostas
- [ ] Implementar provider inicial
- [ ] Configurar credenciais
- [ ] Implementar tratamento de erros
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement llm provider abstraction
```

---

## 4.2 — Agent Runtime

- [ ] Criar `AgentRuntime`
- [ ] Definir entradas
- [ ] Definir saídas
- [ ] Integrar contexto
- [ ] Integrar memória
- [ ] Integrar eventos
- [ ] Integrar LLM

**Commit esperado:**

```text
feat: implement agent runtime
```

---

## 4.3 — Structured Decisions

- [ ] Definir schema de decisão
- [ ] Implementar `ignore`
- [ ] Implementar `remember`
- [ ] Implementar `notify`
- [ ] Implementar `ask`
- [ ] Implementar `act`
- [ ] Implementar `act_and_notify`
- [ ] Implementar validação

**Commit esperado:**

```text
feat: implement structured agent decisions
```

---

## 4.4 — Importance Engine

- [ ] Definir importance
- [ ] Definir urgency
- [ ] Definir personal relevance
- [ ] Definir temporal relevance
- [ ] Definir interruption cost
- [ ] Implementar avaliação
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement importance engine
```

---

## 4.5 — Prompt Assembly

- [ ] Criar `PromptBuilder`
- [ ] Definir system instructions
- [ ] Integrar contexto
- [ ] Integrar memória
- [ ] Integrar evento
- [ ] Integrar capacidades
- [ ] Integrar conversa
- [ ] Controlar tamanho do contexto
- [ ] Criar testes

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

- [ ] Implementar ciclo
- [ ] Implementar state handling
- [ ] Implementar erros
- [ ] Implementar timeout
- [ ] Implementar logging
- [ ] Criar testes end-to-end

**Commit esperado:**

```text
feat: implement agent event loop
```

---

## 4.7 — Agent Integration

- [ ] Integrar Events
- [ ] Integrar Context
- [ ] Integrar Memory
- [ ] Integrar LLM
- [ ] Testar evento → contexto → memória → decisão

**Commit esperado:**

```text
feat: complete autonomous reasoning core
```

### Agent Runtime completo

- [ ] **FASE 4 CONCLUÍDA**

---

# FASE 5 — SKILLS + MCP

**Objetivo:** permitir que o agente execute ações de forma estruturada e controlada.

**Período:** Semanas 10–11

## 5.1 — Skill Framework

- [ ] Criar `Skill`
- [ ] Definir capabilities
- [ ] Definir permissions
- [ ] Definir risk level
- [ ] Definir confirmation policy
- [ ] Definir execução
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement skill framework
```

---

## 5.2 — Skill Registry

- [ ] Implementar registro
- [ ] Implementar descoberta
- [ ] Implementar consulta
- [ ] Implementar listagem
- [ ] Implementar capabilities
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement skill registry
```

---

## 5.3 — Tool Abstraction

- [ ] Criar `Tool`
- [ ] Criar `ToolResult`
- [ ] Criar `ToolError`
- [ ] Definir input schema
- [ ] Definir output schema
- [ ] Definir risk metadata
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement tool abstraction
```

---

## 5.4 — MCP Client

- [ ] Implementar conexão MCP
- [ ] Implementar descoberta de ferramentas
- [ ] Validar schemas
- [ ] Implementar chamadas
- [ ] Implementar erros
- [ ] Implementar timeout
- [ ] Implementar reconexão
- [ ] Criar testes

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

- [ ] Implementar roteamento
- [ ] Validar permissões
- [ ] Validar schemas
- [ ] Registrar execução
- [ ] Tratar erros

**Commit esperado:**

```text
feat: implement tool router
```

---

## 5.6 — System + File Skills

- [ ] Criar System Skill
- [ ] Criar File Skill
- [ ] Definir permissões
- [ ] Implementar operações seguras
- [ ] Implementar confirmação
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement system and file skills
```

---

## 5.7 — Calendar Skill

- [ ] Criar integração
- [ ] Ler eventos
- [ ] Criar eventos
- [ ] Atualizar eventos
- [ ] Implementar permissões
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement calendar skill
```

---

## 5.8 — Email Skill

- [ ] Criar integração
- [ ] Ler emails
- [ ] Buscar emails
- [ ] Criar drafts
- [ ] Enviar emails com confirmação
- [ ] Implementar permissões
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement email skill
```

---

## 5.9 — Confirmation System

- [ ] Definir níveis de risco
- [ ] Definir ações automáticas
- [ ] Definir ações que exigem confirmação
- [ ] Criar confirmation manager
- [ ] Registrar decisões
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement confirmation system
```

---

## 5.10 — Skills + MCP Integration

- [ ] Integrar Agent Runtime
- [ ] Integrar Skill Registry
- [ ] Integrar Tool Router
- [ ] Integrar MCP
- [ ] Testar agente executando uma ação real
- [ ] Validar permissões

**Commit esperado:**

```text
feat: complete skill and MCP architecture
```

### Skills + MCP completos

- [ ] **FASE 5 CONCLUÍDA**

---

# FASE 6 — VOICE

**Objetivo:** criar interface conversacional por voz com wake word.

**Período:** Semana 12

## 6.1 — Wake Word

- [ ] Criar `WakeWordDetector`
- [ ] Definir interface
- [ ] Integrar detector
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement wake word interface
```

---

## 6.2 — Speech-to-Text

- [ ] Criar `SpeechToText`
- [ ] Integrar modelo/provider
- [ ] Implementar captura
- [ ] Implementar transcrição
- [ ] Tratar erros
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement speech-to-text pipeline
```

---

## 6.3 — Text-to-Speech

- [ ] Criar `TextToSpeech`
- [ ] Integrar provider
- [ ] Implementar geração
- [ ] Implementar reprodução
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement text-to-speech pipeline
```

---

## 6.4 — Voice Sessions

- [ ] Criar `VoiceSession`
- [ ] Definir session ID
- [ ] Integrar conversa
- [ ] Controlar timeout
- [ ] Controlar estado
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement voice sessions
```

---

## 6.5 — Interruption

- [ ] Detectar nova fala
- [ ] Interromper TTS
- [ ] Processar novo comando
- [ ] Controlar concorrência
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement voice interruption
```

---

## 6.6 — Voice Integration

- [ ] Integrar wake word
- [ ] Integrar STT
- [ ] Integrar Agent
- [ ] Integrar TTS
- [ ] Testar conversa completa

**Commit esperado:**

```text
feat: complete conversational voice interface
```

### Voice completo

- [ ] **FASE 6 CONCLUÍDA**

---

# FASE 7 — PROACTIVITY + AUTONOMY

**Objetivo:** permitir que o agente avalie eventos autonomamente e decida quando agir ou interromper o usuário.

**Período:** Semanas 13–14

## 7.1 — Trigger Engine

- [ ] Criar trigger engine
- [ ] Integrar eventos
- [ ] Definir condições
- [ ] Definir triggers
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement event trigger engine
```

---

## 7.2 — Interruption Policy

- [ ] Considerar importância
- [ ] Considerar atividade do usuário
- [ ] Considerar foco
- [ ] Considerar horário
- [ ] Considerar localização
- [ ] Considerar conversa atual
- [ ] Considerar notificações recentes
- [ ] Criar política de interrupção
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement interruption policy
```

---

## 7.3 — Notification Manager

- [ ] Criar Notification Manager
- [ ] Implementar desktop notification
- [ ] Implementar voice notification
- [ ] Implementar silent mode
- [ ] Implementar prioridade
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement notification manager
```

---

## 7.4 — Decision Logging

- [ ] Registrar decisões
- [ ] Registrar contexto utilizado
- [ ] Registrar memória utilizada
- [ ] Registrar razão
- [ ] Registrar ações
- [ ] Permitir consulta posterior
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement agent decision logging
```

---

## 7.5 — Background Task Manager

- [ ] Criar Task Manager
- [ ] Criar estados de tarefa
- [ ] Executar tarefas em background
- [ ] Implementar retry
- [ ] Implementar cancelamento
- [ ] Implementar falhas
- [ ] Criar testes

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

- [ ] Criar condições
- [ ] Integrar contexto
- [ ] Integrar memória
- [ ] Integrar eventos
- [ ] Executar ações
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement conditional triggers
```

---

## 7.7 — Proactivity Integration

- [ ] Integrar triggers
- [ ] Integrar policy
- [ ] Integrar notifications
- [ ] Integrar memory
- [ ] Integrar tasks
- [ ] Testar comportamento proativo completo

**Commit esperado:**

```text
feat: enable proactive agent behavior
```

### Proactivity completa

- [ ] **FASE 7 CONCLUÍDA**

---

# FASE 8 — INTEGRATION + HARDENING

**Objetivo:** integrar o sistema com o computador e torná-lo confiável, seguro e avaliável.

**Período:** Semanas 15–16

## 8.1 — Computer Context

- [ ] Detectar aplicação ativa
- [ ] Detectar janela ativa
- [ ] Detectar CPU
- [ ] Detectar RAM
- [ ] Detectar GPU
- [ ] Detectar rede
- [ ] Detectar tempo de inatividade
- [ ] Detectar processos relevantes
- [ ] Integrar ao Context Engine

**Commit esperado:**

```text
feat: implement computer context providers
```

---

## 8.2 — Computer Skill

- [ ] Abrir aplicação
- [ ] Fechar aplicação
- [ ] Focar janela
- [ ] Interagir com interface
- [ ] Ler tela quando apropriado
- [ ] Executar comandos seguros
- [ ] Implementar permissões
- [ ] Implementar confirmação
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement computer skill
```

---

## 8.3 — Permission System

- [ ] Definir permission model
- [ ] Definir níveis de risco
- [ ] Definir capabilities
- [ ] Implementar allowlist
- [ ] Implementar denylist
- [ ] Integrar Skills
- [ ] Integrar MCP
- [ ] Integrar Computer Skill

**Commit esperado:**

```text
feat: implement permission system
```

---

## 8.4 — Audit Logging

- [ ] Registrar ações
- [ ] Registrar ferramentas
- [ ] Registrar decisões
- [ ] Registrar confirmações
- [ ] Registrar falhas
- [ ] Implementar consulta
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement audit logging
```

---

## 8.5 — Behavioral Evaluation

Criar cenários de avaliação:

- [ ] Email importante durante período de foco
- [ ] Email irrelevante
- [ ] Reunião próxima
- [ ] Solicitação para enviar email
- [ ] Falha de ferramenta
- [ ] Memórias contraditórias
- [ ] Mudança de preferência
- [ ] Situação em que o agente deve permanecer em silêncio

**Commit esperado:**

```text
test: add agent behavioral evaluation suite
```

---

## 8.6 — Failure + Recovery

Testar:

- [ ] LLM indisponível
- [ ] Banco indisponível
- [ ] MCP indisponível
- [ ] Timeout
- [ ] Evento duplicado
- [ ] Evento fora de ordem
- [ ] Contexto desatualizado
- [ ] Tool failure
- [ ] Processo reiniciado
- [ ] Recuperação após crash

**Commit esperado:**

```text
test: add failure and recovery scenarios
```

---

## 8.7 — Performance

- [ ] Medir latência
- [ ] Medir retrieval
- [ ] Medir construção de contexto
- [ ] Medir chamadas ao LLM
- [ ] Identificar gargalos
- [ ] Otimizar componentes críticos
- [ ] Criar benchmarks

**Commit esperado:**

```text
perf: optimize context and memory retrieval
```

---

## 8.8 — Runtime Hardening

- [ ] Revisar concorrência
- [ ] Revisar tratamento de erros
- [ ] Revisar timeouts
- [ ] Revisar retries
- [ ] Revisar logs
- [ ] Revisar dependências
- [ ] Revisar limites de segurança
- [ ] Corrigir problemas críticos

**Commit esperado:**

```text
refactor: harden agent runtime
```

---

## 8.9 — Documentation Review

- [ ] Atualizar arquitetura
- [ ] Atualizar Skills
- [ ] Atualizar MCP
- [ ] Atualizar memória
- [ ] Atualizar contexto
- [ ] Atualizar setup
- [ ] Atualizar troubleshooting
- [ ] Atualizar roadmap
- [ ] Documentar decisões finais

**Commit esperado:**

```text
docs: complete system documentation
```

---

## 8.10 — Release Review

- [ ] Executar todos os testes
- [ ] Executar lint
- [ ] Executar type checking
- [ ] Validar instalação limpa
- [ ] Validar configuração
- [ ] Validar segurança
- [ ] Validar principais workflows
- [ ] Validar voz
- [ ] Validar memória
- [ ] Validar proatividade
- [ ] Validar Skills
- [ ] Validar MCP
- [ ] Confirmar critérios de v0.1

**Commit esperado:**

```text
release: jarvis v0.1
```

### Release

- [ ] **FASE 8 CONCLUÍDA**

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
[ ] LLM
[ ] Agent Runtime
[ ] Decisions
[ ] Importance
[ ] Prompt Assembly
[ ] Agent Loop
```

O sistema consegue raciocinar sobre acontecimentos.

---

## M5 — Actionable Agent

**Semana 11**

```text
[ ] Skills
[ ] Tools
[ ] MCP
[ ] Router
[ ] Permissions
[ ] Confirmation
```

O sistema consegue agir.

---

## M6 — Voice Agent

**Semana 12**

```text
[ ] Wake Word
[ ] STT
[ ] Agent
[ ] TTS
[ ] Interruption
```

O sistema consegue conversar.

---

## M7 — Proactive Agent

**Semana 14**

```text
[ ] Triggers
[ ] Policies
[ ] Notifications
[ ] Tasks
[ ] Conditional Actions
```

O sistema consegue decidir quando deve falar e agir.

---

## M8 — Jarvis v0.1

**Semana 16**

```text
[ ] Computer Awareness
[ ] Computer Skill
[ ] Security
[ ] Audit
[ ] Evaluation
[ ] Recovery
[ ] Performance
[ ] Documentation
```

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
| — | 4.1 | ⬜ | — |
| — | 4.2 | ⬜ | — |
| — | 4.3 | ⬜ | — |
| — | 4.4 | ⬜ | — |
| — | 4.5 | ⬜ | — |
| — | 4.6 | ⬜ | — |
| — | 4.7 | ⬜ | — |
| — | 5.1 | ⬜ | — |
| — | 5.2 | ⬜ | — |
| — | 5.3 | ⬜ | — |
| — | 5.4 | ⬜ | — |
| — | 5.5 | ⬜ | — |
| — | 5.6 | ⬜ | — |
| — | 5.7 | ⬜ | — |
| — | 5.8 | ⬜ | — |
| — | 5.9 | ⬜ | — |
| — | 5.10 | ⬜ | — |
| — | 6.1 | ⬜ | — |
| — | 6.2 | ⬜ | — |
| — | 6.3 | ⬜ | — |
| — | 6.4 | ⬜ | — |
| — | 6.5 | ⬜ | — |
| — | 6.6 | ⬜ | — |
| — | 7.1 | ⬜ | — |
| — | 7.2 | ⬜ | — |
| — | 7.3 | ⬜ | — |
| — | 7.4 | ⬜ | — |
| — | 7.5 | ⬜ | — |
| — | 7.6 | ⬜ | — |
| — | 7.7 | ⬜ | — |
| — | 8.1 | ⬜ | — |
| — | 8.2 | ⬜ | — |
| — | 8.3 | ⬜ | — |
| — | 8.4 | ⬜ | — |
| — | 8.5 | ⬜ | — |
| — | 8.6 | ⬜ | — |
| — | 8.7 | ⬜ | — |
| — | 8.8 | ⬜ | — |
| — | 8.9 | ⬜ | — |
| — | 8.10 | ⬜ | — |

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