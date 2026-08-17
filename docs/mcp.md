# Tools, Tool Router e MCP

> **Documentação de implementação**: descreve a camada de Tools que existe em
> `src/jarvis/tools/` desde a Fase 5 — contrato de `Tool`, roteamento, registry,
> backend local e cliente MCP. Até a Fase 4 este documento era conceitual.
>
> Contrato normativo: [`architecture-contracts.md §9`](architecture-contracts.md#9-tool--mcp-boundary),
> [ADR-0005](adr/0005-skill-tool-mcp-distinction.md) e
> [ADR-0015](adr/0015-stdlib-stdio-mcp-client.md). Para Skills, ver
> [skills.md](skills.md).

## O que existe

```text
src/jarvis/tools/
├── tool.py       # ToolId, ToolDescriptor, ToolCall, ToolResult
├── schema.py     # FieldSpec, ParameterSchema, parameters_fingerprint, from_json_schema
├── errors.py     # a taxonomia ToolError
├── ports.py      # ToolBackend (Protocol)
├── registry.py   # ToolRegistry, BackendStatus
├── router.py     # ToolRouter, ToolRetryPolicy
├── access.py     # ToolAccess
└── adapters/
    ├── local_backend.py    # fs.read_text, fs.write_text, fs.list_dir, system.info
    ├── computer_backend.py # list_processes, focus_window, open_app, close_app, run_command (Fase 8.2)
    ├── mcp_config.py       # mcp.json, ambiente mínimo do processo filho
    ├── mcp_protocol.py     # JSON-RPC 2.0, handshake, tradução de schema e resultado
    ├── mcp_stdio.py        # transporte: subprocesso + thread leitora
    └── mcp_client.py       # McpToolBackend
```

`ComputerToolBackend` (Fase 8.2) é mais um `ToolBackend`, ao lado do local e
do MCP — nenhum contrato novo, mesmo port. Ver
[`computer.md`](computer.md) para o que ele expõe e
[ADR-0031](adr/0031-command-allowlist-execution-model.md) para o modelo de
allowlist que `open_app`/`run_command` exigem.

Este pacote **não** importa `jarvis.policy` nem `jarvis.skills`. O router assume
que a chamada já foi autorizada; quem torna essa suposição verdadeira é o
`ToolAccess`.

## O contrato de Tool

```python
type ToolId = str  # "backend:nome"


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDescriptor:
    tool_id: ToolId
    backend_id: str
    name: str
    summary: str
    parameters: ParameterSchema
    supports_idempotency_key: bool = False
```

`ToolId` é qualificado por backend (`local:fs.read_text`, `workspace:search`), o
que resolve colisão entre servidores por construção — dois MCP Servers podem
expor `search` sem que o registry precise arbitrar.

O **nome** aceita maiúsculas e `_` porque não é nosso: um servidor externo expõe
`read_file` ou `getStatus`, e recusar a tool por causa da convenção dele seria
rejeitar a integração inteira. O `backend_id`, esse sim, é escolhido por nós e
continua em minúsculas.

`ToolResult` só descreve **sucesso**. Falha é exceção da família `ToolError` —
não um campo `ok` que alguém esquece de checar, que é a forma mais comum de uma
falha virar sucesso silencioso.

## O Tool Router

Ponto único de estrangulamento (`architecture-contracts.md §9`), na ordem em que
as coisas acontecem:

1. **resolve** o `tool_id` no registry (ausente ⇒ `ToolNotFoundError`);
2. **valida** os parâmetros contra o schema anunciado, imediatamente antes do
   dispatch e independentemente da validação de negócio da Skill — concerns
   diferentes, não redundância;
3. **aplica timeout** por chamada;
4. **executa** via `ToolBackend`;
5. **normaliza** toda falha para `ToolError`. Nenhum erro de JSON-RPC,
   `subprocess` ou `OSError` cru chega à Skill. Um adapter que deixa escapar
   exceção nativa tem bug: o router o converte em `ToolExecutionError` e registra
   o stack trace completo no log, para quem for consertar;
6. **registra** a execução — aqui, num lugar só. Skills não implementam log
   próprio.

O router **não** decide autorização e não conhece `jarvis.policy`.

### Retry: duas condições, e as duas precisam valer

O router repete apenas se o erro se declara `retryable` **e** a execução foi
declarada `Idempotency.SAFE` pela Skill. Um timeout numa operação `unsafe` nunca
é repetido — timeout não prova que a operação não aconteceu do outro lado
(`PHASE-5.md §19`).

## `ToolAccess`: menor privilégio por execução

Uma Skill não recebe o router. Recebe um objeto amarrado a uma execução e
limitado às tools que ela própria declarou em `required_tools`, construído apenas
em `jarvis/execution` e apenas depois de uma `PolicyApproval` consumida.

Uma Skill de leitura que tentasse chamar uma tool de escrita é recusada com
`ToolNotPermittedError` — que é um `PolicyDenied` — antes de o router entrar na
jogada, mesmo com aprovação válida em mãos.

## O registry

`ToolRegistry` mantém `ToolId → (backend, descriptor)`, construído por
`refresh()` sobre os backends registrados. É **cache do ambiente, não fonte de
verdade do domínio** (`PHASE-5.md §25`): vive em memória, é refeito a cada
processo, e não é persistido — cache de catálogo só se justificaria com custo de
descoberta medido, e não há.

Um backend que falha na descoberta **não derruba o processo**: fica registrado
como degradado, aparece assim em `jarvis tools list`, e uma Skill que dependa de
uma tool ausente é negada pelo Policy Engine com `required_tool_unavailable`.

## Backend local

`local:` expõe quatro tools sobre o workspace (`JARVIS_FILE_SKILL_ROOT`, default
`data/workspace`): `fs.read_text`, `fs.write_text`, `fs.list_dir`, `system.info`.

Existe por duas razões, e a segunda é arquitetural: dá execução real de ponta a
ponta sem processo externo, e é a prova executável de que o contrato de `Tool`
**não** é o formato de wire do MCP disfarçado. Se só existisse o backend MCP,
`ToolDescriptor` acabaria virando um espelho do protocolo sem que ninguém
percebesse.

É o único lugar da camada de ação que toca `pathlib` e `platform`. A raiz
allowlistada é imposta **aqui**, não pela política — barreiras independentes:
mesmo que uma regra de política seja afrouxada por engano, um caminho fora da
raiz continua recusado. A checagem acontece **depois** de `resolve()`, e não
sobre o texto, porque é assim que um symlink apontando para fora é pego.

`system.info` reporta OS, versão de Python, contagem de CPUs e espaço livre —
**não** hostname, usuário nem variáveis de ambiente. O resultado de uma Skill
pode acabar num prompt enviado a um serviço de nuvem.

## Cliente MCP

Próprio, síncrono, sobre stdio + JSON-RPC 2.0, usando apenas a stdlib
([ADR-0015](adr/0015-stdlib-stdio-mcp-client.md)). Quatro mensagens:
`initialize`, `notifications/initialized`, `tools/list`, `tools/call`.

### Ciclo de vida

```text
construir            → nada acontece
discover()/invoke()  → conecta (Popen → initialize → notifications/initialized)
                     → tools/list  |  tools/call
falha de transporte  → encerra o processo e marca desconectado
próxima chamada      → tenta reconectar uma vez
```

Não há laço de reconexão em background: não existe daemon nesta fase para
hospedá-lo, e uma thread que reconecta sozinha seria infraestrutura sem dono.

Três detalhes de portabilidade que não são óbvios:

- **thread leitora + `queue`, nunca `select`** — `selectors` não funciona sobre
  pipes no Windows, e o projeto é desenvolvido em Windows e testado em Linux;
- **`stderr=DEVNULL`** — capturar exigiria uma segunda thread para não travar o
  pipe, e o que viesse de lá acabaria em log, inclusive o que um servidor
  mal-comportado imprimir sobre a própria credencial;
- **UTF-8 forçado nas duas pontas** (`errors="replace"` na leitura,
  `PYTHONIOENCODING=utf-8` no filho) — MCP é UTF-8 no fio, mas o padrão de um
  processo Python no Windows ainda é a codificação do console. Sem isso, um acento
  na descrição de uma tool derruba a thread leitora e o sintoma aparece como "o
  servidor sumiu".

### Configuração e fronteira de secrets

`mcp.json`, caminho em `JARVIS_MCP_CONFIG`. Ausente = nenhum MCP Server, e todo o
resto do sistema continua funcionando.

```json
{
  "servers": {
    "workspace": {
      "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./data/workspace"],
      "enabled": true,
      "timeout_seconds": 20,
      "startup_timeout_seconds": 10,
      "env_keys": ["WORKSPACE_TOKEN"]
    }
  }
}
```

**`env_keys` nomeia variáveis; nunca contém valores.** Os valores são lidos do
ambiente do processo pai na hora de iniciar o filho. O arquivo é versionável sem
risco.

O ambiente do filho é **explícito e mínimo**: `PATH`, o mínimo que o sistema
operacional exige, `PYTHONIOENCODING=utf-8` e as chaves pedidas. Não é
`os.environ` inteiro — um MCP Server não tem por que herdar
`JARVIS_GEMINI_API_KEY` só porque estava lá.

### Normalização de resultado

| Resposta MCP | Vira |
|---|---|
| `isError: true` | `ToolExecutionError` com o texto do bloco |
| `structuredContent` presente | `ToolResult.data = structuredContent` |
| só `content: [{type:"text"}]` | `data = {"text": ...}`, `message` = texto |
| bloco não textual | `[conteúdo <tipo> omitido]` — binário não trafega nesta fase |
| `error` JSON-RPC `-32601` / `-32602` | `ToolNotFoundError` / `ToolInvalidInputError` |
| outro `error` | `ToolExecutionError` |
| corpo não-JSON, `id` divergente, EOF | `ToolProtocolError` |
| deadline estourado | `ToolTimeoutError` |

### Tradução de schema, e o que ela admite não validar

`from_json_schema` traduz um subconjunto documentado (`type`, `properties`,
`required`, `enum`, `minimum`, `maximum`, `maxLength`, `pattern`,
`additionalProperties`). O que não entende **não valida, e declara que não
validou**: a palavra-chave ignorada vai para `ignored_keywords`, visível em
`jarvis tools list --schemas`. Fingir ter validado `allOf` ou `$ref` seria pior
que não validar, porque produziria confiança sem cobertura.

Um nome de tool impossível de qualificar como `ToolId` é **pulado**, não fatal: o
resto do servidor continua utilizável.

## Erros

```text
domínio     ToolNotFoundError · ToolInvalidInputError · ToolConfigurationError
            ToolNotPermittedError (é PolicyDenied)
provider    ToolTimeoutError (retryable) · ToolUnavailableError (retryable)
            ToolExecutionError · ToolProtocolError (permanentes)
```

`ToolError` é o marcador comum, herdado junto com a categoria do contrato §13 —
a herança dupla existe para que `except ToolError` capture a camada inteira e
`retryable` continue vindo da categoria certa.

## Testes sem serviço externo

`tests/mcp_fake_server.py` é um MCP Server mínimo e determinístico, executado
como `sys.executable -m tests.mcp_fake_server`. Ele exercita o caminho completo
— `Popen`, thread leitora, framing, handshake, encerramento — sem rede, sem
credencial e sem instalar nada, em Windows e em Linux. Suas tools existem para
provocar cada ramo: `echo`, `fail`, `slow`, `garbage`, `Weird-Name`.

O protocolo também é testado como função pura, e o cliente contra um
`FakeTransport` em memória.

## Comandos de CLI

```bash
jarvis tools list             # backends, estado e tools descobertas
jarvis tools list --schemas   # + schema de entrada e o que não foi validado
```

## Documentos relacionados

- Skills e o que elas declaram: [skills.md](skills.md)
- Policy Engine: [security.md](security.md)
- Contrato normativo: [architecture-contracts.md §9](architecture-contracts.md#9-tool--mcp-boundary)
- Cliente MCP: [ADR-0015](adr/0015-stdlib-stdio-mcp-client.md)
- Plano da fase: [phase-5-plan.md](phase-5-plan.md)
