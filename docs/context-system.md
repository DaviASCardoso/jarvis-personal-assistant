# Context Engine

> Documentação conceitual do Context Engine, previsto para a **Fase 2** do
> [roadmap](../ROADMAP.md). Criada na subfase **0.5** como explicação de um
> contrato já aprovado na 0.3 — **não implementa** nenhum dos conceitos
> abaixo. O contrato normativo completo está em
> [`architecture-contracts.md §6`](architecture-contracts.md#6-context-contract);
> este documento explica o *porquê* e o *como se relaciona*, sem repetir a
> tabela de campos.

## Por que um Context Engine

O Agent Runtime precisa saber "o que está acontecendo agora" para
raciocinar de forma útil — mas eventos brutos (§[event-system.md](event-system.md))
são um stream de fatos pontuais, não um estado consultável. O Context
Engine existe para transformar esse stream (mais dados de providers, como
relógio ou calendário) em uma **projeção consultável do presente**: "o
usuário está em reunião", "são 22h", "o dispositivo ativo é o notebook".

## `CurrentContext` vs. `ContextSnapshot`

- **`CurrentContext`** é o "agora": os últimos valores conhecidos, por
  campo (`UserContext`, `EnvironmentContext`, `DeviceContext`,
  `ActivityContext`, `ScheduleContext`, `ConversationContext`,
  `TaskContext` — ver [ROADMAP.md §2.1](../ROADMAP.md)). Consultado a
  cada ciclo de raciocínio do Agent Runtime.
- **`ContextSnapshot`** é uma captura imutável e datada do `CurrentContext`
  em um instante específico, usada para reconstrução histórica — por
  exemplo, para responder "o que o agente sabia quando decidiu X" ao
  auditar uma decisão passada (ver [security.md](security.md) sobre
  auditabilidade).

**`CurrentContext` não é fonte de verdade** — é uma projeção derivada de
Events + Context Providers, reconstruível a partir deles. Events e Memory
são a fonte de verdade; o Context Engine apenas mantém uma vista
conveniente e atualizada sobre eles.

## Fontes de contexto

Um `ContextProvider` é a abstração (port) através da qual o Context Engine
recebe dados — de eventos (via assinatura do Event Bus) ou de polls diretos
(Time Provider, Device Provider, Calendar Provider, Location Provider — ver
[ROADMAP.md §2.2](../ROADMAP.md)). O Context Engine não sabe como cada
provider concreto obtém seu dado (chamada de API, leitura de sensor,
cálculo local) — só consome a interface do port.

## Freshness, TTL e confiança

Cada campo do `CurrentContext` carrega metadados próprios, não um único
metadado global para o objeto inteiro:

- **`observed_at`** — quando aquele valor específico foi observado.
- **`source`** — qual provider ou evento originou o valor.
- **`confidence`** — o quão confiável o Context Engine considera aquele
  valor.

O **TTL é por tipo de campo**, nunca um TTL único para todo o contexto:
localização expira em minutos; um dado de calendário expira só no próximo
poll. Um campo além do seu TTL é marcado **`stale`**, nunca descartado
silenciosamente — decidir se um dado `stale` ainda é aceitável para uma
decisão específica é responsabilidade de quem consome o contexto (tipicamente
o Agent Runtime), não do Context Engine. Um campo sem dado nenhum é
`None`/ausente — o Context Engine nunca infere ou inventa um valor.

## Conflitos entre fontes

Quando dois providers (ou um provider e um evento) reportam valores
diferentes para o mesmo campo, a regra padrão é: **`observed_at` mais
recente vence**, por campo. O conflito em si é sempre registrado — nunca
descartado silenciosamente, mesmo quando resolvido automaticamente.
Resolução de conflito plugável por campo (ex. uma estratégia diferente de
"mais recente vence" para um campo específico) fica para quando houver
necessidade concreta; não faz parte deste contrato ainda.

## Diferença entre estado atual e histórico

O `CurrentContext` responde "o que é verdade agora, pelo que sabemos". O
`ContextSnapshot` responde "o que era verdade — ou o que o sistema
acreditava ser verdade — em um instante específico do passado". Essa
distinção importa porque o Agent Runtime raciocina sempre sobre o
`CurrentContext` do momento da decisão, mas auditoria e depuração
("por que o agente decidiu isso?") dependem de poder reconstruir esse
mesmo instante depois — o que só um snapshot imutável permite.

## Contexto não é memória

É tentador tratar contexto e memória como a mesma coisa — ambos "o sistema
sabendo algo sobre o usuário". A diferença é o ciclo de vida:

| | Context | Memory |
|---|---|---|
| **Horizonte** | presente, expira por TTL | durável, decai/reforça ao longo do tempo |
| **Fonte** | eventos recentes + providers | consolidação, experiência, retrieval |
| **Papel na decisão** | "o que está acontecendo agora" | "o que o sistema aprendeu/deveria lembrar" |

Eventos e memória **podem contribuir para** o contexto (ex. uma preferência
lembrada pode influenciar como um campo de contexto é interpretado), mas o
Context Engine não é dono de memória, e a Memory System não é dona de
projeção de estado atual — ver [memory-system.md](memory-system.md) para o
contrato de memória e a distinção de `relevance` vs. `importance`.

## Documentos relacionados

- Contrato normativo completo: [architecture-contracts.md §6](architecture-contracts.md#6-context-contract)
- Limites do componente: [architecture-contracts.md §3.2](architecture-contracts.md#32-context-engine)
- Visão geral: [architecture.md](architecture.md)
