# Documentação

Esta pasta reúne a documentação técnica do Jarvis.

## O que já existe

- [`architecture-contracts.md`](architecture-contracts.md) — os contratos
  arquiteturais que todo componente futuro do Jarvis deve respeitar (limites
  de componentes, regras de dependência, contratos de Event/Context/Memory/
  Skill, fronteira de segurança, persistência, configuração, erros e
  observability). Definidos na subfase 0.3.
- [`adr/`](adr/) — Architecture Decision Records: as decisões pontuais e
  difíceis de reverter que fundamentam os contratos acima.

## O que ainda não existe

A documentação de arquitetura de alto nível (`architecture.md`) e a
documentação por componente (`event-system.md`, `context-system.md`,
`memory-system.md`, `agent-runtime.md`, `skills.md`, `mcp.md`,
`security.md`) será criada na subfase 0.5 do [roadmap](../ROADMAP.md).

## Contratos vs. documentação de implementação

Duas categorias de documento coexistem neste projeto, com regras diferentes:

- **Contratos** (`architecture-contracts.md`, `adr/`) precisam existir
  *antes* do código que restringem — é o próprio propósito deles: impedir
  acoplamento antes que ele seja escrito. Ficam vivos e são atualizados
  quando a realidade diverge; uma mudança de decisão de ADR gera um novo
  ADR que supera o anterior, não uma edição silenciosa do antigo.
- **Documentação de implementação/uso** (os documentos por componente da
  0.5 em diante) descreve o comportamento real de código que já existe.
  Essa continua seguindo a regra original: **cada documento é criado junto
  da funcionalidade que descreve, não antes.**
