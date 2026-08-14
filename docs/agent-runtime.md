# Agent Runtime

> **Documentação de implementação**: descreve o Agent Runtime que existe em
> `src/jarvis/agent/` desde a **Fase 4**. O contrato normativo está em
> [`architecture-contracts.md §3.4`](architecture-contracts.md#34-agent-runtime),
> [ADR-0002](adr/0002-llm-provider-abstraction.md),
> [ADR-0003](adr/0003-policy-engine-safety-authority.md),
> [ADR-0011](adr/0011-gemini-rest-llm-adapter.md) e
> [ADR-0012](adr/0012-core-owned-structured-decisions.md) — este documento não
> os repete: explica o que foi construído, como funciona e o que ainda não faz.
>
> O plano que guiou a fase, com as alternativas descartadas, está em
> [`phase-4-plan.md`](phase-4-plan.md).

## O que existe

```text
src/jarvis/agent/
├── errors.py        # taxonomia: InvalidDecisionError, LLM*Error, PromptTooLargeError
├── messages.py      # Role, Message, LLMRequest, LLMResponse, StopReason, TokenUsage
├── ports.py         # LLMProvider (Protocol)
├── decision.py      # DecisionType, MemoryProposal, ActionProposal, Decision, parse_decision
├── conversation.py  # ConversationTurn, Conversation
├── input.py         # UserMessage, EventTrigger, EventSummary, AgentInput
├── importance.py    # ImportanceWeights, ImportanceAssessment, assess, should_reason
├── prompt.py        # SYSTEM_INSTRUCTION, Capability, PromptBudget, ReasoningEnvelope, PromptBuilder
├── runtime.py       # AgentRuntime, AgentTurn, LLMRetryPolicy, GenerationDefaults
└── adapters/
    └── gemini.py    # GeminiLLMProvider (REST, stdlib)
```

O Agent Runtime é o único componente que conhece Context, Memory e
`LLMProvider` ao mesmo tempo — é para isso que ele existe. Ele **não** conhece
Skill, Tool Router, MCP, Policy, banco, arquivo nem `Settings`.

## O loop implementado

```mermaid
flowchart LR
    OBS["observe\nUserMessage | EventTrigger"] --> CTZ["contextualize\ncontext_reader()"]
    CTZ --> RET["retrieve\nMemoryManager.retrieve"]
    RET --> TRI{"importance\n(só para evento)"}
    TRI -->|"abaixo do limiar"| SIL["Decision.ignore\nsem chamar o LLM"]
    TRI -->|"acima"| PRM["prompt\nPromptBuilder.build"]
    PRM --> LLM["reason\nLLMProvider.generate"]
    LLM --> DEC["decide\nparse_decision"]
    DEC --> OUT["AgentTurn"]
```

`AgentRuntime.handle(agent_input, conversation=…, recent_events=…, capabilities=…)`
devolve um `AgentTurn` com a decisão, a avaliação de importância (quando
houve), os ids das memórias consultadas, o uso de tokens e a latência.

**O que o loop não faz, por decisão e não por omissão:** não grava memória, não
emite evento, não captura snapshot, não escreve em disco. O único efeito
externo de um turno é a chamada HTTP feita pelo adapter. Quem aplica a proposta
de memória é o composition root, depois de receber o `AgentTurn` — ver
[ADR-0018](adr/0018-memory-writes-outside-the-policy-engine.md).

## Duas entradas, dois tratamentos

| | `UserMessage` | `EventTrigger` |
|---|---|---|
| origem | CLI (`agent ask`/`chat`), futura Voice Interface | evento já registrado no Event Store |
| triagem | **nunca** — falar com o agente é, por definição, relevante | sempre, antes de qualquer chamada ao modelo |
| `correlation_id` | o `conversation_id` | o `correlation_id` do evento |
| `causation_id` | ausente | o `event_id` do gatilho |
| payload no prompt | o texto da mensagem | o payload do evento, inteiro |

## `Decision`: seis variantes, validadas por forma

`ignore` · `remember` · `notify` · `ask` · `act` · `act_and_notify`

Cada variante declara o que exige e o que não admite, numa tabela que os testes
percorrem (`_REQUIRED`/`_FORBIDDEN` em `decision.py`) — uma variante nova sem
regra de forma quebra o teste.

**Uma resposta de conversa é `notify` com `message`.** O que distingue um
alerta proativo de uma réplica ao usuário é o gatilho, não o tipo da decisão;
não existe um sétimo tipo `respond`.

`Decision` é **dado inerte**: sem `execute()`, sem callback, sem referência a
Skill. `test_a_decision_carries_no_executable_behaviour` verifica isso por
introspecção, e `test_agent_architecture.py` verifica que nenhum módulo do
pacote alcança `jarvis.skills`, `jarvis.tools`, `jarvis.policy`,
`jarvis.execution` ou `jarvis.mcp`. Os quatro primeiros eram nomes apenas
reservados quando o teste foi escrito, na Fase 4, justamente para que ele
estivesse de guarda no dia em que existissem — desde a Fase 5 existem, e o
teste passou a ter dentes. `jarvis.mcp` segue sem existir de propósito: MCP é
um backend do Tool Router (`tools/adapters/mcp_*.py`), não um componente de
domínio.

## `LLMProvider`: o que um adapter precisa garantir

```python
class LLMProvider(Protocol):
    @property
    def model(self) -> LLMModel: ...
    def generate(self, request: LLMRequest) -> LLMResponse: ...
```

- não busca contexto, memória, eventos, capacidades nem configuração;
- não monta prompt e não interpreta a resposta como decisão;
- não guarda estado entre chamadas;
- traduz **toda** exceção nativa para a taxonomia de `agent/errors.py`;
- respeita `request.timeout_seconds`.

O port não tem superfície de tool-calling nem de JSON Schema — ver
[ADR-0012](adr/0012-core-owned-structured-decisions.md).

## O adapter Gemini

| Aspecto | Como é |
|---|---|
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent` |
| Transporte | `urllib.request` da stdlib; **nenhum SDK de vendor** ([ADR-0011](adr/0011-gemini-rest-llm-adapter.md)) |
| Autenticação | header `x-goog-api-key` — nunca na query string, que vaza em log de exceção e proxy |
| Structured output | `responseMimeType = "application/json"` + `responseSchema`; a validação autoritativa continua sendo do Core |
| `action.parameters` | viaja como **texto JSON** e é decodificado no adapter ([ADR-0019](adr/0019-gemini-action-parameters-as-json-text.md)) |
| Modelo | `JARVIS_GEMINI_MODEL`, default `gemini-3.6-flash` (tier gratuito) |
| Testabilidade | o transporte é injetável (`opener`), então corpo, parsing e erros são testados sem rede |

Tradução de erro (nenhuma exceção nativa chega ao Core):

| Origem | Erro interno | Retryable |
|---|---|---|
| timeout de socket / `URLError(TimeoutError)` | `LLMTimeoutError` | sim |
| HTTP 429 (lê `Retry-After`) | `LLMRateLimitError` | sim |
| HTTP 401/403 | `LLMAuthenticationError` | não |
| HTTP 4xx restante | `LLMRequestRejectedError` | não |
| HTTP 5xx, conexão recusada | `LLMProviderError` | sim |
| corpo não-JSON, sem candidatos, texto vazio com `STOP` | `LLMInvalidResponseError` | não |

`LLMProviderError` deriva de `ProviderError`, categoria compartilhada
introduzida nesta fase em `jarvis/errors.py` — `EmbeddingProviderError` e
`ContextProviderError` passaram a derivar dela também (contracts §13).

## Importance Engine

Filtro determinístico e explicável, **sem nenhuma chamada de LLM** — um filtro
que chama o modelo não filtra chamadas ao modelo.

| Grandeza | Cálculo |
|---|---|
| `urgency` | o maior entre proximidade do próximo compromisso (≤15 min → 1.0; ≤60 min → 0.7; conhecido → 0.3) e recência do evento (meia-vida de 30 min) |
| `personal_relevance` | melhor `RelevanceScore.total` do retrieval; 0.0 sem memória |
| `temporal_relevance` | fração dos campos de contexto observados que estão `fresh`; 0.5 quando não há nenhum |
| `interruption_cost` | `busy`/`do_not_disturb` → 0.9; atividade exigente → 0.7; `free` → 0.1; desconhecido → 0.3 |

`total = 0.30·urgency + 0.30·personal_relevance + 0.15·temporal_relevance − 0.25·interruption_cost`,
limitado a `[0,1]`. Abaixo de `JARVIS_AGENT_IMPORTANCE_THRESHOLD` (default
`0.45`) o turno termina em `Decision.ignore` com
`reason="below_importance_threshold"` — sem custo, sem token, sem ruído.

`reasons` carrega rótulos fechados (`user_busy`, `schedule_imminent`,
`no_relevant_memory`…), nunca conteúdo: eles vão para o log.

## Prompt assembly e orçamento

O envelope tem oito seções: `now`, `trigger`, `current_context`,
`relevant_memories`, `recent_events`, `conversation`, `available_capabilities`,
`constraints`. Campo de contexto ausente fica fora; campo vencido entra
**marcado** `stale` (contracts §6: quem decide se aceita é o consumidor).

O orçamento é medido em caracteres (~4 por token), não em tokens — um
tokenizador seria dependência nova para uma estimativa que só precisa ser
conservadora. Ordem de corte, sempre a mesma:

1. turnos de conversa mais antigos;
2. eventos recentes mais antigos;
3. memórias de menor score;
4. truncagem por item (`max_chars_per_item`).

O gatilho, a instrução de sistema e as `constraints` **nunca** são cortados; se
ainda assim não couber, `PromptTooLargeError` — falhar é melhor que enviar um
prompt mutilado em silêncio. O que foi omitido é informado ao modelo em
`constraints.omitted` e logado em contagem.

## Erros, timeout, retry

- **Timeout**: um único mecanismo, `LLMRequest.timeout_seconds`, aplicado pelo adapter.
- **Retry de transporte** (`LLMRetryPolicy`, no Core): só quando o erro se declara `retryable`; `max_attempts=2` por default para não queimar quota gratuita; respeita o `Retry-After` do provider quando existe; `sleep` é injetável, então nenhum teste dorme.
- **Reparo de conteúdo**: uma tentativa, reenviando o envelope com um pedido curto de correção de formato. Falhando a segunda, `InvalidDecisionError` sobe.
- **Truncagem** (`StopReason.MAX_TOKENS`): tratada antes do parsing, e não como erro de formato. Um JSON cortado no meio de uma string não volta válido por insistir no formato — o que falta é brevidade, então o reparo pede concisão (`TRUNCATION_HINT`). Persistindo, `LLMInvalidResponseError` nomeia a causa: orçamento de saída ou modelo que se repete.
- **Sem limitador de taxa client-side**: o que existe é 429 mapeado, retries limitados, uma chamada por turno e a triagem cortando o caminho proativo. Gatilho para acrescentar: 429 recorrente em uso normal.

## Observabilidade

Logs estruturados, um por passo relevante, sempre com `correlation_id`:
`agent.turn_started`, `agent.triage_skipped`, `agent.prompt_trimmed`,
`agent.llm_called`, `agent.llm_failed`, `agent.decision_invalid`,
`agent.response_truncated`, `agent.decided`.

**Nenhum deles contém** prompt, resposta do modelo, conteúdo de memória,
payload de evento, `message` da decisão ou credencial —
`tests/test_agent_privacy.py` verifica isso em todos os caminhos, inclusive nos
de erro.

Cadeia reconstruível, e desde a Fase 5 percorrível de verdade com
`jarvis events list --correlation-id <id>`: `Event.correlation_id` →
`Decision.correlation_id` → `PolicyVerdict` → Skill → Tool.

## Configuração e secrets

| Variável | Default | Categoria |
|---|---|---|
| `JARVIS_LLM_PROVIDER` | `gemini` | configuração |
| `JARVIS_GEMINI_API_KEY` | — | **secret** (`SecretStr`) |
| `JARVIS_GEMINI_MODEL` | `gemini-3.6-flash` | configuração |
| `JARVIS_LLM_TIMEOUT_SECONDS` | `30` | configuração |
| `JARVIS_LLM_MAX_OUTPUT_TOKENS` | `1024` | configuração |
| `JARVIS_LLM_TEMPERATURE` | `0.2` | configuração |
| `JARVIS_LLM_MAX_ATTEMPTS` | `2` | configuração |
| `JARVIS_AGENT_IMPORTANCE_THRESHOLD` | `0.45` | configuração |

`build_llm_provider` em `cli.py` é o **único** lugar que lê a credencial. O
`AgentRuntime` recebe valores já resolvidos (`GenerationDefaults`), nunca
`Settings` — é o que torna estruturalmente impossível um secret chegar ao
prompt, e não apenas improvável.

## Comandos de CLI

```bash
jarvis agent ask "o que aconteceu enquanto eu estava fora?"
jarvis agent ask "oi" --conversation-id conv-42
printf 'oi\ne depois?\n' | jarvis agent chat        # multi-turno, uma mensagem por linha
jarvis agent react --event-id <id de um evento registrado>
```

Sem `JARVIS_GEMINI_API_KEY` os três falham com mensagem explícita e código de
saída 1; todo o resto do Jarvis continua funcionando offline.

Para `act`/`act_and_notify` **sem** `--execute` a saída imprime, literalmente,
`proposta não executada: use --execute para submetê-la à política`. Com a flag a
dica some: quem submeteu lê o desfecho real logo abaixo, e as duas linhas juntas
se contradiriam.

## Execução (desde a Fase 5)

O agente continua **sem** executar nada: ele entrega a `Decision` e para. O que
mudou é que agora existe alguém para recebê-la.

- **Ida.** `cli.capabilities_from(registry)` traduz `SkillDescriptor` em
  `Capability` e injeta em `runtime.handle(..., capabilities=...)`. O agente não
  importa `jarvis.skills`: recebe nomes, resumos e schemas como **texto**.
  `Capability.parameters` carrega a linha de schema — sem ela o modelo acerta o
  nome da skill e erra os campos, e a validação recusa a proposta inteira.
- **Submissão.** `jarvis agent ask --execute` entrega `decision.action` ao
  `ActionExecutor`. É **opt-in**: executar precisa ser escolha de quem chamou,
  não consequência automática de raciocinar. Sem a flag, a decisão só é impressa.
- **Volta.** O desfecho vira `ActionResultSummary` — dado puro em
  `agent/input.py`, sem referência a `jarvis.execution` — e entra no envelope
  como `last_action_result`, marcado na instrução de sistema como **fato**: o
  modelo não pode afirmar sucesso sobre um `denied` ou um `failed`.
- **Segundo turno só quando dá errado.** Em `act_and_notify` bem-sucedido a
  mensagem do agente já existe, e pagar uma chamada extra para reformular o que
  já foi dito é desperdício de quota. Numa negação ou falha, a frase em
  linguagem natural vale a chamada — e é aí que o "observe result" do loop 4.6 se
  fecha.

`runtime.py`, `decision.py`, `ports.py` e o adapter Gemini **não mudaram** na
Fase 5. `prompt.py` ganhou `Capability.parameters`, `PromptBudget.max_capabilities`
e a seção `last_action_result`; capacidades entraram na escada de corte por
último — cortar uma capacidade remove uma opção de ação, o que é pior que cortar
contexto, mas não cortá-las nunca faria um registry grande estourar o orçamento
sem saída.

## Gravação de memória

O outro laço que se fecha fora do runtime. `cli._persist_memory_proposal` aplica
`decision.memory` logo depois do turno, antes de imprimi-lo — mesmo desenho da
ação, sem Policy Engine e sem `--execute`, pelos motivos do
[ADR-0018](adr/0018-memory-writes-outside-the-policy-engine.md): gravar uma
afirmação não toca nada fora do processo e se desfaz por supersessão.

- Vale para **qualquer** decisão que carregue `memory`, não só `remember` — a
  matriz de forma permite `notify` com proposta junto.
- A proveniência segue o caminho de entrada: `USER` sem referência em
  `ask`/`chat`, `EVENT` com o `event_id` do gatilho em `react`. Sem referência no
  caminho do usuário porque `find_duplicate` exige a **mesma** `reference`:
  apontar para um `decision_id` novo a cada turno faria cada repetição da mesma
  afirmação virar linha nova em vez de reforço.
- `MemoryProposal` é mais permissivo que `Memory` (não tem `scope` nem
  `valid_until`). Uma proposta que o domínio recusa — `preference` sem
  `subject`, por exemplo — é **recusada sozinha**: a saída imprime o motivo, e a
  mensagem e a ação da mesma decisão continuam valendo.
- A saída distingue os três desfechos: `gravada como <id>`, `reforçada como
  <id>`, `proposta recusada: <motivo>`. Um `remember` puro não tem `message`, e
  a confirmação (`Anotado.`) é o que o usuário lê e o que a conversa guarda como
  turno do assistente.

`AgentRuntime` **não** mudou: `tests/test_agent_runtime.py` continua afirmando
que o runtime não grava memória.

## Limitações conhecidas

- **`notify`/`ask` não entregam nada**: falta o Notification System (7.3). A
  mensagem só chega ao usuário se ele estiver olhando o terminal.
- **O agente não emite eventos.** Registrar decisões de forma consultável é a
  subfase 7.4 — a trilha de execução (`action.*`, `policy.evaluated`) é emitida
  pela camada de ação, não por ele.
- **Não há subscrição no bus.** O caminho proativo é explícito (`agent react`);
  inscrever o agente é o Trigger Engine (7.1). Sem isso, todo
  `jarvis events emit` viraria uma chamada paga.
- **Sem tool-calling e sem streaming** — ver ADR-0012 e `phase-4-plan.md §20`. O
  gatilho que o ADR-0012 previu para reconsiderar (existir um registry real)
  agora está disponível; a reavaliação não foi feita nesta fase.
- **Conversa não é persistida.** Sessões são escopo de 6.4.
- **`EmbeddingProvider` continua local** (`HashingEmbeddingProvider`): é port separado de `LLMProvider` (ADR-0002), e trocá-lo exigiria reindexar tudo e tornaria `memory add` dependente de rede.

## Como trocar de provider

1. Escrever `src/jarvis/agent/adapters/<vendor>.py` implementando `LLMProvider`, traduzindo os erros para a taxonomia de `agent/errors.py`.
2. Acrescentar o nome a `LLMProviderName` em `config.py` e escolher em `build_llm_provider`.

Nada muda em `runtime.py`, `prompt.py`, `decision.py`, `importance.py` nem nos
testes de comportamento do agente. É a promessa do ADR-0002, e os testes de
arquitetura são o que a mantêm verdadeira.

## Testes

```bash
uv run pytest                  # suíte padrão: sem API key, sem rede, sem quota
uv run pytest -m external      # smoke test contra a API real (opcional, manual)
```

O único teste que toca a API real é `tests/test_agent_smoke_external.py`,
marcado `external` e excluído por `addopts`. Os demais usam `StubLLMProvider`,
`FailingLLMProvider` e `RecordingOpener` (`tests/agent_doubles.py`).

## Documentos relacionados

- Contrato normativo: [architecture-contracts.md §3.4](architecture-contracts.md#34-agent-runtime)
- Abstração de LLM: [ADR-0002](adr/0002-llm-provider-abstraction.md)
- Policy Engine como autoridade: [ADR-0003](adr/0003-policy-engine-safety-authority.md) e [security.md](security.md)
- Adapter Gemini: [ADR-0011](adr/0011-gemini-rest-llm-adapter.md)
- Decisão estruturada: [ADR-0012](adr/0012-core-owned-structured-decisions.md)
- Plano da fase: [phase-4-plan.md](phase-4-plan.md)
- Visão geral: [architecture.md](architecture.md)
