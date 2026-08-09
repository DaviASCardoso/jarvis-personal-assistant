# 0005. Distinção entre Skill, Tool, MCP Server e MCP Tool

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

O `ROADMAP.md` usa os termos Skill, Tool e MCP em fases diferentes (5.1
Skill Framework, 5.3 Tool Abstraction, 5.4 MCP Client) sem definir a
fronteira entre eles. Sem essa definição, é fácil que "Skill" vire apenas um
sinônimo de "função que chama uma tool MCP" — o que colapsaria justamente o
lugar onde risco, permissão e política de confirmação deveriam viver (ver
[ADR-0003](0003-policy-engine-safety-authority.md)) dentro de uma simples
chamada de função, sem espaço para essas semânticas.

## Decisão

Quatro conceitos distintos, cada um com uma responsabilidade própria:

- **Tool**: capacidade atômica, stateless, com schema fixo de entrada/saída
  (ex. `send_email(to, subject, body)`). Corresponde ~1:1 a uma tool MCP.
- **MCP Server**: processo externo que expõe uma ou mais Tools via
  protocolo MCP — detalhe de implementação de onde uma Tool mora,
  irrelevante para quem consome a Tool.
- **MCP Tool**: representação de wire-level de uma Tool, como descoberta via
  protocolo MCP. Traduzida para o contrato interno de `Tool` pelo Tool
  Router/MCP Client.
- **Skill**: capacidade de nível mais alto que o agente decide invocar —
  pode compor múltiplas Tools, e carrega validação de input, classificação
  de risco e política de confirmação **próprias**. Skill não é sinônimo de
  função: é o lugar onde moram as semânticas de risco/permissão/confirmação,
  mesmo quando envolve tecnicamente só uma Tool.

Uma consequência direta: `risk` e `confirmation_requirement` são atributos
de **Skill**, nunca de Tool ou de MCP Server — Tools são "o que pode ser
feito tecnicamente"; Skills são "o que o agente está autorizado/deveria
decidir fazer, e sob qual condição". Essas declarações da Skill, por sua
vez, não concedem autorização — ver
[ADR-0003](0003-policy-engine-safety-authority.md).

Detalhamento em
[`architecture-contracts.md §8`](../architecture-contracts.md#8-skill-contract).

## Alternativas consideradas

- **Skill = wrapper fino de uma Tool MCP** (1:1, sem camada própria):
  descartada — não sobraria lugar natural para risco/permissão/confirmação
  sem empurrar essa responsabilidade para o Tool Router ou para o Policy
  Engine conhecerem detalhes de cada Tool individualmente, o que violaria os
  limites definidos em `architecture-contracts.md §3.7` (Tool Router não
  deve conhecer regras de negócio de Skills).
- **Sem distinção entre Tool e MCP Tool** (tratar o formato MCP como o
  próprio contrato interno de Tool): descartada — acoplaria todo o sistema
  ao formato de wire do MCP; um backend de tool futuro que não seja MCP
  exigiria reescrever o contrato inteiro em vez de só um novo adapter.

## Consequências

- Uma Skill pode compor múltiplas Tools (potencialmente de MCP Servers
  diferentes) sob uma única política de risco/confirmação coerente.
- Trocar o backend de uma Tool (de um MCP Server para outro, ou para um
  backend não-MCP no futuro) não exige tocar na Skill que a usa.
- Adiciona uma camada de indireção (Skill → Tool Router → MCP) que uma
  chamada direta de função não teria — custo aceito em troca de ter um
  lugar único e consistente para risco/permissão.
- Não define, nesta fase, quantas Skills vão existir nem seu catálogo
  inicial — isso é escopo da Fase 5.
