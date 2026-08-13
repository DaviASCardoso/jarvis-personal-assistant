# Skills

> **Documentação de implementação**: descreve o Skill Framework que existe em
> `src/jarvis/skills/` desde a Fase 5. Até a Fase 4 este documento era
> conceitual; agora descreve código real.
>
> Contrato normativo: [`architecture-contracts.md §8`](architecture-contracts.md#8-skill-contract),
> [ADR-0005](adr/0005-skill-tool-mcp-distinction.md) e
> [ADR-0016](adr/0016-action-execution-orchestrator.md). Para Tools, Tool Router
> e MCP, ver [mcp.md](mcp.md); para o Policy Engine, [security.md](security.md).

## O que existe

```text
src/jarvis/skills/
├── skill.py      # SkillDescriptor, SkillInvocation, SkillOutput, SkillHandler, Skill
├── registry.py   # SkillRegistry
├── errors.py     # SkillError, SkillInputError, SkillExecutionError, UnknownSkillError
└── builtin/      # system.status, file.read, file.list, file.write
```

Este pacote **não** importa `jarvis.policy.engine`, `jarvis.agent` nem
`jarvis.tools.adapters`. Ele toca `jarvis.policy.vocabulary` (o vocabulário de
risco) e `jarvis.tools` (o contrato de Tool) — e nada além disso. Um teste
arquitetural verifica cada uma dessas ausências.

## Skill ≠ Tool: por que a distinção existe

| Conceito | O que é | Onde mora risco/permissão? |
|---|---|---|
| **Tool** | capacidade atômica, stateless, schema fixo (`fs.write_text`). ~1:1 com uma tool MCP | não aqui |
| **MCP Server** | processo externo que expõe Tools — detalhe de onde a Tool mora | não aqui |
| **MCP Tool** | representação de wire-level de uma Tool | não aqui |
| **Skill** | capacidade que o agente decide invocar; pode compor várias Tools | **aqui** |

`ToolDescriptor` **não tem campo de risco**, e a ausência é deliberada: se
tivesse, a primeira Tool a se declarar inofensiva teria criado um segundo lugar
onde autorização parece morar.

## O descritor

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SkillDescriptor:
    name: str  # slug; mesmo padrão de ActionProposal.skill
    summary: str  # vai para o envelope do LLM
    parameters: ParameterSchema
    capabilities: frozenset[str]  # exigidas, ex. {"file:write"}
    required_tools: tuple[ToolId, ...]  # o teto do ToolAccess
    risk: RiskLevel  # none < low < medium < high < critical
    effects: frozenset[Effect]  # read/write/destructive/physical/…
    confirmation_requirement: ConfirmationRequirement
    idempotency: Idempotency  # safe | unsafe
    version: int = 1
```

Duas grandezas de risco, e não uma. `RiskLevel` é escalar e ordenado ("quão
perigoso?"); `Effect` é categórico ("perigoso *como*?"). `PHASE-5.md §32` pede
distinguir leitura, alteração, ação destrutiva, ação física e comunicação
externa — e um escalar não expressa isso: `start_print` e `delete_file` podem ser
igualmente arriscados e ainda merecer políticas diferentes.

`RiskLevel` compara por `at_least()`, nunca por `>=`: `StrEnum` compara como
texto, e alfabeticamente `critical < low`.

### `risk` não concede autorização

Regra sem exceção, herdada do [ADR-0003](adr/0003-policy-engine-safety-authority.md):
`risk`, `effects` e `confirmation_requirement` são **autodeclarações**. Elas são
insumo para o Policy Engine, que pode divergir — uma Skill que se declare
inofensiva e esteja na denylist continua negada.

## O que um handler recebe (e o que não recebe)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SkillInvocation:
    execution_id: str
    correlation_id: str
    parameters: Mapping[str, JsonValue]  # já validados
    tools: ToolAccess  # escopado, só chega após approval
    now: datetime
```

Três ausências valem mais que qualquer comentário sobre segurança:

- **sem `PolicyEngine`** — não há como se autorizar;
- **sem `ToolRouter`** — o que chega é `ToolAccess`, limitado às tools declaradas
  e construído só depois de uma `PolicyApproval` consumida ([ADR-0016](adr/0016-action-execution-orchestrator.md));
- **sem Context e sem Memory** — `architecture-contracts.md §3.6` manda que
  cheguem como parâmetro explícito; a Skill nunca os busca.

`SkillOutput.summary` é texto **seguro para o usuário**: uma frase sobre o que
aconteceu, não o conteúdo do que foi lido. `SkillOutput.data` carrega o resultado
estruturado e não vai para log nem para evento.

## Validação de parâmetros

`PHASE-5.md §27`: "o LLM não é confiável como validador; validação deve ocorrer
em código". O validador é `ParameterSchema` (em `jarvis/tools/schema.py`,
compartilhado com Tools) e rejeita campo desconhecido por padrão, tipo errado,
obrigatório ausente, valor fora de faixa e string fora do padrão.

Há **três** barreiras independentes, e a redundância é de propósito:

| barreira | onde | o que garante |
|---|---|---|
| schema da Skill | executor, antes da política | o formato é o declarado |
| regra de negócio | handler | ex. "o caminho precisa ser relativo" |
| schema da Tool | Tool Router, antes do dispatch | o contrato técnico do backend |

Uma delas afrouxada por engano não abre o caminho inteiro.

## O registry

Registro **explícito**, feito pelo composition root (`register_builtin_skills`).
Não há varredura de módulos nem entry points: descobrir capacidades importando
código arbitrário é superfície de ataque e efeito colateral em import, e nada
disso se paga com quatro Skills.

O registry serve às duas pontas da mesma garantia (`PHASE-5.md §26`): decide o
que o modelo **vê** (a lista de capacidades no envelope) e o que o executor
**aceita** (um nome fora daqui vira negação auditada). Um nome inventado não vira
execução em nenhum dos dois caminhos.

O registry **não** devolve tipos do Agent Runtime. Quem traduz `SkillDescriptor`
em `Capability` é `cli.capabilities_from()` — é o que mantém `jarvis.skills` sem
dependência de `jarvis.agent`.

O padrão de nome é duplicado entre `skills/skill.py` e `agent/decision.py`
(os pacotes não podem se importar). `tests/test_skill_registry.py` amarra os
dois: o que o agente consegue propor, o registry consegue registrar.

## O catálogo inicial

| Skill | Tool | capacidade | risco | efeitos | confirmação | idempotência |
|---|---|---|---|---|---|---|
| `system.status` | `local:system.info` | `system:read` | `none` | read | never | safe |
| `file.list` | `local:fs.list_dir` | `file:read` | `low` | read | never | safe |
| `file.read` | `local:fs.read_text` | `file:read` | `low` | read | never | safe |
| `file.write` | `local:fs.write_text` | `file:write` | `medium` | write | conditional | unsafe |

Quatro Skills locais — as únicas que dão execução real de ponta a ponta **sem**
integração externa. Elas cobrem os dois lados da política: leitura passa direto;
escrita pede confirmação quando a ação foi disparada por um evento em vez de
pedida pelo usuário (`conditional`).

Nenhuma Skill genérica do tipo `execute_anything` (`PHASE-5.md §33`): cada uma
declara exatamente uma ferramenta, e o `ToolAccess` recusa o resto.

**Calendar e Email não existem** — exigiriam OAuth e integração externa,
explicitamente fora do escopo da Fase 5. A arquitetura as suporta: um MCP Server
de Gmail ou Calendar registrado em `mcp.json` expõe tools novas sem uma linha de
código no Core. Ver `docs/phase-5-plan.md §33` (V-1).

## Ciclo de execução

```text
lookup → validação de schema → política → aprovação consumida
       → ToolAccess recortado → handler → tools → auditoria → outcome
```

Cada seta é uma barreira, e cada barreira tem um teste em
`tests/test_action_security.py`. Quem percorre a cadeia é o `ActionExecutor`
(`jarvis/execution/`), nunca a Skill nem o agente.

## Erros

`SkillError` (domínio) tem duas subclasses úteis: `SkillInputError` para regra de
negócio violada e `SkillExecutionError` para "tentei e não consegui". Falha de
infraestrutura sobe como `ToolError` do router e **não** é achatada — a diferença
entre "o pedido está errado" e "o mundo lá fora falhou" é o que o Agent Runtime
precisa para decidir o que dizer ao usuário.

Nenhuma mensagem de erro carrega parâmetro, conteúdo de arquivo ou resultado de
tool (`tests/test_action_privacy.py`).

## Como acrescentar uma Skill

1. Escreva o handler em `skills/builtin/` (ou num módulo próprio): Core puro,
   sem `pathlib`, compondo chamadas via `invocation.tools`.
2. Declare o `SkillDescriptor` — inclusive `required_tools`, que vira o teto do
   `ToolAccess`.
3. Registre em `register_builtin_skills`.
4. Conceda a capacidade em `JARVIS_POLICY_GRANTED_CAPABILITIES`. Sem isso, a
   política nega — o default é restritivo de propósito.

Se a tool declarada não existir no `ToolRegistry`, o Policy Engine nega com
`required_tool_unavailable` **antes** de executar, em vez de a Skill falhar no
meio com metade dos efeitos já produzidos.

## Comandos de CLI

```bash
jarvis skills list       # nome, risco, efeitos, capacidades, tools e schema
```

## Documentos relacionados

- Tools, Tool Router e MCP: [mcp.md](mcp.md)
- Policy Engine e confirmação: [security.md](security.md)
- Contrato normativo: [architecture-contracts.md §8](architecture-contracts.md#8-skill-contract)
- Distinção Skill/Tool/MCP: [ADR-0005](adr/0005-skill-tool-mcp-distinction.md)
- Orquestrador e `ToolAccess`: [ADR-0016](adr/0016-action-execution-orchestrator.md)
- Plano da fase: [phase-5-plan.md](phase-5-plan.md)
