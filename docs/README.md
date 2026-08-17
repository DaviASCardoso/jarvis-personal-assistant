# Documentação

Esta pasta reúne a documentação técnica do Jarvis.

## O que já existe

- [`architecture.md`](architecture.md) — visão geral narrativa da
  arquitetura: propósito do sistema, componentes, Ports & Adapters, fluxo
  de dados, e como eventos, contexto, memória, agente, policy, skills e
  tools se relacionam. Não é normativo — explica e conecta os contratos
  abaixo, com links para eles. Criado na subfase 0.5.
- [`architecture-contracts.md`](architecture-contracts.md) — os contratos
  arquiteturais que todo componente futuro do Jarvis deve respeitar (limites
  de componentes, regras de dependência, contratos de Event/Context/Memory/
  Skill, fronteira de segurança, persistência, configuração, erros e
  observability). Definidos na subfase 0.3.
- [`adr/`](adr/) — Architecture Decision Records: as decisões pontuais e
  difíceis de reverter que fundamentam os contratos acima.
- [`event-system.md`](event-system.md) — **documentação de implementação**:
  descreve o Event System que existe em `src/jarvis/events/` desde a Fase 1
  (Event/RecordedEvent, Event Store SQLite, Event Bus, consumers,
  correlation/causation, idempotência, comandos de CLI).
- [`context-system.md`](context-system.md) — **documentação de implementação**:
  descreve o Context Engine que existe em `src/jarvis/context/` desde a Fase 2
  (`Observation`, os sete subcontextos, TTL por campo, conflitos, eventos
  projetados, reconstrução, snapshots com expiração lógica, comandos de CLI).
- [`memory-system.md`](memory-system.md) — **documentação de implementação**:
  descreve o Memory System que existe em `src/jarvis/memory/` desde a Fase 3
  (`Memory`/`StoredMemory`, `EmbeddingProvider` e o adapter de hashing,
  retrieval estruturado e semântico, ranking explicável, ciclo de vida,
  consolidação por deduplicação/contradição/promoção, integração com Event
  System e Context Engine, comandos de CLI).
- [`agent-runtime.md`](agent-runtime.md) — **documentação de implementação**:
  descreve o Agent Runtime que existe em `src/jarvis/agent/` desde a Fase 4
  (`LLMProvider` e o adapter Gemini, `Decision` e seu parsing, Importance
  Engine determinístico, prompt assembly com orçamento, erros/timeout/retry,
  observabilidade, comandos de CLI e limitações conhecidas).
- [`skills.md`](skills.md) — **documentação de implementação**: descreve o Skill
  Framework que existe em `src/jarvis/skills/` desde a Fase 5 (`SkillDescriptor`
  com risco/efeitos/idempotência, validação de parâmetros, registry explícito,
  catálogo inicial, ciclo de execução, `ToolAccess`).
- [`mcp.md`](mcp.md) — **documentação de implementação**: descreve a camada de
  Tools que existe em `src/jarvis/tools/` desde a Fase 5 (contrato de `Tool`,
  Tool Router, registry e descoberta, backend local, cliente MCP sobre stdio,
  `mcp.json`, normalização de erros).
- [`voice.md`](voice.md) — **documentação de implementação**: descreve a camada
  de voz que existe em `src/jarvis/voice/` desde a Fase 6 (os sete ports, as duas
  estratégias de wake word sem IA local, VAD determinístico, STT/TTS em nuvem por
  REST da stdlib, sessão com retenção, interrupção, o que sai do dispositivo,
  comandos de CLI e limitações conhecidas).
- [`interface.md`](interface.md) — **documentação de implementação**: descreve o
  painel de observabilidade que existe em `src/jarvis/interface/` desde a Fase 6
  (view models, contrato de `/api/state`, as duas cadências de atualização,
  modelo de threads, por que é somente leitura, toasts e privacidade).
- [`security.md`](security.md) — **documentação de implementação**: descreve o
  Policy Engine e a camada de execução que existem em `src/jarvis/policy/` e
  `src/jarvis/execution/` desde a Fase 5 (regras e composição por força,
  `PolicyApproval` de uso único, fluxo de confirmação, menor privilégio em três
  camadas, as cinco impossibilidades, auditoria, secrets).
- [`proactivity.md`](proactivity.md) — **documentação de implementação**:
  descreve a proatividade que existe em `src/jarvis/proactivity/`,
  `src/jarvis/notify/`, `src/jarvis/decisions/` e `src/jarvis/tasks/` desde a
  Fase 7 (Trigger Engine, Interruption Policy, Conditional Triggers sem LLM,
  Notification Manager, Decision Log como eventos, Background Task Manager
  ticado sem thread nova, os três interruptores de opt-in, comandos de CLI e
  a limitação conhecida de escopo de reação entre processos).
- [`computer.md`](computer.md) — **documentação de implementação**: descreve
  o Computer Context e a Computer Skill que existem em
  `src/jarvis/context/adapters/{window_activity,resource_usage,
  process_activity}_provider.py`, `src/jarvis/tools/adapters/
  computer_backend.py` e `src/jarvis/skills/builtin/computer.py` desde a
  Fase 8 (os oito campos de contexto de computador, as cinco Skills, o
  modelo de allowlist de comandos, comandos de CLI e limitações conhecidas).
- [`troubleshooting.md`](troubleshooting.md) — problemas de setup conhecidos
  entre todas as fases (credencial ausente, extra de voz não instalado,
  `psutil` sem permissão em ambiente restrito, painel não abre no
  navegador), consolidados a partir das mensagens de erro que já existem.
- [`phase-1-plan.md`](phase-1-plan.md), [`phase-2-plan.md`](phase-2-plan.md),
  [`phase-3-plan.md`](phase-3-plan.md), [`phase-4-plan.md`](phase-4-plan.md),
  [`phase-5-plan.md`](phase-5-plan.md), [`phase-6-plan.md`](phase-6-plan.md),
  [`phase-7-plan.md`](phase-7-plan.md) e [`phase-8-plan.md`](phase-8-plan.md)
  — os planos técnicos aprovados que guiaram as Fases 1 a 8, incluindo as
  decisões consideradas e as descartadas.

## Contratos vs. documentação de implementação

Duas categorias de documento coexistem neste projeto, com regras diferentes:

- **Contratos** (`architecture-contracts.md`, `adr/`) precisam existir
  *antes* do código que restringem — é o próprio propósito deles: impedir
  acoplamento antes que ele seja escrito. Ficam vivos e são atualizados
  quando a realidade diverge; uma mudança de decisão de ADR gera um novo
  ADR que supera o anterior, não uma edição silenciosa do antigo.
- **Documentação conceitual por componente** (`architecture.md` e os
  documentos listados acima, criados na 0.5) é uma exceção deliberada à
  regra seguinte: ela explica contratos já aprovados na 0.3 *antes* de a
  funcionalidade correspondente existir, porque o roadmap front-carrega
  essa explicação para a subfase 0.5 — nenhum desses documentos descreve
  API ou classe real, e cada um deixa isso explícito.
- **Documentação de implementação/uso** (atualizações destes mesmos
  documentos, ou documentos novos, a partir da fase em que cada componente
  ganha código real) descreve o comportamento real de código que já
  existe. Essa segue a regra original: **cada atualização é feita junto da
  funcionalidade que descreve, não antes.**
