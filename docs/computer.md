# Contexto e controle do computador

> **Documentação de implementação**: descreve o que existe em
> `src/jarvis/context/adapters/{window_activity,resource_usage,
> process_activity}_provider.py`, `src/jarvis/tools/adapters/
> computer_backend.py` e `src/jarvis/skills/builtin/computer.py` desde a
> Fase 8. Contratos normativos ficam em
> [`architecture-contracts.md §3.2/§3.6/§3.7`](architecture-contracts.md);
> as decisões, nos [ADR-0030](adr/0030-psutil-as-a-normal-dependency.md) e
> [ADR-0031](adr/0031-command-allowlist-execution-model.md).

---

## 1. O que a Fase 8 acrescenta

Duas peças, e a distinção entre elas é a mesma que separa **observar** de
**agir** em todo o resto do projeto:

- **Computer Context** (8.1) — três `ContextProvider` (mesmo port da Fase 2)
  que observam aplicação/janela ativa, CPU/RAM/GPU/rede/ociosidade e
  processos relevantes. Só leem; nunca agem.
- **Computer Skill** (8.2) — `ComputerToolBackend` (mesmo `ToolBackend` port
  da Fase 5) + cinco Skills que **agem**: listar processos, focar janela,
  abrir/fechar aplicativo, executar comando. Passam pela mesma cadeia
  Policy → Skill → Tool → Backend de qualquer outra Skill — nenhum caminho
  novo de Agent Runtime direto ao sistema operacional.

```text
Computer Context:  SO → Provider → ContextUpdate → Context Engine
Computer Skill:    Skill → ToolAccess → Tool Router → ComputerToolBackend → SO
```

---

## 2. Computer Context (8.1)

| Provider | Campos | Mecanismo |
|---|---|---|
| `WindowActivityProvider` | `active_application`, `active_window_title` | `ctypes` (Windows-only) |
| `ResourceUsageProvider` | `cpu_percent`, `memory_percent`, `gpu_percent`, `network_connected`, `idle_seconds` | `psutil` (multiplataforma) + `ctypes`/PowerShell (Windows-only) |
| `ProcessActivityProvider` | `relevant_process_count` | `psutil`, filtrado por `JARVIS_COMPUTER_RELEVANT_PROCESSES` |

Oito campos novos em `ContextField`, todos com TTL curto (30s para métricas
de CPU/RAM/GPU/ociosidade; 2min para janela/processos; 5min para rede) — os
mesmos que qualquer outro campo de contexto: `Observation` com proveniência,
freshness computada na leitura, nunca armazenada.

**Cada leitura é independente e tolerante a falha individual.** Perder GPU
não derruba CPU; perder janela ativa fora do Windows não derruba nada — vira
ausência, nunca um valor inventado, mesma disciplina que a Fase 2 já aplicou
a Location. `ProcessActivityProvider` com a allowlist vazia (o default)
nunca observa nada — ausência, não zero.

**GPU é melhor esforço.** Usa `Get-Counter` do PowerShell sobre
`\GPU Engine(*)\Utilization Percentage` (Windows 10 1803+), sem SDK de
vendor. Nem todo driver publica o contador; quando não publica, o campo fica
ausente.

**Fora do Windows**, `WindowActivityProvider` e as partes Windows-only de
`ResourceUsageProvider` (ociosidade, GPU) degradam para ausência silenciosa
— CPU/RAM/rede continuam funcionando via `psutil`, que é multiplataforma.

---

## 3. Computer Skill (8.2)

| Skill | Tool | Capacidade | Risco | Efeito | Confirmação |
|---|---|---|---|---|---|
| `computer.list_processes` | `computer:list_processes` | `computer:read` | `none` | leitura | nunca |
| `computer.focus_window` | `computer:focus_window` | `computer:read` | `low` | escrita | nunca |
| `computer.open_app` | `computer:open_app` | `computer:open` | `medium` | físico | sempre* |
| `computer.close_app` | `computer:close_app` | `computer:close` | `high` | destrutivo | sempre |
| `computer.run_command` | `computer:run_command` | `computer:run` | `high` | destrutivo | sempre |

\* `open_app` declara confirmação `conditional`, mas o efeito `physical`
está em `DEFAULT_CONFIRM_EFFECTS` — na prática, sempre pede confirmação,
pedida pelo usuário ou não.

**Nenhuma das quatro capacidades (`computer:read/open/close/run`) está na
allowlist default de `JARVIS_POLICY_GRANTED_CAPABILITIES`.** As cinco Skills
continuam negadas assim que registradas, até configuração explícita — mesmo
critério que já protege `file.write` desde a Fase 5. Ver
[`security.md`](security.md) para o modelo de permissão completo (não
recriado nesta fase, só estendido).

### Decisões de escopo, documentadas e não silenciosas

- **"Interagir com interface"** — escopo restrito a **janela** (focar,
  listar), não simulação de mouse/teclado. Automação de UI de propósito
  geral é a superfície de risco mais alta que o projeto poderia ter — um
  agente que clica em qualquer lugar da tela — e nenhum item concreto do
  roadmap pede isso além da frase genérica.
- **"Ler tela quando apropriado"** — escopo restrito à **identidade** da
  janela ativa (aplicação + título, já entregue por 8.1), não captura de
  pixels/OCR.

---

## 4. Allowlist de comandos

`computer.open_app` e `computer.run_command` **nunca** aceitam um comando
como texto ou uma lista de argumentos do chamador. Os dois só aceitam um
`name` curto, que precisa bater com uma chave de
`JARVIS_COMPUTER_COMMAND_ALLOWLIST_PATH` — um JSON `nome → argv`:

```json
{
  "notepad": ["notepad.exe"],
  "dir": ["cmd", "/c", "dir"]
}
```

Sem o arquivo configurado (o default), as duas Skills continuam registradas
— visíveis em `jarvis skills list` — mas todo `name` é recusado. Nunca
`shell=True`, nunca concatenação de texto: ver
[ADR-0031](adr/0031-command-allowlist-execution-model.md) para o raciocínio
completo e as alternativas descartadas.

`computer.close_app` não usa allowlist — opera sobre processos **já em
execução** (correspondência por substring do nome), não lança processo
novo. Exclui por `pid` o próprio processo do Jarvis, para que um
`application` que bata com o nome do interpretador (`python`/`pythonw`)
nunca o encerre (achado da revisão de segurança da 8.8).

---

## 5. Configuração

```bash
JARVIS_COMPUTER_RELEVANT_PROCESSES=slicer.exe,camera_app.exe
JARVIS_COMPUTER_COMMAND_ALLOWLIST_PATH=./config/computer-commands.json
JARVIS_POLICY_GRANTED_CAPABILITIES=system:read,file:read,file:write,computer:read
```

Vazio/ausente em qualquer um dos três = a capacidade correspondente
simplesmente não existe em prática, sem erro — mesmo critério de
`policy_granted_capabilities`/`mcp_config_path`/`proactivity_rules_path`.

---

## 6. Comandos

```bash
jarvis context show                    # inclui os oito campos novos, se observados
jarvis skills list                     # mostra as cinco, com risco/efeitos/capacidades
jarvis action run --skill computer.list_processes
jarvis audit show <correlation_id>     # decisão + trilha de uma execução (8.4)
```

---

## 7. Limitações conhecidas

- **Janela ativa, ociosidade e GPU são Windows-only.** Fora do Windows,
  ausência silenciosa — o resto do sistema continua funcionando.
- **`computer.close_app` casa por substring do nome do processo**, não por
  identidade exata: `application="chrome"` também encerra
  `chrome_installer.exe` se ele estiver rodando. Documentado, não
  escondido — o risco `high` + confirmação `always` existem exatamente por
  isso.
- **Sem automação de interface genérica** (mouse/teclado) e **sem
  captura de tela/OCR** — decisões de escopo da 8.2, não lacunas.
- **GPU depende do driver publicar o contador do Windows** — quando não
  publica, o campo fica ausente, nunca um número inventado.
