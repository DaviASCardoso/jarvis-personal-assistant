# 0031. `computer.open_app`/`computer.run_command`: só argv de uma allowlist, nunca comando livre

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A Fase 8.2 dá ao Jarvis a primeira capacidade real de tocar o sistema
operacional além do workspace de arquivos: abrir um aplicativo, fechar um
processo, focar uma janela e **executar um comando**. Das quatro, a última é
a que carrega o risco qualitativamente diferente — `LocalToolBackend`
(Fase 5) já mexe com o sistema de arquivos, mas dentro de uma raiz
allowlistada e sem nunca invocar um processo novo. `computer.run_command`
seria, sem uma barreira própria, a primeira Tool do projeto capaz de rodar
**qualquer coisa** que o sistema operacional aceite — a superfície de risco
mais alta de todo o catálogo de Skills até aqui.

O guia da Fase 8 é explícito: "nunca permitir execução irrestrita de
comandos". Isso não é uma preferência de estilo — é a mesma classe de decisão
que levou `LocalToolBackend._resolve` a recusar caminho fora da raiz **antes**
de tocar o disco, e que levou a Fase 5 a nunca dar ao LLM autoridade de
segurança ([ADR-0003](0003-policy-engine-safety-authority.md)).

## Decisão

`ComputerToolBackend.open_app`/`run_command` **nunca** aceitam um comando
como texto. Os dois só aceitam um `name` (string curta), que precisa bater
com uma chave de `command_allowlist` — um mapa `nome → argv` (lista de
argumentos já separados) carregado uma única vez pelo composition root a
partir de `JARVIS_COMPUTER_COMMAND_ALLOWLIST_PATH`
(`ComputerToolBackend.load_command_allowlist`, mesmo critério de "ausência é
estado normal, não erro" de `load_mcp_config`).

Três propriedades, todas verificadas por teste
(`tests/test_tool_computer_backend.py::TestCommandAllowlist`):

1. **Nunca `shell=True`.** Todo `argv` chega a `subprocess.Popen`/`subprocess.run`
   como lista, nunca como texto interpolado — não há caractere de shell que o
   chamador possa injetar, porque não há chamador que forneça texto de
   comando algum.
2. **A allowlist é fechada por padrão.** `command_allowlist` vazio (o default
   do construtor) nega as duas Tools inteiramente — mesmo critério de
   `policy_granted_capabilities`/`proactivity_trigger_event_types`: uma lista
   vazia nega tudo, nunca permite tudo.
3. **Um `name` fora da allowlist nunca chega a `launch`/`run`.** A checagem
   acontece antes de qualquer chamada nativa — o mesmo "recusar antes de
   agir" de `LocalToolBackend._resolve`.

A allowlist em si não é reinventada por Skill: é uma responsabilidade só do
backend (Infrastructure), e a Skill (`computer.open_app`/`run_command`,
Core) não sabe nem precisa saber que ela existe — só passa o `name` adiante.
Risco e confirmação continuam vivendo na Skill (`risk=medium`/`high`,
`effects={PHYSICAL}`/`{DESTRUCTIVE}`), como manda o
[ADR-0005](0005-skill-tool-mcp-distinction.md); a allowlist é a barreira de
**capacidade técnica**, independente da barreira de **autorização** que o
Policy Engine já aplica sobre `computer:open`/`computer:run`.

## Alternativas consideradas

- **Aceitar `argv` (lista) diretamente do chamador, sem allowlist**:
  descartada — daria ao LLM (via `ActionProposal.parameters`) o poder de
  montar qualquer `argv`, o que equivale a execução irrestrita com um passo
  extra. O guia da Fase 8 proíbe isso explicitamente.
- **Aceitar comando como texto único, validado por regex/denylist de
  caracteres perigosos**: descartada — denylist de caracteres é
  historicamente incompleta (é assim que se originam a maioria dos bypasses
  de sanitização de shell), e ainda exigiria `shell=True` para interpretar o
  texto. Allowlist fechada de `argv` elimina a classe inteira de problema em
  vez de tentar cobri-la.
- **Uma allowlist por Skill (`open_app` e `run_command` com arquivos
  separados)**: descartada por falta de necessidade concreta — as duas
  compartilham o mesmo modelo de risco (`name → argv` fixo), e duas
  configurações para a mesma decisão seria superfície a mais sem ganho
  correspondente (regra 11 do `ROADMAP.md`).
- **Permitir argumentos extras do chamador sobre um `argv` base da
  allowlist** (ex. `run_command(name="dir", args=["/b"])`): descartada por
  ora — reabriria parte da superfície de injeção que a allowlist existe para
  fechar (um argumento adicional pode mudar o comportamento do comando de
  formas não previstas por quem escreveu a allowlist). Documentado como
  decisão de escopo, não lacuna: um caso de uso concreto que precise disso
  pede revisão deste ADR, não uma extensão silenciosa.

## Consequências

- Sem `JARVIS_COMPUTER_COMMAND_ALLOWLIST_PATH` configurado (o default),
  `computer.open_app`/`computer.run_command` continuam registradas — visíveis
  em `jarvis skills list` — mas todo `name` é recusado com
  `ToolInvalidInputError`. O sistema "funciona sem" a capacidade, mesmo
  critério de MCP.
- `computer.focus_window`/`computer.list_processes`/`computer.close_app` não
  passam por allowlist nenhuma — operam sobre processos/janelas já em
  execução, não lançam processo novo, e por isso não carregam a mesma classe
  de risco que justificaria a mesma barreira.
- **Custo aceito:** um operador que queira `computer.open_app`/`run_command`
  de verdade precisa escrever e manter um arquivo JSON de allowlist — mais
  fricção que "deixar o modelo decidir o comando", que é exatamente o ponto.
- **Gatilho para revisitar:** se um caso de uso legítimo precisar de
  argumentos variáveis sobre um comando allowlistado (ex. abrir um arquivo
  específico com um aplicativo específico), este ADR precisa ser revisto —
  hoje o modelo é `name → argv` fixo, sem parametrização.
