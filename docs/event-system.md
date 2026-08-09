# Event System

> Documentação conceitual do Event System, previsto para a **Fase 1** do
> [roadmap](../ROADMAP.md). Criada na subfase **0.5** como explicação de um
> contrato já aprovado na 0.3 — **não implementa** nenhum dos conceitos
> abaixo. O contrato normativo completo está em
> [`architecture-contracts.md §5`](architecture-contracts.md#5-event-contract)
> e em [ADR-0004](adr/0004-event-immutability-and-timestamps.md); este
> documento explica o *porquê* e o *como se relaciona*, sem repetir a tabela
> de campos.

## Por que um Event System

O Event System é o componente que primeiro toca tudo que acontece no mundo
digital/físico observável pelo Jarvis — um email chegando, o usuário
abrindo uma aplicação, uma reunião se aproximando. Ele existe para
transformar esses acontecimentos brutos em **fatos estruturados e
imutáveis** que o resto do sistema (Context Engine, Memory, Agent Runtime)
pode consumir sem precisar conhecer a fonte original de cada um. Ver visão
geral em [architecture.md §2](architecture.md#2-visão-de-alto-nível).

## Conceitos

- **Event** — um fato imutável: algo que aconteceu, com identidade
  (`event_id`), tipo (`event_type`), quando aconteceu (`occurred_at`) e o
  que aconteceu (`payload`). Uma vez persistido, nunca é alterado —
  correções são novos eventos, nunca update in-place (ver §4).
- **Event Source** — de onde um evento se origina (ex. `gmail-watcher`,
  `manual-cli`). É um adapter de Infrastructure, não um componente do Core:
  o Event System não sabe "como" um watcher de Gmail funciona, só recebe o
  `Event` já estruturado que ele produz.
- **Event Bus** — o mecanismo de publicação/assinatura que entrega um
  evento recém-emitido a quem estiver consumindo em tempo real (Fase 1.2).
- **Event Store** — o registro persistente e consultável de todos os
  eventos, por tipo, por janela temporal ou por `correlation_id` (Fase
  1.3). É o Event Store, e só ele, que atribui `recorded_at` (§4).
- **Event Consumer** — qualquer componente a jusante (tipicamente o
  Context Engine, futuramente outros) que assina o Event Bus ou consulta o
  Event Store para reagir a eventos (Fase 1.4). Um Consumer nunca modifica
  um evento — só lê e produz efeitos próprios (ex. atualizar contexto).

## Correlation e Causation

Um único acontecimento no mundo real costuma gerar uma cadeia de eventos
relacionados: um email chega (`email.received`) → o agente decide agir
(`Decision.act`) → uma resposta é enviada (`email.sent`) → isso por sua vez
é observado como um novo evento. Dois campos amarram essa cadeia sem
depender de posição no tempo:

- **`correlation_id`** agrupa toda a cadeia causal inteira — todo evento,
  decisão e ação que nasceram, direta ou indiretamente, do mesmo
  acontecimento original compartilham o mesmo `correlation_id`. Por
  padrão, um evento raiz usa seu próprio `event_id` como `correlation_id`.
- **`causation_id`** aponta apenas para o evento/decisão **pai direto** —
  o passo imediatamente anterior na cadeia, não a raiz inteira.

Essa distinção é o que permite reconstruir "por que o Jarvis fez X" sem
depender da ordem física de gravação no Event Store — ver
[architecture.md §8](architecture.md#8-observabilidade-cross-cutting).

## Idempotência

Sources podem, por retry de rede ou reprocessamento de um watcher, tentar
emitir o "mesmo" evento mais de uma vez. Em vez de tratar isso como um
problema para cada consumidor resolver individualmente, o contrato empurra
a responsabilidade para a origem: sempre que possível, o `event_id` é
derivado deterministicamente de uma chave natural da source (ex. o
Message-ID de um email), e o Event Store trata a reinserção do mesmo
`event_id` como **no-op**, não como erro. Isso evita que um evento seja
processado duas vezes pelo simples fato de ter sido observado duas vezes.

## `occurred_at` vs. `recorded_at`

Estes são dois timestamps com donos diferentes, e a distinção é
deliberada:

| | `occurred_at` | `recorded_at` |
|---|---|---|
| **O que representa** | tempo de domínio — quando o fato realmente aconteceu | tempo de persistência — quando o Event Store gravou o evento |
| **Quem define** | o producer (a Event Source), fornecido ou estimado | o Event Store, no momento em que persiste |
| **Pode ser editado pelo producer depois?** | não (imutável após persistido) | nunca — não é nem visível ao producer como campo de escrita |
| **Exemplo de divergência** | email marcado como recebido às 14:00 | watcher só processou e persistiu o evento às 14:05, por atraso de polling |

A ordenação de leitura que o Event Store garante aos seus consumidores é
baseada em `recorded_at` — mas essa é uma garantia de **ordem de leitura
estável para quem lê do mesmo store**, não uma alegação sobre relógio
monotônico global. Dois Event Stores diferentes, ou dois producers com
clock skew entre si, não têm essa garantia entre si. Ordem causal de
domínio real usa `occurred_at` combinado com `causation_id`/`correlation_id`
— nunca a posição de um evento no stream como prova de causalidade.

## Relação com o resto do sistema

O Event System não conhece Context Engine, Memory, Agent Runtime, Skills
ou Policy — ele só produz e armazena `Event`s (ver limites em
[`architecture-contracts.md §3.1`](architecture-contracts.md#31-event-system)).
É o Context Engine, como consumidor, que decide o que fazer com cada
evento — ver [context-system.md](context-system.md).

## Documentos relacionados

- Contrato normativo completo: [architecture-contracts.md §5](architecture-contracts.md#5-event-contract)
- Decisão de imutabilidade e timestamps: [ADR-0004](adr/0004-event-immutability-and-timestamps.md)
- Regras de criação de Events para sessões futuras: [CLAUDE.md §6](../CLAUDE.md)
- Visão geral: [architecture.md](architecture.md)
