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

- [ ] **Fase 0 — Foundation**
- [ ] **Fase 1 — Event System**
- [ ] **Fase 2 — Context Engine**
- [ ] **Fase 3 — Memory System**
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

- [ ] Criar `CLAUDE.md`
- [ ] Documentar arquitetura
- [ ] Documentar estrutura do projeto
- [ ] Definir convenções de código
- [ ] Definir regras de testes
- [ ] Definir regras para alterações arquiteturais
- [ ] Definir regras para criação de Skills
- [ ] Definir regras para criação de Events
- [ ] Definir regras para documentação
- [ ] Definir workflow de desenvolvimento com Claude Code

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

- [ ] Criar documentação principal
- [ ] Documentar arquitetura de alto nível
- [ ] Documentar responsabilidades dos componentes
- [ ] Documentar fluxo de dados
- [ ] Documentar decisões arquiteturais iniciais
- [ ] Criar estrutura para Architecture Decision Records

**Commit esperado:**

```text
docs: establish architectural documentation
```

---

## 0.6 — Testes, CI e Definition of Done

- [ ] Definir estrutura de testes
- [ ] Criar testes básicos
- [ ] Configurar CI
- [ ] Executar lint automaticamente
- [ ] Executar type checking automaticamente
- [ ] Executar testes automaticamente
- [ ] Definir Definition of Done
- [ ] Definir critérios de qualidade

**Commit esperado:**

```text
test: establish project quality gates
```

---

## 0.7 — Foundation Review

- [ ] Auditar estrutura do projeto
- [ ] Auditar dependências
- [ ] Auditar arquitetura
- [ ] Auditar documentação
- [ ] Auditar testes
- [ ] Verificar reprodutibilidade do ambiente
- [ ] Corrigir problemas encontrados
- [ ] Confirmar Foundation como estável

**Commit esperado:**

```text
chore: complete foundation milestone
```

### Foundation completa

- [ ] **FASE 0 CONCLUÍDA**

---

# FASE 1 — EVENT SYSTEM

**Objetivo:** criar o sistema nervoso do Jarvis: transformar acontecimentos em eventos estruturados e processáveis.

**Período:** Semanas 2–3

## 1.1 — Event Domain

- [ ] Definir entidade `Event`
- [ ] Definir identificador de evento
- [ ] Definir timestamp
- [ ] Definir source
- [ ] Definir event type
- [ ] Definir payload
- [ ] Definir correlation ID
- [ ] Definir causation ID
- [ ] Definir schema version
- [ ] Definir regras de imutabilidade

**Commit esperado:**

```text
feat: implement event domain
```

---

## 1.2 — Event Bus

- [ ] Definir interface do Event Bus
- [ ] Implementar `publish`
- [ ] Implementar `subscribe`
- [ ] Implementar consumo
- [ ] Implementar acknowledgement
- [ ] Implementar retry
- [ ] Implementar tratamento de falhas
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement event bus
```

---

## 1.3 — Event Store

- [ ] Definir armazenamento persistente
- [ ] Criar schema de eventos
- [ ] Implementar persistência
- [ ] Implementar consulta por tipo
- [ ] Implementar consulta temporal
- [ ] Implementar consulta por correlation ID
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement persistent event store
```

---

## 1.4 — Event Consumers

- [ ] Criar abstração `EventConsumer`
- [ ] Implementar consumer básico
- [ ] Implementar processamento assíncrono quando necessário
- [ ] Implementar retry
- [ ] Implementar dead-letter/error handling
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement event consumers
```

---

## 1.5 — Event System Integration

- [ ] Integrar Event Domain
- [ ] Integrar Event Bus
- [ ] Integrar Event Store
- [ ] Integrar Consumers
- [ ] Criar fluxo completo
- [ ] Testar eventos end-to-end

**Commit esperado:**

```text
feat: complete event-driven core
```

### Event System completo

- [ ] **FASE 1 CONCLUÍDA**

---

# FASE 2 — CONTEXT ENGINE

**Objetivo:** transformar eventos e dados ambientais em uma representação estruturada do estado atual do usuário e do sistema.

**Período:** Semanas 4–5

## 2.1 — Context Domain

- [ ] Definir `CurrentContext`
- [ ] Definir `UserContext`
- [ ] Definir `EnvironmentContext`
- [ ] Definir `DeviceContext`
- [ ] Definir `ActivityContext`
- [ ] Definir `ScheduleContext`
- [ ] Definir `ConversationContext`
- [ ] Definir `TaskContext`
- [ ] Definir timestamps e validade dos dados

**Commit esperado:**

```text
feat: implement context domain
```

---

## 2.2 — Context Providers

- [ ] Criar interface `ContextProvider`
- [ ] Criar Time Provider
- [ ] Criar Device Provider
- [ ] Criar Activity Provider
- [ ] Criar Calendar Provider
- [ ] Criar Location Provider
- [ ] Criar mocks para testes

**Commit esperado:**

```text
feat: implement context providers
```

---

## 2.3 — Context Aggregation

- [ ] Criar Context Aggregator
- [ ] Coletar dados dos providers
- [ ] Resolver conflitos
- [ ] Controlar validade dos dados
- [ ] Implementar timestamps
- [ ] Criar `get_current_context`
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement context aggregation
```

---

## 2.4 — Context Snapshots

- [ ] Definir snapshot
- [ ] Persistir snapshots relevantes
- [ ] Implementar consulta histórica
- [ ] Implementar expiração
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement context snapshots
```

---

## 2.5 — Context Integration

- [ ] Integrar Event System
- [ ] Integrar Context Engine
- [ ] Atualizar contexto a partir de eventos
- [ ] Validar consistência
- [ ] Testar fluxo completo

**Commit esperado:**

```text
feat: complete context engine
```

### Context Engine completo

- [ ] **FASE 2 CONCLUÍDA**

---

# FASE 3 — MEMORY SYSTEM

**Objetivo:** criar memória persistente, recuperável, contextual e com ciclo de vida.

**Período:** Semanas 6–7

## 3.1 — Memory Domain

- [ ] Definir `Memory`
- [ ] Definir memória episódica
- [ ] Definir memória semântica
- [ ] Definir memória de preferências
- [ ] Definir memória procedural
- [ ] Definir working memory
- [ ] Definir task memory
- [ ] Definir metadados
- [ ] Definir confidence
- [ ] Definir importance
- [ ] Definir timestamps
- [ ] Definir expiration

**Commit esperado:**

```text
feat: implement memory domain
```

---

## 3.2 — Persistent Memory Storage

- [ ] Definir banco de dados
- [ ] Configurar PostgreSQL
- [ ] Configurar pgvector
- [ ] Criar schema
- [ ] Criar migrations
- [ ] Implementar repository
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement persistent memory storage
```

---

## 3.3 — Memory Retrieval

- [ ] Implementar busca semântica
- [ ] Implementar busca temporal
- [ ] Implementar busca por entidades
- [ ] Implementar filtros
- [ ] Implementar ranking inicial
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement memory retrieval
```

---

## 3.4 — Memory Scoring

- [ ] Definir relevância
- [ ] Definir recência
- [ ] Definir importância
- [ ] Definir confidence
- [ ] Definir relevância temporal
- [ ] Implementar scoring combinado
- [ ] Testar ranking

**Commit esperado:**

```text
feat: implement memory scoring
```

---

## 3.5 — Memory Consolidation

- [ ] Definir consolidação
- [ ] Detectar padrões
- [ ] Criar memórias semânticas
- [ ] Relacionar memórias
- [ ] Controlar confidence
- [ ] Evitar duplicações
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement memory consolidation
```

---

## 3.6 — Memory Lifecycle

- [ ] Implementar reinforcement
- [ ] Implementar decay
- [ ] Implementar expiration
- [ ] Implementar forget
- [ ] Implementar delete
- [ ] Implementar atualização
- [ ] Registrar origem das memórias
- [ ] Criar testes

**Commit esperado:**

```text
feat: implement memory lifecycle
```

---

## 3.7 — Memory Integration

- [ ] Integrar Event System
- [ ] Integrar Context Engine
- [ ] Criar fluxo evento → memória
- [ ] Criar fluxo contexto → memória relevante
- [ ] Testar recuperação contextual

**Commit esperado:**

```text
feat: complete persistent memory system
```

### Memory System completo

- [ ] **FASE 3 CONCLUÍDA**

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
[ ] Repositório
[ ] Tooling
[ ] Contratos
[ ] CLAUDE.md
[ ] Documentação
[ ] CI
[ ] Testes
```

---

## M1 — Event-Driven Core

**Semana 3**

```text
[ ] Events
[ ] Event Bus
[ ] Event Store
[ ] Consumers
```

O sistema consegue perceber acontecimentos estruturados.

---

## M2 — Context-Aware

**Semana 5**

```text
[ ] Context
[ ] Providers
[ ] Aggregation
[ ] Snapshots
```

O sistema consegue representar o estado atual.

---

## M3 — Persistent Memory

**Semana 7**

```text
[ ] Memory
[ ] PostgreSQL
[ ] Vector search
[ ] Retrieval
[ ] Consolidation
[ ] Lifecycle
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
| — | 0.4 | ⬜ | — |
| — | 0.5 | ⬜ | — |
| — | 0.6 | ⬜ | — |
| — | 0.7 | ⬜ | — |
| — | 1.1 | ⬜ | — |
| — | 1.2 | ⬜ | — |
| — | 1.3 | ⬜ | — |
| — | 1.4 | ⬜ | — |
| — | 1.5 | ⬜ | — |
| — | 2.1 | ⬜ | — |
| — | 2.2 | ⬜ | — |
| — | 2.3 | ⬜ | — |
| — | 2.4 | ⬜ | — |
| — | 2.5 | ⬜ | — |
| — | 3.1 | ⬜ | — |
| — | 3.2 | ⬜ | — |
| — | 3.3 | ⬜ | — |
| — | 3.4 | ⬜ | — |
| — | 3.5 | ⬜ | — |
| — | 3.6 | ⬜ | — |
| — | 3.7 | ⬜ | — |
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