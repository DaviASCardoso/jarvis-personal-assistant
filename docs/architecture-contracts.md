# Contratos arquiteturais do Jarvis

> Definido na subfase **0.3** do [roadmap](../ROADMAP.md).
>
> Este documento define as regras que **todo componente futuro do Jarvis deve
> respeitar**. Não é um documento de implementação: nenhuma classe, interface
> ou módulo é criado aqui. É a referência que a Fase 1 em diante usa para não
> reproduzir os acoplamentos que este projeto quer evitar (`Memory → LLM`,
> `Event → PostgreSQL`, `Skill → OpenAI`, `Context → Gmail`).
>
> As decisões mais difíceis de reverter que fundamentam estes contratos estão
> registradas como ADRs em [`adr/`](adr/). Este documento referencia o ADR
> correspondente onde relevante, em vez de repetir a justificativa.
>
> Documentação de implementação por componente (`event-system.md`,
> `memory-system.md`, etc.) é escopo da subfase 0.5 e das fases 1–8, criada
> junto de cada funcionalidade real — ver [`../README.md`](README.md).

---

## 1. Princípios e escopo

Toda decisão arquitetural do Jarvis prioriza, nesta ordem de importância:

1. baixo acoplamento;
2. interfaces pequenas;
3. testabilidade;
4. substituibilidade;
5. simplicidade;
6. segurança;
7. observabilidade;
8. evolução incremental.

E evita explicitamente:

- abstrações especulativas (port/interface sem consumidor real);
- padrões de design usados por estética;
- frameworks desnecessários;
- dependências circulares;
- acoplamento a um único fornecedor de LLM;
- acoplamento do domínio à infraestrutura.

O Jarvis é um projeto pessoal. Estes contratos existem para manter o sistema
extensível sem virar um monólito acoplado — não para reproduzir complexidade
de arquitetura empresarial. Quando um contrato aqui parecer pesado demais
para o tamanho atual do projeto, isso é um sinal para simplificar o contrato,
não para ignorá-lo silenciosamente.

---

## 2. Regra de dependência (Ports & Adapters)

Ver [ADR-0001](adr/0001-ports-and-adapters-dependency-rule.md) para a
justificativa completa, incluindo por que a pilha linear
`Domain → Application → Infrastructure → Interfaces` foi rejeitada.

```text
                    ┌───────────────────────────┐
                    │           CORE            │
                    │  (Domain + Application)    │
                    │  entidades, value objects,  │
                    │  ports, orquestração pura   │
                    └──────────────┬──────────────┘
                                   │ define ports
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
      ┌───────────────┐   ┌───────────────┐    ┌─────────────────┐
      │ INFRASTRUCTURE │   │  INTERFACES   │    │ COMPOSITION ROOT │
      │   (adapters)   │   │ (entry points)│    │     (wiring)     │
      └───────────────┘   └───────────────┘    └─────────────────┘
```

- **Core** = Domain (entidades, value objects, ports, lógica pura sem I/O) +
  Application (serviços de orquestração que usam ports: Agent Runtime loop,
  Context Aggregator, Memory Manager, Policy Engine, Skill Registry, Tool
  Router). Não é necessariamente uma separação de pastas na Fase 1 — é uma
  regra de dependência.
- **Infrastructure** = adapters que implementam os ports do Core (bancos,
  LLM providers, MCP client, STT/TTS, canais de notificação, watchers de
  eventos).
- **Interfaces** = pontos de entrada que acionam o Core (CLI, daemon de voz,
  futura API).
- **Composition Root** = único lugar autorizado a conhecer Core,
  Infrastructure e Interfaces ao mesmo tempo, e a instanciar/injetar
  adapters concretos nos serviços do Core.

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Core** | depender apenas de outros elementos do Core (entidades, ports, outros serviços de Core) | definir ports que a Infrastructure deve implementar | importar qualquer módulo de Infrastructure ou de um SDK de vendor específico |
| **Infrastructure** | implementar ports definidos no Core | depender do Core (para conhecer a assinatura dos ports) | ser importada por Core ou por Interfaces diretamente |
| **Interfaces** | acionar casos de uso do Core | depender do Core | importar Infrastructure diretamente (só via Composition Root) |
| **Composition Root** | instanciar adapters e injetá-los no Core | conhecer Core + Infrastructure + Interfaces | conter lógica de negócio |

**Responsável:** cada novo componente, ao ser implementado a partir da Fase
1, é responsável por respeitar esta direção de dependência — revisão de
código deve rejeitar qualquer import que a viole.

---

## 3. Limites dos componentes

### 3.1 Event System
- **Responsabilidade:** capturar acontecimentos do mundo digital/físico como
  fatos estruturados e imutáveis; publicá-los; persisti-los para consulta.
- **Permitido conhecer:** o próprio `Event`, seu `EventStore`/`EventBus`.
- **Proibido conhecer:** Context Engine, Memory, Agent Runtime, Skills,
  Policy, LLM.
- **Entradas:** sinais brutos de Event Sources (adapters de Infrastructure).
- **Saídas:** `Event` imutável, publicado via `EventBus` e consultável via
  `EventStore`.
- **Dependências permitidas:** Domain (entidade `Event`), ports próprios.
- **Dependências proibidas:** qualquer componente a jusante do fluxo
  principal (Context, Memory, Agent, Skills, Policy) e qualquer infra
  concreta fora de seus próprios ports.
- **Responsável:** Event System.

### 3.2 Context Engine
- **Responsabilidade:** manter uma projeção consultável do "estado atual",
  derivada de eventos + providers.
- **Permitido conhecer:** Context Providers (via port), Event Store (leitura).
- **Proibido conhecer:** internals de Memory, Agent Runtime, Skills, LLM.
- **Entradas:** eventos (via subscrição), polls de providers.
- **Saídas:** `CurrentContext` e `ContextSnapshot`, via port de consulta.
- **Dependências permitidas:** Domain, Event System (como consumidor,
  somente leitura), ports de Context Provider.
- **Dependências proibidas:** Memory, Agent Runtime, Skills/Tools, LLM.
- **Responsável:** Context Engine.

### 3.3 Memory System
- **Responsabilidade:** conhecimento durável e recuperável sobre o usuário e
  o mundo, com ciclo de vida (reforço, decaimento, expiração).
- **Permitido conhecer:** `MemoryRepository` port, `EmbeddingProvider` port
  (ver [ADR-0002](adr/0002-llm-provider-abstraction.md)).
- **Proibido conhecer:** `LLMProvider` de raciocínio, Skills, Policy, Tool
  Router.
- **Entradas:** escrita (`remember`) e consulta (`retrieve`), acionadas por
  Agent Runtime/Event System.
- **Saídas:** entidades `Memory`, resultados de retrieval rankeados.
- **Dependências permitidas:** Domain, `EmbeddingProvider` port,
  `MemoryRepository` port.
- **Dependências proibidas:** `LLMProvider` de raciocínio, Skills, Tool
  Router, Policy.
- **Responsável:** Memory System.

### 3.4 Agent Runtime
- **Responsabilidade:** núcleo de raciocínio — monta prompt a partir de
  contexto+memória+evento, chama o LLM via port, interpreta a `Decision`
  estruturada, conduz o loop observe→contextualize→retrieve→reason→decide→
  execute→observe result.
- **Permitido conhecer:** Context (leitura), Memory, `LLMProvider` port,
  Policy Engine (apenas para entregar a `Decision`), Skill Registry (apenas
  para descoberta de capacidades).
- **Proibido conhecer:** SDK concreto de vendor de LLM, implementação
  interna de Skills, internals do Tool Router, internals de infraestrutura.
- **Entradas:** `Event` ou enunciado de conversa + contexto atual + memórias
  recuperadas.
- **Saídas:** `Decision` estruturada (`ignore` | `remember` | `notify` |
  `ask` | `act` | `act_and_notify`).
- **Regra crítica:** o Agent Runtime **nunca executa ações diretamente** —
  só emite `Decision`. Quem executa é Policy → Skill → Tool Router → MCP.
  Ver [ADR-0003](adr/0003-policy-engine-safety-authority.md).
- **Dependências permitidas:** Domain (`Event`, `Context`, `Memory`,
  `Decision`), `LLMProvider` port, `PromptBuilder` próprio, serviços de
  aplicação de Memory/Context.
- **Dependências proibidas:** implementação concreta de Skills, internals do
  Tool Router, MCP, infraestrutura.
- **Responsável:** Agent Runtime.

### 3.5 Policy Engine
- **Responsabilidade:** autoridade determinística sobre se uma ação
  proposta é permitida, negada ou requer confirmação. Dona de regras de
  permissão, níveis de risco e do disparo de audit logging.
- **Permitido conhecer:** `Decision` recebida, metadados de risco/permissão
  declarados pela Skill, regras de política configuradas, `Notification`
  port (para pedir confirmação), `AuditLog` port.
- **Proibido conhecer:** LLM, internals de prompt, internals de Memory,
  internals de Context, detalhes de wire do MCP.
- **Entradas:** proposta `Decision.act(skill, params)` com metadados de
  risco da Skill.
- **Saídas:** `PolicyVerdict` (`allow` | `deny` | `require_confirmation`) +
  registro de auditoria; quando aplicável, emite `PolicyApproval` (ver
  §10.3).
- **Dependências permitidas:** Domain (`Decision`, metadados de Skill,
  `PolicyApproval`), `Notification` port, `AuditLog` port.
- **Dependências proibidas:** `LLMProvider`, MCP, implementação concreta de
  Skills, Memory, Context.
- **Responsável:** Policy Engine. Nenhum outro componente decide `allow` /
  `deny` / `require_confirmation` — ver §8.4 e §10.

### 3.6 Skills
- **Responsabilidade:** representar uma capacidade/workflow que o agente
  pode executar — ver distinção completa Skill vs Tool vs MCP em §8.
- **Permitido conhecer:** Tool Router port, seu próprio schema de
  entrada/saída, seus próprios metadados de risco.
- **Proibido conhecer:** internals do Agent Runtime, LLM, internals de
  Memory/Context (dados necessários chegam como parâmetro explícito, não são
  buscados pela própria Skill), internals do Policy Engine.
- **Entradas:** parâmetros validados, entregues **após** aprovação do Policy
  Engine.
- **Saídas:** `SkillResult` ou `SkillError`.
- **Dependências permitidas:** Domain (contratos de `Tool`/`Skill`), Tool
  Router port.
- **Dependências proibidas:** `LLMProvider`, Memory, Context, internals de
  Policy, detalhes concretos de um MCP server específico.
- **Responsável:** cada Skill individual, pelo seu próprio contrato de
  entrada/saída e pela correção da sua declaração de risco — não pela
  decisão de autorização (ver §8.4).

### 3.7 Tool Router
- **Responsabilidade:** rotear uma chamada de tool de uma Skill para o
  backend correto (MCP hoje; outros backends no futuro), normalizar
  resultados/erros, aplicar timeout, registrar execução.
- **Permitido conhecer:** MCP Client port, registry de tools/discovery,
  configuração de timeout.
- **Proibido conhecer:** lógica de negócio de Skills, Agent Runtime, regras
  de decisão do Policy Engine (assume que a chamada já foi autorizada).
- **Entradas:** `ToolCall` já aprovado (ver `PolicyApproval`, §10.3).
- **Saídas:** `ToolResult` ou `ToolError` normalizado.
- **Dependências permitidas:** Domain (contratos de `Tool`), MCP Client
  port, outros ports de backend de tool.
- **Dependências proibidas:** LLM, Memory, Context, regras de negócio de
  Policy, Skills.
- **Responsável:** Tool Router.

### 3.8 MCP (Client)
- **Responsabilidade:** implementar o protocolo MCP — conexão, descoberta de
  ferramentas, validação de schema no limite do protocolo, invocação,
  reconexão.
- **Permitido conhecer:** protocolo MCP, configuração de conexão dos
  servers.
- **Proibido conhecer:** Skills, Agent Runtime, Policy, Memory.
- **Entradas:** `ToolCall` técnico vindo do Tool Router.
- **Saídas:** resultado bruto do MCP server, traduzido para o contrato de
  `ToolResult`/`ToolError` do Core.
- **Dependências permitidas:** biblioteca/protocolo MCP.
- **Dependências proibidas:** qualquer componente de Core além do contrato
  de `Tool`.
- **Responsável:** MCP Client (parte de Infrastructure).

### 3.9 Voice Interface
- **Responsabilidade:** wake word → STT → encaminha texto ao Agent Runtime
  → TTS da resposta; gerencia sessão/interrupção.
- **Permitido conhecer:** ports de STT/TTS, a interface conversacional do
  Agent Runtime.
- **Proibido conhecer:** Skills, Tools, MCP, internals de Memory/Context
  (acessa tudo isso só através do Agent Runtime).
- **Entradas:** stream de áudio.
- **Saídas:** texto (para o Agent) / áudio (da resposta do Agent).
- **Dependências permitidas:** Domain (`ConversationContext`), interface
  conversacional do Agent Runtime, ports de STT/TTS.
- **Dependências proibidas:** Skills, Tools, MCP, Memory/Context diretamente.
- **Responsável:** Voice Interface.

### 3.10 Notification System
- **Responsabilidade:** entregar mensagens ao usuário (desktop, voz,
  silencioso) com prioridade; usado tanto para notificação proativa quanto
  para pedidos de confirmação do Policy Engine.
- **Permitido conhecer:** canais de entrega e sua política de prioridade.
- **Proibido conhecer:** o motivo de negócio pelo qual a notificação foi
  disparada — recebe um `Notification` já formado.
- **Entradas:** `Notification` (mensagem, prioridade, canal, flag de pedido
  de confirmação).
- **Saídas:** confirmação de entrega; se aplicável, evento de resposta do
  usuário.
- **Dependências permitidas:** Domain (`Notification`), ports de canal.
- **Dependências proibidas:** Agent Runtime, Memory, lógica de negócio de
  Policy.
- **Responsável:** Notification System.

### 3.11 Persistence
- **Responsabilidade:** não é um componente com comportamento de negócio —
  é a regra transversal do §11.
- **Responsável:** cada Repository port/adapter individual.

### 3.12 Configuration
- **Responsabilidade:** configuração técnica de sistema, carregada uma vez
  na composition root — ver detalhamento completo em §12.
- **Permitido conhecer:** nada (é folha da árvore de dependências).
- **Proibido:** ser consultada ad hoc por código de Core/Application em vez
  de receber a configuração já injetada.
- **Responsável:** Configuration.

---

## 4. LLM Independence

Ver [ADR-0002](adr/0002-llm-provider-abstraction.md).

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Prompt assembly** | feito pelo Agent Runtime (via `PromptBuilder` do Core) | — | acontecer dentro de um adapter de Infrastructure |
| **Definição de tools expostas ao LLM** | descrita em schema genérico pelo Skill Registry | traduzida para o formato do vendor **somente** dentro do adapter | Core conhecer o formato de tool específico de um vendor |
| **Interpretação da resposta em `Decision`** | feita no Core, sobre representação genérica de resposta | — | Core fazer parsing de JSON/formato específico de vendor |
| **Erros de LLM** | mapeados pelo adapter para a taxonomia do Core (`LLMTimeoutError`, `LLMRateLimitError`, `LLMProviderError`, `LLMInvalidResponseError`) | adapter capturar exceções do SDK do vendor | Core capturar exceção de SDK de vendor diretamente |
| **Troca de provider** | implementar novo adapter de `LLMProvider` + selecionar via configuração | coexistência de múltiplos adapters registrados | qualquer mudança em Agent Runtime, `PromptBuilder`, `Decision` ou Skills para trocar de provider |
| **Embeddings** | Memory depende de um port `EmbeddingProvider` próprio, distinto de `LLMProvider` | o mesmo vendor implementar ambos os ports | Memory depender diretamente de `LLMProvider` |

**Responsável:** Agent Runtime é dono do contrato `LLMProvider`; Memory é
dona do contrato `EmbeddingProvider`. Nenhum dos dois compartilha
implementação por acoplamento — só por coincidência de vendor, se ocorrer.

---

## 5. Event Contract

Ver [ADR-0004](adr/0004-event-immutability-and-timestamps.md).

**Campos obrigatórios:** `event_id` (identificador único), `event_type`
(namespaced, ex. `email.received`), `occurred_at`, `source`, `payload`,
`schema_version`.

**Campos opcionais:** `correlation_id` (default: o próprio `event_id`),
`causation_id`, `metadata` (bag livre, **nunca** usado em lógica de
negócio).

| Aspecto | Regra |
|---|---|
| **Semântica dos timestamps** | `occurred_at` é o tempo de domínio (quando o fato ocorreu, fornecido/estimado pela source). `recorded_at` é atribuído **pelo Event Store** no momento em que o evento é persistido — não é definido nem editável pelo producer. |
| **Ordenação** | O Event Store garante uma **ordenação de persistência consistente para seus consumidores** a partir de `recorded_at`. Isso **não** é uma garantia de relógio monotônico absoluto — é uma garantia de ordem de leitura estável fornecida pelo store. Ordem causal real usa `occurred_at` + `causation_id`/`correlation_id`, não a posição no stream. |
| **Identificação da origem** | `source` identifica de onde o evento veio (ex. `gmail-watcher`, `manual-cli`); usado para filtragem e confiança. |
| **Versionamento** | `schema_version` é por `event_type`; consumidores devem tratar explicitamente versões desconhecidas/antigas (upcast ou ignorar), nunca assumir a versão mais recente. |
| **Idempotência** | Producers devem, quando possível, gerar `event_id` determinístico a partir de uma chave natural da source. O Event Store trata inserção duplicada de `event_id` como no-op, não como erro fatal. |
| **Correlação** | `correlation_id` agrupa toda uma cadeia causal (evento → decisão → ação → evento de resultado). `causation_id` aponta o evento pai direto. |
| **Imutabilidade** | Um evento persistido nunca é alterado. Correções são modeladas como novos eventos com `causation_id` apontando para o original (ex. `email.received.retracted`), nunca como update in-place. |

**Responsável:** Event System é dono do contrato `Event` e do `EventStore`;
todo producer de evento (Event Sources em Infrastructure) deve respeitá-lo.

---

## 6. Context Contract

| Aspecto | Regra |
|---|---|
| **Natureza** | `CurrentContext` **não é fonte de verdade** — é uma projeção derivada de Events + Context Providers, reconstruível. Events e Memory são a fonte de verdade. |
| **Atual vs. histórico** | `CurrentContext` = últimos valores conhecidos por campo. `ContextSnapshot` = captura imutável e datada, usada para reconstrução histórica (ex. "o que o agente sabia quando decidiu X"). |
| **Metadados por campo** | cada campo carrega valor, `observed_at`, `source`, `confidence`. |
| **Validade/TTL** | TTL é definido **por tipo de campo** (ex. localização expira em minutos; calendário expira no próximo poll), nunca um TTL global único. |
| **Dados desatualizados** | dado além do TTL é marcado `stale`, nunca descartado silenciosamente. Decidir se um dado `stale` é aceitável é responsabilidade de quem consome o contexto (ex. Agent Runtime), não do Context Engine. |
| **Conflito entre providers** | regra padrão: `observed_at` mais recente vence por campo. O conflito é sempre registrado, nunca descartado silenciosamente. Resolução plugável por campo fica para quando houver necessidade concreta — não faz parte deste contrato. |
| **Origem** | um campo sem dado é `None`/ausente. O Context Engine nunca infere ou inventa um valor para um campo sem dado. |

**Responsável:** Context Engine.

---

## 7. Memory Contract

**Tipos:** episódica, semântica, preferência, procedural, working memory,
task memory.

**Metadados obrigatórios:** `memory_id`, `type`, `content`, `created_at`,
`updated_at`, `last_accessed_at`, `importance`, `confidence`, `source`.

**Metadados opcionais:** `valid_from`, `valid_until`, `entities`, `tags`,
`embedding` (quando presente, deve registrar qual `EmbeddingProvider`/versão
gerou o vetor — vetores de modelos diferentes não são comparáveis; trocar o
modelo de embedding não pode corromper a busca silenciosamente).

| Conceito | Definição | Onde é usado |
|---|---|---|
| **`importance`** | peso atribuído à memória (quanto ela deveria pesar na recuperação/decaimento) | armazenado na memória |
| **`confidence`** | quão certo o sistema está de que o conteúdo é verdadeiro/preciso | armazenado na memória |
| **`relevance`** | score de recuperação, combinando importance + recência + confidence + match da query | **calculado em tempo de retrieval, nunca armazenado** |

Working memory e task memory podem (mas não precisam) usar um backend mais
barato ou TTL mais curto que memória episódica/semântica — decisão de
implementação da Fase 3, não deste contrato.

**Responsável:** Memory System.

---

## 8. Skill Contract

### 8.1 Distinção de conceitos

Ver [ADR-0005](adr/0005-skill-tool-mcp-distinction.md).

| Conceito | O que é |
|---|---|
| **Tool** | capacidade atômica, stateless, com schema fixo de entrada/saída (ex. `send_email(to, subject, body)`). Corresponde ~1:1 a uma tool MCP. |
| **MCP Server** | processo externo que expõe uma ou mais Tools via protocolo MCP — detalhe de implementação de onde uma Tool mora. |
| **MCP Tool** | representação de wire-level de uma Tool, como descoberta via protocolo MCP. |
| **Skill** | capacidade de nível mais alto que o agente decide invocar — pode compor múltiplas Tools; carrega validação de input, classificação de risco e política de confirmação **próprias**. Não é sinônimo de função. |

### 8.2 Contrato conceitual de Skill

Campos: `name`/`skill_id`, `input schema`, `output schema`, `capabilities`
(tags declarativas, ex. `email:send`), `permissions` (escopos necessários),
`risk` (nível de risco), `confirmation_requirement`, `execution_context`
(dados recebidos explicitamente — a Skill não busca Context/Memory por
conta própria), `errors` (taxonomia própria, mapeada no §13).

### 8.3 Entrada/saída

- **Entrada obrigatória:** parâmetros já validados contra o `input schema`
  da Skill, entregues **somente após** aprovação do Policy Engine.
- **Saída obrigatória:** `SkillResult` (sucesso) ou `SkillError` (falha),
  conforme taxonomia do §13.

### 8.4 `risk` e `confirmation_requirement` não concedem autorização

> **Regra explícita, sem exceção:** `risk` e `confirmation_requirement` são
> **declarações/metadados fornecidos pela própria Skill** — a Skill descreve
> o que ela acredita ser o seu risco e sob qual condição deveria exigir
> confirmação. Essas declarações **nunca concedem autorização à Skill**.
>
> A decisão efetiva de `allow`, `deny` ou `require_confirmation` pertence
> **exclusivamente ao Policy Engine** (§10), que pode inclusive divergir da
> autodeclaração da Skill (ex. aplicar uma denylist estática mais restritiva
> que o risco autodeclarado).

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Skill** | declarar `risk` e `confirmation_requirement` honestamente | usar essas declarações como input para a decisão do Policy Engine | tratar sua própria declaração como autorização e executar sem passar pelo Policy Engine |
| **Policy Engine** | ser a única autoridade que decide `allow`/`deny`/`require_confirmation` | ignorar ou sobrepor a autodeclaração da Skill quando a política exigir | delegar essa decisão de volta à Skill ou ao LLM |

**Responsável:** Policy Engine é o único responsável pela decisão de
autorização; a Skill é responsável apenas pela precisão da sua própria
declaração de metadados.

---

## 9. Tool / MCP Boundary

```text
Agent → Skill → Tool Router → MCP Client → MCP Server → Tool
```

| Aspecto | Onde ocorre | Regra |
|---|---|---|
| **Validação de negócio** | Skill | valida regras de negócio do próprio domínio antes de qualquer chamada de Tool |
| **Validação de schema técnico** | Tool Router / MCP Client | valida contra o schema anunciado pelo MCP, imediatamente antes do dispatch — concern diferente da validação de negócio, não é redundante |
| **Permissão** | Policy Engine, **antes** de a Skill executar | ver §10.3 (`PolicyApproval`) |
| **Timeout** | Tool Router, por chamada | uma Skill que compõe várias Tools pode ter orçamento de tempo adicional próprio |
| **Normalização de erros** | limite MCP Client → Tool Router | erros de transporte/protocolo viram `ToolTimeoutError`, `ToolNotFoundError`, `ToolExecutionError`, `ToolInvalidInputError`; Skills e Agent Runtime nunca veem erro cru de MCP/JSON-RPC |
| **Registro de execução** | Tool Router (choke point único) | toda invocação (input, resultado/erro, duração, `correlation_id`) é registrada em um único lugar — Skills não implementam logging próprio |
| **Descoberta de ferramentas** | MCP Client descobre; Tool Router mantém o registry lógico nome→backend | o contrato de `Tool` não assume MCP como único backend possível no futuro, mesmo que seja o único implementado na Fase 5 |

**Responsável:** Tool Router é dono da normalização de erros, timeout e
registro de execução; MCP Client é dono do protocolo; Skill é dona da
validação de negócio.

---

## 10. Policy e Safety Boundary

Ver [ADR-0003](adr/0003-policy-engine-safety-authority.md).

### 10.1 Propriedade central

**O LLM não é a autoridade final de segurança.** O Agent Runtime pode propor
uma `Decision.act`, mas apenas o Policy Engine — código/configuração
determinística, sem chamada de LLM envolvida na decisão — decide se a ação
acontece.

### 10.2 Fluxo

```text
Decision.act(skill, params)
        ↓
  Policy Engine avalia:
   - risco/permissão declarados pela Skill (ver §8.4)
   - contexto atual
   - regras de política configuradas
   - denylist estática
        ↓
  PolicyVerdict:
   - allow                 → execução prossegue
   - require_confirmation  → Notification pede confirmação; resposta do
                              usuário chega como evento; Policy decide então
   - deny                  → execução bloqueada; Agent Runtime é informado
```

### 10.3 `PolicyApproval`

> `PolicyApproval` é um **conceito/objeto de domínio** que representa uma
> autorização emitida pelo Policy Engine para uma execução específica
> (Skill + parâmetros). Uma Skill só deve poder executar sua parte de risco
> tendo recebido um `PolicyApproval` correspondente — isso torna
> estruturalmente mais difícil pular a checagem de política, em vez de
> depender apenas de disciplina de código.
>
> Este documento **não define** o mecanismo concreto de `PolicyApproval`
> (token opaco, JWT, assinatura criptográfica, objeto em memória, etc.).
> Essa é uma decisão de implementação a ser tomada na Fase 5, não um
> contrato arquitetural.

### 10.4 Denylist e auditoria

- Uma denylist estática vale **independentemente** do risco autodeclarado
  pela Skill (cinto e suspensório).
- Todo `PolicyVerdict` e toda execução real de Tool são registrados via
  `AuditLog` port, com `correlation_id`, timestamp, ator, decisão e
  resultado — consultável posteriormente.

**Responsável:** Policy Engine.

---

## 11. Persistence Boundary

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Domain / Application** | expressar toda necessidade de persistência como Repository port (`EventStore`, `MemoryRepository`, `ContextSnapshotRepository`, `AuditLogRepository`, etc.) | receber/retornar entidades de domínio dos repositories | importar driver de banco, ORM ou biblioteca de acesso a dados concreta |
| **Infrastructure** | implementar os Repository ports com a tecnologia escolhida por fase | mapear entidade ↔ representação de armazenamento internamente ao adapter | expor tipos/objetos específicos do banco (linhas de ORM, cursors) para fora do adapter |

Nenhum banco de dados é escolhido neste documento. A escolha concreta
(SQLite, PostgreSQL, outro) é decisão de cada fase de implementação e deve
permanecer trocável sem alterar Domain/Application, exatamente por causa
desta regra.

**Responsável:** cada Repository port/adapter individual é responsável por
sua própria implementação; a regra de não vazar tipos de infraestrutura é
responsabilidade de quem escreve o adapter.

---

## 12. Configuration Boundary

Quatro categorias que não podem se misturar:

| Categoria | O que é | Onde vive | Exemplo |
|---|---|---|---|
| **Configuração de sistema** | técnica, deploy-time, estática | `Settings` (`pydantic-settings`, já existente, prefixo `JARVIS_`) | `JARVIS_LOG_LEVEL`, seleção de LLM provider |
| **Secrets** | mesmo mecanismo de config de sistema, regras adicionais | env / `.env`, nunca logado, sempre redigido em audit logs | `JARVIS_*_API_KEY` |
| **Preferências do usuário** | aprendidas dinamicamente, com proveniência e confidence, mutáveis pelo próprio agente em runtime | Memory (tipo preferência) — **não** em `Settings` | "não notificar depois das 22h" |
| **Estado** | operacional/efêmero, específico de cada componente | junto do componente dono, não em um `Settings` global | "último event offset processado" |

Memória em si (episódica, semântica, procedural) já é coberta pelo §7 e não
é uma categoria de configuração.

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Configuração** | ser carregada uma vez, na composition root, e injetada explicitamente nos componentes que precisam dela | um entry point (CLI, daemon) carregar `Settings` diretamente ao iniciar | código de Core/Application chamar `load_settings()` (ou equivalente) internamente em vez de receber configuração já injetada |
| **Secrets** | nunca aparecer em log, evento, payload de memória ou audit log em texto claro | ser lido do mesmo mecanismo de env/`.env` | ser persistido em Memory ou em qualquer store de domínio |
| **Preferências** | ser modeladas como Memory, com `confidence`/`source`/histórico | ser lidas pelo Agent Runtime como qualquer outra memória | viver em `Settings` ou em arquivo de configuração estático |

**Responsável:** Configuration é dona da configuração de sistema/secrets;
Memory System é dona das preferências; cada componente é dono do seu
próprio estado operacional.

---

## 13. Error Contract

**Categorias:** `DomainError`, `InfrastructureError`, `ProviderError` (LLM/
MCP/API externa), `TimeoutError` (transversal), `PolicyDenied` (não é uma
falha — é uma negação deliberada), `UserFacingError` (mensagem segura para
o usuário, distinta do detalhe interno completo).

| | Obrigatório | Permitido | Proibido |
|---|---|---|---|
| **Classificação retryable/permanent** | toda categoria de erro do Core declara se é retryable (timeout, rate limit) ou permanent (input inválido, permissão negada) | lógica de retry em qualquer parte do sistema consultar essa classificação | cada componente inventar seu próprio critério de retry |
| **Tradução de exceções** | adapters de Infrastructure capturam exceções específicas de vendor/biblioteca e relançam como o tipo de erro do Core correspondente | adapter conhecer detalhes da exceção nativa do vendor | Core capturar uma exceção nativa de vendor diretamente |
| **Mensagens ao usuário** | Agent Runtime/Notification System decidem o que é seguro mostrar ao usuário | mostrar mensagem genérica + logar detalhe completo internamente | expor stack trace ou detalhe interno diretamente ao usuário |

**Responsável:** cada adapter de Infrastructure é responsável por traduzir
seus próprios erros; o Core é responsável por definir e manter a taxonomia
compartilhada.

---

## 14. Observability Contract

| Aspecto | Regra |
|---|---|
| **`correlation_id`** | propagado de `Event` → `Decision` → `PolicyVerdict` → execução de Skill/Tool → `Event` de resultado. É a espinha dorsal que liga um fluxo inteiro nos logs. |
| **`causation_id`** | liga um passo ao seu evento/decisão pai direto, dentro do fluxo identificado por `correlation_id`. |
| **Logs** | estruturados, não texto livre; um registro por passo relevante, sempre com `correlation_id` + nome do componente + timestamp. |
| **Audit log** | categoria separada e com retenção mais rígida que logs de debug; sempre durável; atrelada especificamente a vereditos do Policy Engine e execuções do Tool Router — não a toda linha de debug. |
| **Métricas / tracing distribuído** | fora de escopo por agora. Para um agente pessoal em processo único, `correlation_id` + log estruturado é suficiente; infraestrutura de tracing (ex. OpenTelemetry) seria prematura neste estágio. |

**Responsável:** cada componente emite seus próprios logs propagando
`correlation_id`/`causation_id` recebidos; Policy Engine e Tool Router são
donos do audit log.

---

## 15. Decisões registradas como ADR

As decisões abaixo são difíceis de reverter depois que houver código real e
por isso têm registro próprio em [`adr/`](adr/), com contexto e
consequências completas:

- [ADR-0001](adr/0001-ports-and-adapters-dependency-rule.md) — Ports &
  Adapters como regra de dependência.
- [ADR-0002](adr/0002-llm-provider-abstraction.md) — Abstração de LLM
  Provider e separação de Embedding Provider.
- [ADR-0003](adr/0003-policy-engine-safety-authority.md) — Policy Engine
  como autoridade determinística de segurança.
- [ADR-0004](adr/0004-event-immutability-and-timestamps.md) — Imutabilidade
  de evento e semântica de timestamps.
- [ADR-0005](adr/0005-skill-tool-mcp-distinction.md) — Distinção entre
  Skill, Tool, MCP Server e MCP Tool.
- [ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md) —
  Configuração vs. Secrets vs. Preferências vs. Estado.
- [ADR-0007](adr/0007-sqlite-event-store.md) — SQLite como armazenamento do
  Event Store (Fase 1).
- [ADR-0008](adr/0008-synchronous-in-process-event-bus.md) — Event Bus
  síncrono em processo (Fase 1).
- [ADR-0009](adr/0009-sqlite-memory-storage.md) — SQLite como armazenamento do
  Memory System (Fase 3).
- [ADR-0010](adr/0010-immutable-memory-and-supersession.md) — Memória
  imutável, com supersessão em vez de sobrescrita (Fase 3).

Decisões de campo-a-campo (schema exato de Event/Context/Memory, nomes
exatos da taxonomia de erro) **não** viram ADR — são detalhe de contrato,
revisável sem implicação arquitetural, e vivem só neste documento.
