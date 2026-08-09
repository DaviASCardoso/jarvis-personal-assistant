# MCP (Model Context Protocol)

> Documentação conceitual do MCP Client e do Tool Router, previstos para a
> **Fase 5** do [roadmap](../ROADMAP.md). Criada na subfase **0.5** como
> explicação de um contrato já aprovado na 0.3 — **não implementa** o MCP
> Client nem conecta nenhum servidor MCP real. O contrato normativo
> completo está em
> [`architecture-contracts.md §9`](architecture-contracts.md#9-tool--mcp-boundary)
> e em [ADR-0005](adr/0005-skill-tool-mcp-distinction.md); este documento
> explica o *porquê* e o *como se relaciona*, sem repetir a tabela de
> responsabilidades. Para a distinção Skill/Tool e o contrato de Skill, ver
> [skills.md](skills.md).

## Onde o MCP entra na cadeia

```text
Agent → Skill → Tool Router → MCP Client → MCP Server → Tool
```

O MCP não é conhecido pelo Agent Runtime nem pela Skill diretamente — ele é
um detalhe de **como** o Tool Router cumpre uma chamada de tool já
aprovada. Isso é deliberado: o contrato de `Tool` não assume MCP como único
backend possível no futuro, mesmo que seja o único implementado na Fase 5
(ver [`architecture-contracts.md §3.7`](architecture-contracts.md#37-tool-router)).

## MCP Client

**Responsabilidade:** implementar o protocolo MCP em si — conexão com um
MCP Server, descoberta de ferramentas expostas, validação de schema no
limite do protocolo, invocação, reconexão em caso de queda.

- **Permitido conhecer:** o protocolo MCP e a configuração de conexão dos
  servers.
- **Proibido conhecer:** Skills, Agent Runtime, Policy, Memory — o MCP
  Client não sabe (nem precisa saber) por que uma chamada de tool está
  acontecendo, só como executá-la tecnicamente.
- **Entrada:** um `ToolCall` técnico, já vindo do Tool Router.
- **Saída:** o resultado bruto do MCP server, traduzido para o contrato de
  `ToolResult`/`ToolError` do Core — nunca o erro cru de transporte/
  protocolo (JSON-RPC) vazando para cima.

O MCP Client é parte de Infrastructure: implementa um port definido pelo
Core, não o contrário.

## MCP Server e MCP Tool

- **MCP Server** é o processo externo que expõe uma ou mais Tools via
  protocolo MCP — um detalhe de onde uma Tool "mora", irrelevante para
  quem consome a Tool através do Tool Router.
- **MCP Tool** é a representação de wire-level de uma Tool, como
  descoberta via protocolo MCP (schema JSON, nome, descrição). O MCP
  Client/Tool Router traduzem essa representação para o contrato interno
  de `Tool` do Core — o resto do sistema nunca lida com o formato de wire
  diretamente.

## Tool Router

**Responsabilidade:** rotear uma chamada de tool vinda de uma Skill até o
backend correto (MCP hoje; outros backends possíveis no futuro),
normalizar resultados/erros, aplicar timeout por chamada, e registrar toda
execução em um único ponto (choke point de auditoria — ver
[security.md](security.md)).

| Aspecto | Onde ocorre |
|---|---|
| Validação de regra de negócio | na Skill, antes de qualquer chamada de Tool |
| Validação de schema técnico | Tool Router / MCP Client, imediatamente antes do dispatch |
| Permissão | Policy Engine, **antes** de a Skill sequer executar (`PolicyApproval`) |
| Timeout | Tool Router, por chamada — uma Skill que compõe várias Tools pode ter orçamento de tempo adicional próprio |
| Normalização de erros | limite MCP Client → Tool Router: erros de transporte viram `ToolTimeoutError`, `ToolNotFoundError`, `ToolExecutionError`, `ToolInvalidInputError` |
| Registro de execução | Tool Router — Skills não implementam logging próprio de execução de tool |

**Entrada:** um `ToolCall` já aprovado pelo Policy Engine. **Saída:** um
`ToolResult` ou `ToolError` normalizado — Skills e Agent Runtime nunca veem
erro cru de MCP/JSON-RPC.

## O que o Tool Router pode e não pode conhecer

Permitido: MCP Client port, registry de tools/discovery, configuração de
timeout. Proibido: lógica de negócio de Skills, Agent Runtime, regras de
decisão do Policy Engine — o Tool Router assume que a chamada já foi
autorizada; ele não decide autorização, só executa o que já foi decidido.

## Documentos relacionados

- Contrato normativo completo: [architecture-contracts.md §9](architecture-contracts.md#9-tool--mcp-boundary)
- Limites do MCP Client: [architecture-contracts.md §3.8](architecture-contracts.md#38-mcp-client)
- Limites do Tool Router: [architecture-contracts.md §3.7](architecture-contracts.md#37-tool-router)
- Distinção Skill/Tool/MCP: [ADR-0005](adr/0005-skill-tool-mcp-distinction.md)
- Skill Contract: [skills.md](skills.md)
- Visão geral: [architecture.md](architecture.md)
