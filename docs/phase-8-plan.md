# Fase 8 — Integration + Hardening: plano de implementação

> Cobre o que `ROADMAP.md` define para a Fase 8 (§8.1–8.10). O
> `phase-8-development-guide.md` anexado à sessão que originou este plano é
> compatível em espírito (watchers de sistema, integração com o SO,
> hardening, observabilidade, segurança) e foi usado como leitura de apoio,
> mas `ROADMAP.md` continua sendo a fonte oficial de escopo — nenhum item
> deste plano vem do anexo sem also estar no roadmap.

**Objetivo da fase:** conectar o Jarvis ao computador onde ele roda e
fortalecer a confiabilidade do que já existe. **Nenhuma capacidade
cognitiva nova.** Nenhum dos oito componentes já implementados (Event
System, Context Engine, Memory System, Agent Runtime, Policy Engine, Skill
Framework, Tool Router + MCP, Voice/Painel, Proatividade) é reescrito —
Fase 8 estende exatamente os pontos que as fases anteriores já deixaram
marcados como "escopo de 8.1" (Activity/Location Provider, subfase 2.2;
"nada de automação do sistema operacional... isso é escopo da subfase 8.1",
`context/adapters/device_provider.py`).

## 0. Princípio geral

Toda capacidade nova desta fase entra **pelos mesmos pontos de extensão**
que as fases anteriores já definiram, nunca por um mecanismo paralelo:

- observação do computador → **mais Context Providers**, mesmo port
  `ContextProvider` de `SystemTimeProvider`/`LocalDeviceProvider` (2.2);
- ação sobre o computador → **mais Tools + mais Skills**, mesmo
  `ToolBackend`/`SkillDescriptor` de `LocalToolBackend`/`file.write` (5.3/5.6),
  passando pela mesma cadeia `Policy → Skill → Tool Router → Adapter`
  (contrato §9, ADR-0016) — **nunca** `Agent Runtime → Operating System`
  diretamente, como o guia anexado também exige;
- segurança e auditoria → o **mesmo** `PolicyEngine`/`AuditLog`/Event Store
  de sempre, com capacidades novas (`computer:*`) na mesma allowlist que já
  nega tudo por padrão.

Isso não é só estilo: `test_action_architecture.py` já falha se qualquer
módulo novo abrir um caminho `Skill → autoautorizar` ou construir
`ToolAccess` fora de `jarvis/execution`, e os testes correspondentes de
Context/Skills fazem o mesmo pela AST. Reutilizar os pontos de extensão é a
forma mais barata de continuar passando neles.

## 1. Subfases e o que cada uma entrega

### 8.1 — Computer Context

**Entrega:** `jarvis/context/model.py` ganha um oitavo subcontexto,
`ComputerContext`, com oito campos (`active_application`,
`active_window_title`, `cpu_percent`, `memory_percent`, `gpu_percent`,
`network_connected`, `idle_seconds`, `relevant_process_count`) — cada um um
`ContextField` novo, uma entrada em `ContextUpdate`, uma linha em
`iter_fields`, e um TTL próprio em `freshness.py` (nenhum reaproveita um TTL
existente: CPU/RAM/idle mudam em segundos, aplicação ativa em minutos, rede
em dezenas de minutos).

Três providers novos em `context/adapters/`, cada um seguindo o desenho
injetável de `LocalDeviceProvider(hostname: Callable[[], str] = platform.node)`
— nenhum lê API do SO por conta própria fora de um callable substituível,
o que é o que torna os testes determinísticos sem hardware nem SO real:

| Provider | Campos | Mecanismo (Windows) | Fora do Windows |
|---|---|---|---|
| `WindowActivityProvider` | `active_application`, `active_window_title` | `ctypes` (`GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId` + `psutil.Process(pid).name()`) | degrada (`ContextProviderError`, mesmo tratamento de falha que `ContextAggregator` já dá a qualquer provider) |
| `ResourceUsageProvider` | `cpu_percent`, `memory_percent`, `gpu_percent`, `network_connected`, `idle_seconds` | `psutil` para CPU/RAM/rede; `ctypes GetLastInputInfo` para ociosidade; GPU via `powershell Get-CimInstance Win32_VideoController` (comando fixo, sem interpolação — sem risco de injeção) | CPU/RAM/rede funcionam (psutil é multiplataforma); idle e GPU ausentes, honestamente |
| `ProcessActivityProvider` | `relevant_process_count` | `psutil.process_iter()` contra uma allowlist configurável (`JARVIS_COMPUTER_RELEVANT_PROCESSES`) | funciona igual (psutil) |

Nova dependência: **`psutil`**, como dependência normal (não um extra
opcional como `sounddevice`/voz) — não exige hardware nem driver, roda em
qualquer ambiente de CI, inclusive Linux. Justificada por ADR (§5).

**Decisões de escopo, honestas desde já:**

- GPU é **melhor esforço**: sem vendor SDK (NVIDIA/AMD), a única fonte
  multiplataforma-de-verdade não existe. Falha vira ausência, mesmo
  tratamento que a Fase 2 deu a Location.
- Sem GPU/idle fora do Windows, o campo fica ausente — não inventado. É a
  mesma disciplina do contrato §6 ("o Context Engine nunca infere").

### 8.2 — Computer Skill

**Entrega:** `jarvis/tools/adapters/computer_backend.py`
(`ComputerToolBackend`, `backend_id="computer"`) + `jarvis/skills/builtin/computer.py`
(cinco Skills), registradas em `register_builtin_skills` — mesmo padrão de
`LocalToolBackend`/`skills/builtin/files.py`.

| Skill | Tool | capacidade | risco | efeitos | confirmação |
|---|---|---|---|---|---|
| `computer.list_processes` | `computer:list_processes` | `computer:read` | `none` | read | never |
| `computer.focus_window` | `computer:focus_window` | `computer:read` | `low` | write | never |
| `computer.open_app` | `computer:open_app` | `computer:open` | `medium` | physical | conditional |
| `computer.close_app` | `computer:close_app` | `computer:close` | `high` | destructive | always |
| `computer.run_command` | `computer:run_command` | `computer:run` | `high` | destructive | always |

Como nenhuma dessas capacidades (`computer:*`) está na allowlist default de
`JARVIS_POLICY_GRANTED_CAPABILITIES`, **as cinco continuam negadas por
padrão** assim que registradas — mesmo mecanismo que já protege
`file.write` hoje, sem precisar de um interruptor novo (ver 8.3).

**`computer.run_command` nunca aceita comando arbitrário.** Só executa a
partir de um **template allowlistado** (`JARVIS_COMPUTER_COMMAND_ALLOWLIST`,
nome→`argv`), nunca `shell=True`, nunca concatenação de texto — o mesmo
espírito de `LocalToolBackend._resolve` recusar caminho fora da raiz antes
de tocar o disco. ADR próprio (§5).

**Decisões de escopo, documentadas e não silenciosas:**

- **"Interagir com interface"** — escopo restrito a operações de **janela**
  (focar, listar), não a simulação de mouse/teclado. Automação de UI de
  propósito geral (`pywinauto`/`pyautogui`) é a superfície de risco mais
  alta de todo o sistema — um agente que clica em qualquer lugar da tela —
  e nenhum item concreto do roadmap pede isso além da frase genérica.
  Registrado como decisão, não lacuna.
- **"Ler tela quando apropriado"** — escopo restrito a **identidade da
  janela ativa** (aplicação + título), já entregue por 8.1, não captura de
  pixels/OCR. Adicionar `Pillow` + GDI só se um caso de uso concreto exigir.

### 8.3 — Permission System

O modelo de permissão (capabilities, `RiskLevel`, `Effect`,
`ConfirmationRequirement`, allowlist, denylist) **já existe inteiro** desde
a Fase 5 (`jarvis/policy/`) — Fase 8 não recria nada. Esta subfase integra
as capacidades novas ao modelo existente e **prova** que a integração é
segura por padrão:

- `computer:read`/`computer:open`/`computer:close`/`computer:run` seguem o
  mesmo `require_capability` (`dominio:verbo`) de `system:read`/`file:write`.
- Teste novo, espelhando `test_action_security.py`: nenhuma das cinco
  Skills de computador executa sem capacidade concedida explicitamente —
  `capability_not_granted` nega as cinco com a configuração default.
- Teste novo: `computer.open_app`/`close_app`/`run_command`, mesmo com
  capacidade concedida, ainda pedem confirmação por efeito
  (`effect_requires_confirmation`, já que `PHYSICAL`/`DESTRUCTIVE` já
  entram em `DEFAULT_CONFIRM_EFFECTS`) — verificado, não presumido.
- `jarvis skills list` já mostra risco/efeitos/capacidades de qualquer
  Skill registrada — nenhuma mudança de CLI necessária para "integrar
  Skills". MCP já passa pelo mesmo `PolicyEngine` desde a Fase 5 — nada a
  integrar de novo.

### 8.4 — Audit Logging

A trilha de auditoria (`jarvis/audit.py`, 9 tipos de evento) e o Decision
Log (Fase 7.4) **já existem e já cobrem** ações, ferramentas, decisões,
confirmações e falhas. Esta subfase acrescenta a única lacuna real:
**consulta unificada**. Hoje decisão e execução são consultadas
separadamente (`jarvis decisions list` / `jarvis events list
--correlation-id`). Novo comando:

```bash
jarvis audit show <correlation_id>
```

Lê o **mesmo** Event Store, projeta decisão(ões)
(`jarvis.decisions.project_decisions`) e trilha de ação/ferramenta (mesma
lógica de agregação de `interface/service.py::_action_cards`, generalizada
para uso de CLI) numa timeline só, ordenada por `recorded_at`. Nenhum
armazenamento novo — leitura pura sobre dado que já existe.

### 8.5 — Behavioral Evaluation

`tests/test_behavioral_evaluation.py`, um cenário por item do roadmap,
todos com componentes reais (Context/Memory/Execution de verdade, só o LLM
como `StubLLMProvider` — mesmo padrão de `test_agent_integration.py` e
`test_proactivity_integration.py`):

| Cenário do roadmap | Como é exercitado |
|---|---|
| Email importante durante foco | `EventTrigger` (`event_type="email.received"`) + contexto `activity=focus`/`availability=busy` + memória de alta relevância — mostra a troca entre `interruption_cost` alto e `personal_relevance` alto |
| Email irrelevante | mesmo tipo de evento, sem memória relevante, `context` neutro — abaixo do limiar, LLM nunca chamado |
| Reunião próxima | `schedule.next_entry_at` a ≤15 min — `urgency=1.0`, sempre raciocina |
| Solicitação para enviar email | como nenhuma Skill de e-mail existe (fora de escopo em todas as fases — `skills.md`), o cenário fiel é "o modelo propõe uma skill que não existe" → `ActionExecutor` nega com `skill_not_registered`, nunca finge sucesso. Documentado como adaptação fiel, não substituição silenciosa |
| Falha de ferramenta | `Skill` cujo `ToolAccess.call` estoura `ToolExecutionError` — `ActionExecutor` devolve `FAILED`, audita, não derruba o processo |
| Memórias contraditórias | duas `PREFERENCE` com o mesmo `subject`, conteúdo diferente — retrieval só devolve a vigente (supersessão da Fase 3) |
| Mudança de preferência | `remember` de uma preferência nova sobre uma existente — a antiga fecha `valid_until`, a nova vigora, o próximo prompt reflete só a atual |
| Silêncio apropriado | importância abaixo do limiar — `Decision.ignore`, sem LLM, sem notificação, sem ação |

### 8.6 — Failure + Recovery

`tests/test_failure_recovery.py`, um teste nomeado por cenário do roadmap.
Onde a cobertura já existe em profundidade num teste de unidade (ex. evento
duplicado em `test_events_sqlite_store.py`), o teste aqui é uma prova de
**integração curta** que aponta para a cobertura de unidade em vez de
duplicá-la — o arquivo existe para que os dez nomes do roadmap apareçam
juntos e sejam auditáveis de uma vez, não para reescrever suítes inteiras:

LLM indisponível · banco indisponível · MCP indisponível · timeout · evento
duplicado · evento fora de ordem · contexto desatualizado · falha de tool ·
processo reiniciado (Event Store/Context/Memory reabertos de um arquivo
SQLite existente, não `:memory:`) · recuperação após crash (`PendingAction`
presa em `running` bloqueia reexecução via `blocks_reexecution`, e
`jarvis action pending`/`show` continuam honestos sobre o estado).

### 8.7 — Performance

`scripts/benchmark.py` (fora da suíte pytest — evita flakiness de CI por
tempo de execução), medindo com o mesmo método do ADR-0009: retrieval de
memória (N sintéticas, cosseno exato), construção de contexto
(`ContextAggregator.refresh` com os providers da 8.1 dublados),
`parse_decision` (custo de interpretar uma resposta do modelo). Um teste
leve em `tests/test_performance_benchmarks.py` com limites **generosos**
(regressão grosseira, não gate de performance rígido) para não tornar o CI
frágil por variação de máquina.

**Expectativa honesta:** dado que a Fase 3 já mediu e decidiu (ADR-0009),
não se espera encontrar gargalo novo na escala de um agente pessoal.
"Otimizar componentes críticos" só acontece se o benchmark achar um —
inventar otimização sem medição violaria `architecture-contracts.md §1`.

### 8.8 — Runtime Hardening

Revisão dirigida (não uma reescrita) sobre: concorrência (o modelo de
threads do ADR-0023 continua com uma tocando SQLite?), tratamento de erro e
timeout dos três providers/backend novos da 8.1/8.2, retries (o
`ComputerToolBackend` respeita a mesma política do router — não implementa
retry próprio), dependências (`psutil` é a única nova; sem transitivas
inesperadas), limites de segurança (nenhum caminho novo de
`Agent Runtime → SO` direto). Findings e correções (se houver) documentados
no relatório final da fase, não num documento à parte — a revisão é sobre
código que **esta mesma fase** escreveu, então o relatório final já é o
lugar certo.

### 8.9 — Documentation Review

- `docs/computer.md` novo (Context Providers + Computer Skill, mesmo
  formato de `voice.md`/`mcp.md`).
- `docs/troubleshooting.md` novo — problemas de setup conhecidos entre
  todas as fases (credencial ausente, extra de voz não instalado, `psutil`
  sem permissão em ambiente restrito, painel não abre no navegador),
  consolidando o que hoje está espalhado em mensagens de erro.
- `architecture-contracts.md` — nenhum componente novo no sentido do §3 (os
  providers entram em §3.2, o backend/skills entram em §3.6/§3.7); uma nota
  em cada seção referenciando a Fase 8, mesmo padrão das notas "Acrescentado
  na Fase X" já usadas.
- `README.md`, `docs/README.md`, `ROADMAP.md` atualizados ao final de cada
  subfase, como nas fases anteriores — não em lote no fim.

### 8.10 — Release Review

Checklist executado e registrado no relatório final: suíte completa,
`ruff check`/`ruff format --check`/`mypy`, instalação limpa (`uv sync`),
`jarvis info` mostra configuração efetiva incluindo os campos novos,
`jarvis skills list` mostra as cinco Skills de computador negadas por
padrão, fluxo de voz/memória/proatividade/Skills/MCP continuam passando
(suíte já cobre). Versão promovida de `0.1.0.dev0` para `0.1.0` em
`pyproject.toml`/`__init__.py` — o próprio ato de "release" que o commit
`release: jarvis v0.1` nomeia.

## 2. Dependências entre subfases

```text
8.1 Computer Context ──┬──► 8.3 Permission System (integra as novas capacidades)
                       │
8.2 Computer Skill ────┤    (depende de 8.1 só para "ler tela" ≈ janela ativa)
                       │
                       ├──► 8.4 Audit Logging (consulta ações de 8.2)
                       │
                       ├──► 8.5 Behavioral Evaluation (independente; usa o que já existe + 8.1/8.2 incidentalmente)
                       │
                       ├──► 8.6 Failure + Recovery (independente)
                       │
                       ├──► 8.7 Performance (independente; pode incluir os providers de 8.1 no benchmark)
                       │
8.1+8.2+8.3+8.4 ───────┴──► 8.8 Runtime Hardening (revisa o que 8.1–8.4 escreveram)
                            │
                            ▼
                       8.9 Documentation Review
                            │
                            ▼
                       8.10 Release Review
```

Ordem de implementação: **8.1 → 8.2 → 8.3 → 8.4 → 8.5 → 8.6 → 8.7 → 8.8 →
8.9 → 8.10**, seguindo a numeração do roadmap.

## 3. Riscos

| Risco | Mitigação |
|---|---|
| Testes dependentes de Windows/hardware real quebrando CI (Linux) | Todo provider/backend novo recebe suas chamadas de SO como **callable injetável**, testado só com dublês — mesmo padrão de `LocalDeviceProvider`. Nenhum teste chama `ctypes`/`psutil` de verdade. |
| `computer.run_command` virar execução arbitrária | Allowlist de templates nomeados, `subprocess` sem `shell=True`, nunca concatenação de string do usuário no comando — auditado por teste dedicado, não só por revisão. |
| GPU/idle-time inexistentes fora do Windows quebrando algo | Tratados como ausência (`ContextProviderError` → degrada), mesmo caminho que Location já usa desde a Fase 2. |
| Nova dependência (`psutil`) trazendo superfície inesperada | Biblioteca madura, sem I/O de rede, amplamente usada; escopo de uso restrito a leituras (CPU/RAM/processos) — nenhuma escrita do sistema passa por ela. |
| Capacidades `computer:*` vazando para produção sem intenção | Allowlist vazia nega tudo por padrão (mesma regra de `file:write` desde a Fase 5) — nenhum interruptor novo necessário, e testado explicitamente na 8.3. |
| Escopo "Interagir com interface"/"ler tela" virando automação de UI de propósito geral | Reduzido deliberadamente a operações de janela; decisão registrada com alternativa descartada, não lacuna silenciosa. |
| Duplicar cobertura de teste já sólida em 8.5/8.6 | Cada cenário aponta para a cobertura de unidade existente quando ela já é suficiente; o arquivo novo agrega, não substitui. |

## 4. Componentes reutilizados (não recriados)

- `ContextProvider` port + `ContextAggregator` (Fase 2) — os três providers
  novos são só mais implementações do mesmo port.
- `ToolBackend` port + `ToolRegistry`/`ToolRouter` (Fase 5) — o
  `ComputerToolBackend` é só mais um backend.
- `SkillDescriptor`/`SkillRegistry`/`ActionExecutor` (Fase 5) — as cinco
  Skills de computador seguem exatamente o molde de `file.*`.
- `PolicyEngine`/`PolicyRuleSet` (Fase 5) — nenhuma regra nova; as
  capacidades novas só precisam entrar na allowlist para funcionar.
- `AuditLog`/Event Store (Fase 1/5) — `jarvis audit show` só lê.
- `jarvis.decisions.project_decisions` (Fase 7.4) — reaproveitado por
  `jarvis audit show`.
- `StubLLMProvider`/padrão de teste de integração (Fase 4/7) — 8.5 e parte
  de 8.6 seguem o mesmo molde de `test_agent_integration.py`.

## 5. ADRs previstos

1. **`psutil` como dependência normal para observação do computador** — por
   que não é extra opcional (ao contrário de `sounddevice`), por que não
   `ctypes`/WMI puro para tudo, e o que continua ausente fora do Windows.
2. **Execução de comando por template allowlistado, nunca shell livre** —
   a decisão de segurança mais importante da fase: `computer.run_command`
   nunca aceita texto de comando montado dinamicamente.

Números exatos (`ADR-0030`, `ADR-0031`) atribuídos na implementação.

## 6. Commits previstos

```text
feat: implement computer context providers      (8.1)
feat: implement computer skill                  (8.2)
feat: implement permission system               (8.3)
feat: implement audit logging                   (8.4)
test: add agent behavioral evaluation suite      (8.5)
test: add failure and recovery scenarios         (8.6)
perf: optimize context and memory retrieval      (8.7)
refactor: harden agent runtime                   (8.8)
docs: complete system documentation              (8.9)
release: jarvis v0.1                             (8.10)
```

`docs: complete system documentation` inclui `docs/computer.md`,
`docs/troubleshooting.md`, `architecture-contracts.md` e `ROADMAP.md`.

## 7. Critérios de conclusão

Por subfase: implementação completa, testes relevantes escritos e
passando, documentação necessária atualizada, arquitetura preservada
(nenhuma violação nova capturada pelos testes de arquitetura existentes,
mais os novos que 8.3 acrescenta), nenhum problema crítico conhecido,
commit criado.

Da fase inteira (`ROADMAP.md` §"Release"): `uv run pytest`, `uv run ruff
check`, `uv run ruff format --check` e `uv run mypy` verdes; instalação
limpa funcional; `jarvis info` mostra a configuração efetiva completa;
todos os workflows principais (voz, memória, proatividade, Skills, MCP)
continuam passando; `ROADMAP.md` atualizado; working tree limpo (respeitando
o que já estava sujo antes desta sessão, sem tocar nisso); versão promovida
a `0.1.0`.
