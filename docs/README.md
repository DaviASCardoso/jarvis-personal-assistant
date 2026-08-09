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
- Documentação conceitual por componente, criada na subfase 0.5 — explica
  cada contrato aprovado na 0.3 sem repeti-lo e sem implementar nada ainda
  (cada componente segue sem código real até sua fase correspondente no
  [roadmap](../ROADMAP.md)):
  - [`event-system.md`](event-system.md) — Event, Event Source, Event
    Store, Event Consumer, correlation/causation, idempotência (Fase 1).
  - [`context-system.md`](context-system.md) — `CurrentContext`,
    `ContextSnapshot`, providers, freshness/TTL, confiança (Fase 2).
  - [`memory-system.md`](memory-system.md) — tipos de memória,
    importance/confidence/relevance, `EmbeddingProvider` (Fase 3).
  - [`agent-runtime.md`](agent-runtime.md) — loop observe→...→execute,
    `Decision`, `LLMProvider` (Fase 4).
  - [`skills.md`](skills.md) — distinção Skill/Tool/MCP, contrato de
    Skill, cadeia Agent→Skill→Tool Router→MCP (Fase 5).
  - [`mcp.md`](mcp.md) — MCP Client/Server/Tool, Tool Router (Fase 5).
  - [`security.md`](security.md) — Policy Engine, `PolicyApproval`,
    secrets, auditabilidade, prompt injection, menor privilégio (Fase 5,
    transversal).

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
