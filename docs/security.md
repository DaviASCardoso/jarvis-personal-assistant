# Segurança, Policy Engine e execução

> **Documentação de implementação**: descreve o Policy Engine, o fluxo de
> confirmação e as fronteiras de segurança que existem em `src/jarvis/policy/` e
> `src/jarvis/execution/` desde a Fase 5. Até a Fase 4 este documento era
> conceitual.
>
> Contrato normativo: [`architecture-contracts.md §10`](architecture-contracts.md#10-policy-e-safety-boundary),
> [ADR-0003](adr/0003-policy-engine-safety-authority.md),
> [ADR-0013](adr/0013-single-use-policy-approval.md),
> [ADR-0014](adr/0014-confirmation-state-and-event-answers.md),
> [ADR-0016](adr/0016-action-execution-orchestrator.md) e
> [ADR-0017](adr/0017-audit-trail-as-events.md).

## A propriedade central

**O LLM não é a autoridade final de segurança.** O Agent Runtime pode propor uma
`Decision.act`, mas só o Policy Engine — código determinístico, sem chamada de
LLM, sem I/O — decide se a ação acontece.

```text
LLM propõe.  Código valida.  Policy autoriza.  Skill executa.
Tool opera.  MCP conecta.    Event registra.
```

## O que existe

```text
src/jarvis/policy/
├── vocabulary.py  # RiskLevel, Effect, ConfirmationRequirement, Idempotency
├── verdict.py     # PolicyRequest, PolicyVerdict, PolicyApproval, Confirmation
├── rules.py       # PolicyRuleSet + as regras, cada uma com rule_id
├── engine.py      # PolicyEngine: evaluate(), consume(), ledger
└── errors.py      # PolicyError e a família ApprovalError

src/jarvis/execution/
├── orchestrator.py  # ActionExecutor — o único caminho até uma Skill
├── consumer.py      # ActionEventConsumer — projeta confirmações
└── …                # identidade, modelo, eventos, repositório
```

`jarvis/audit.py` guarda o port `AuditLog` na raiz: `policy`, `tools` e
`execution` o usam, e nenhum dos três pode importar os outros dois.

## As regras

`PolicyRuleSet` é dado imutável montado pelo composition root a partir de
`Settings`. Cada regra tem um `rule_id` estável, que aparece na auditoria — é o
que permite responder "por que essa ação foi negada?" com um identificador, e não
com uma paráfrase que muda quando alguém reescreve uma mensagem.

| `rule_id` | Condição | Veredito |
|---|---|---|
| `skill_not_registered` | a skill não existe no registry | `deny` |
| `required_tool_unavailable` | alguma tool declarada não está disponível | `deny` |
| `skill_denylisted` | nome na denylist estática | `deny` |
| `effect_denylisted` | efeito na denylist | `deny` |
| `risk_above_ceiling` | `risk ≥ deny_risk_at_or_above` (default `critical`) | `deny` |
| `capability_not_granted` | capacidade fora da allowlist | `deny` |
| `risk_requires_confirmation` | `risk ≥ confirm_risk_at_or_above` (default `high`) | `require_confirmation` |
| `effect_requires_confirmation` | efeito destrutivo/físico/externo/de gasto | `require_confirmation` |
| `skill_requires_confirmation` | a Skill declara `always` | `require_confirmation` |
| `proactive_action_requires_confirmation` | Skill `conditional` disparada por **evento** | `require_confirmation` |
| `confirmation_satisfied` | confirmação válida atende o pedido | rebaixa para `allow` |
| `default_allow` | nenhuma das acima | `allow` |

### O mais forte vence

Todas as regras são avaliadas, e o veredito final é
`max(deny, require_confirmation, allow)`. **Não** é "primeira regra que casa":
assim nenhuma regra consegue rebaixar a decisão de outra, e acrescentar uma regra
nova nunca afrouxa a política por acidente de ordenação.

`confirmation_satisfied` só se aplica quando a força máxima é exatamente
`require_confirmation` — como `deny` tem força maior, **uma confirmação jamais
libera uma ação negada**. É a propriedade que impede o pior bug possível desta
camada, e tem teste com esse nome.

Denylist e teto de risco valem **independentemente** da autodeclaração da Skill
(§10.4, "cinto e suspensório").

### Ação proativa é mais cara de errar

Uma Skill `conditional` executa direto quando o usuário pediu, e pede confirmação
quando quem disparou foi um evento: ninguém está olhando, e o gatilho pode ter
vindo de conteúdo não confiável. É por isso que `ActionRequest.actor` existe.

## `PolicyApproval`

Uma aprovação vale porque **o engine que a emitiu a reconhece**, não porque
carrega prova própria ([ADR-0013](adr/0013-single-use-policy-approval.md)):

- `evaluate()` é o único lugar que cria uma aprovação válida — criar inclui
  registrar num ledger interno;
- `consume()` valida contra o ledger: existe? não usada? não expirada?
  `execution_id`, `skill` e `parameters_fingerprint` batem?
- **uso único**, TTL curto (default 60s);
- ligada ao `parameters_fingerprint`: autorizar "apagar A" nunca autoriza
  "apagar B", e editar os parâmetros depois invalida.

Uma `PolicyApproval` construída à mão tem todos os campos e nenhum valor:
`consume()` não a encontra. Sem criptografia, sem JWT — o Jarvis roda em um
processo local, e não há fronteira de confiança a atravessar.

O ledger é **em memória, por processo**. Consequência desejada: uma confirmação
respondida noutra invocação do CLI força reavaliação completa da política. Uma
denylist acrescentada entre o pedido e a confirmação ainda nega.

## Confirmação

Modelo: **ação pendente é estado; resposta do usuário é evento**
([ADR-0014](adr/0014-confirmation-state-and-event-answers.md)).

```text
Processo 1 — jarvis action run --skill file.write …
  evaluate → require_confirmation
    → ActionRepository.put(awaiting_confirmation, com os parâmetros, expires_at)
    → evento action.confirmation_requested (SEM parâmetros)
    → o CLI imprime o execution_id

Processo 2 — jarvis action confirm <execution_id>
  publica action.confirmation_granted            (contracts §10.2)
    → EventBus → ActionEventConsumer → marca confirmado (só estado)
  o CLI chama executor.resume(...)                (passo separado)
    → reavalia a política do zero
    → allow ⇒ approval ⇒ ToolAccess ⇒ handler ⇒ tools ⇒ action.completed
```

O consumer **não executa nada**. Um consumer que disparasse a execução ao receber
a confirmação seria um caminho até a Tool acionado por evento, sem passar de novo
pelo Policy Engine.

A confirmação é ligada a `execution_id` **e** ao `parameters_fingerprint`, e
expira (`JARVIS_CONFIRMATION_TTL_SECONDS`, default 900). A reavaliação nunca
estende o prazo: senão uma pendência consultada de vez em quando duraria para
sempre.

O canal é o **CLI**, não o Notification System — esse é a subfase 7.3.

## Menor privilégio, em três camadas independentes

1. **Política** — `granted_capabilities` limita quais Skills podem ser
   autorizadas. Default restritivo: allowlist vazia nega tudo.
2. **Execução** — `ToolAccess` limita cada execução às tools declaradas naquela
   Skill; só é construído em `jarvis/execution` e só depois de aprovação
   consumida.
3. **Infraestrutura** — o backend local recusa qualquer caminho fora da raiz
   allowlistada; o subprocesso MCP recebe ambiente mínimo e explícito.

Uma camada afrouxada por engano não abre o caminho inteiro.

## As cinco impossibilidades

`PHASE-5.md §36` pede que cinco caminhos sejam impossíveis. Cada um é garantido
estruturalmente e provado duas vezes: por import (`test_action_architecture.py`)
e em execução (`test_action_security.py`).

| Propriedade | Garantia |
|---|---|
| `LLM → Tool` | `jarvis.agent` não importa `policy`/`skills`/`tools`/`execution`; `Decision` é dado inerte, sem `execute()`; o nome da skill viaja como texto |
| `Skill → autoautorizar` | `SkillInvocation` não contém `PolicyEngine` nem `ToolRouter`; aprovação forjada é recusada pelo ledger |
| `Tool → contornar a política` | `ToolAccess` só existe após `consume(approval)`; tool fora do declarado é recusada |
| `require_confirmation → executar` | `submit` devolve `awaiting_confirmation` sem construir `ToolAccess`; `resume` reavalia e exige confirmação válida |
| `deny → executar` | nenhuma aprovação ⇒ nenhum `ToolAccess` ⇒ handler nunca chamado |

Cada arquivo tem também um teste-sentinela que verifica o **caminho feliz** na
mesma montagem — sem ele, os cinco poderiam ficar verdes por vacuidade se a
montagem mudasse.

## Auditoria

A trilha **é** o log de eventos ([ADR-0017](adr/0017-audit-trail-as-events.md)).
Não há `audit.db`. Nove tipos, cada um respondendo a uma pergunta da §23:

```text
action.requested · policy.evaluated · action.confirmation_requested
action.confirmation_granted · action.confirmation_denied
tool.execution_completed · tool.execution_failed
action.completed · action.failed
```

`event_id` determinístico por marco, derivado de
`(execution_id, kind, ordinal, discriminator)`. O `discriminator` existe por um
caso concreto: uma execução confirmada é avaliada **duas vezes**, e sem ele o
veredito que autoriza colidiria com o que pediu confirmação — a trilha perderia
exatamente o registro mais importante.

**Fail-closed no veredito, best-effort no resto**: se `policy.evaluated` não pode
ser gravado, a execução aborta. Sem trilha, sem ação. Falha nos marcos posteriores
é logada mas não desfaz o efeito — não existe compensação honesta para "o arquivo
já foi escrito".

Consulta:

```bash
jarvis events list --correlation-id <id>
```

## Secrets e conteúdo sensível

- Nenhum `PolicyRequest`, `PolicyVerdict`, `PolicyApproval`, evento de auditoria
  ou log carrega parâmetros de ação — só o `parameters_fingerprint` (sha256 do
  JSON canônico).
- A única estrutura que guarda parâmetros é a `PendingAction` em `actions.db`:
  local, apagável, nunca logada.
- Mensagens de erro nomeiam campo e categoria, nunca valor.
- `mcp.json` nomeia variáveis de ambiente; valores só existem em memória, no
  ambiente do subprocesso.
- `system.info` não reporta hostname, usuário nem ambiente — o resultado de uma
  Skill pode acabar num prompt enviado à nuvem.

`tests/test_action_privacy.py` planta valores reconhecíveis e assere a ausência
deles em **todos** os caminhos: permitido, negado, aguardando confirmação e
falho.

## Prompt injection

A defesa não mudou e continua não sendo um filtro de conteúdo: uma `Decision.act`
manipulada por conteúdo de evento continua sendo apenas uma proposta. Nesta fase
ela ganha três barreiras a mais — o nome precisa existir no registry, os
parâmetros precisam passar no schema, e o Policy Engine precisa autorizar.

`test_action_security.py::test_a_skill_name_invented_by_the_model_is_denied`
submete uma proposta com nome inventado e assere
`denied` / `skill_not_registered`.

## Configuração

| Variável | Default | Papel |
|---|---|---|
| `JARVIS_POLICY_GRANTED_CAPABILITIES` | `system:read,file:read,file:write` | allowlist |
| `JARVIS_POLICY_DENIED_SKILLS` | (vazio) | denylist por nome |
| `JARVIS_POLICY_DENIED_EFFECTS` | (vazio) | denylist por efeito |
| `JARVIS_POLICY_CONFIRM_EFFECTS` | `destructive,physical,external_communication,spend` | efeitos que pedem confirmação |
| `JARVIS_POLICY_CONFIRM_RISK` | `high` | risco que pede confirmação |
| `JARVIS_POLICY_DENY_RISK` | `critical` | teto de risco |
| `JARVIS_APPROVAL_TTL_SECONDS` | `60` | validade de uma aprovação |
| `JARVIS_CONFIRMATION_TTL_SECONDS` | `900` | validade de uma confirmação |
| `JARVIS_FILE_SKILL_ROOT` | `data/workspace` | raiz allowlistada |

Valor inválido **falha alto** no carregamento: configuração de segurança
silenciosamente ignorada é pior que ausente. `jarvis info` imprime a política
efetiva — ela não deve ser adivinhada.

Nada disso é preferência do usuário (ADR-0006): preferências vivem em Memory.

## O que a Fase 6 acrescentou

Duas credenciais novas (`JARVIS_GROQ_API_KEY`, `JARVIS_GOOGLE_TTS_API_KEY`), com
as mesmas três regras das anteriores: `SecretStr`, lidas **só** no composition
root, e sempre em header — nunca em query string, log, evento ou memória. Um
teste varre a AST atrás de `get_secret_value` fora de `cli.py`.

Duas fronteiras novas, e as duas são de leitura:

- **A voz não alcança execução.** Uma ação proposta por voz percorre exatamente a
  mesma cadeia de uma digitada, inclusive a confirmação, que continua publicando
  evento e **reavaliando a política do zero**. `jarvis.voice` não importa
  `jarvis.execution` nem `jarvis.policy`, e um teste garante isso.
- **O painel não executa nada.** Nenhuma rota de escrita existe: `POST`, `PUT`,
  `DELETE` e `PATCH` respondem 405 em qualquer caminho, e o bind é fixo em
  loopback ([ADR-0024](adr/0024-observability-panel-as-snapshot-reader.md)).

Privacidade: áudio nunca é gravado em disco, transcrição nunca entra em evento
([ADR-0025](adr/0025-voice-transcripts-as-operational-state.md)), e o painel
nunca ecoa o payload de um evento de fonte externa. O que **sai** do dispositivo
está tabelado em [voice.md §8](voice.md).

## Limitações conhecidas

- O ledger de aprovações não sobrevive ao processo. É a decisão, não um defeito.
- Não há proteção contra código malicioso **dentro** do processo: quem edita
  `jarvis/policy/engine.py` pode tudo. Nenhum mecanismo em processo poderia
  prometer outra coisa.
- O canal de confirmação é o CLI e a voz; notificação real é a 7.3.
- Com a voz ligada, áudio do usuário sai do dispositivo para dois serviços de
  nuvem. É contrapartida declarada, não descuido — ver
  [ADR-0022](adr/0022-cloud-speech-over-stdlib-rest.md).
- Não há revogação de aprovação em voo — o TTL curto é o que limita a janela.

## Documentos relacionados

- Skills: [skills.md](skills.md) · Tools e MCP: [mcp.md](mcp.md)
- Agent Runtime: [agent-runtime.md](agent-runtime.md)
- Contrato normativo: [architecture-contracts.md §10](architecture-contracts.md#10-policy-e-safety-boundary)
- Plano da fase: [phase-5-plan.md](phase-5-plan.md)
