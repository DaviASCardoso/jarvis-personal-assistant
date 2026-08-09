# 0004. Imutabilidade de evento e semântica de timestamps

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

O Event System (Fase 1) é a base de todo o resto do sistema — Context,
Memory e Agent Runtime dependem, direta ou indiretamente, de conseguir
confiar na ordem e na integridade dos eventos. Duas decisões sobre o
contrato de `Event` são particularmente caras de mudar depois que o Event
Store já tiver dados reais: se eventos podem ser alterados após persistidos,
e o que exatamente um "timestamp" de evento significa.

Sobre timestamps especificamente: um evento pode ter um tempo de domínio
diferente do tempo em que o Jarvis efetivamente tomou conhecimento dele (ex.
um email marcado como recebido às 14:00, mas só processado pelo watcher às
14:05 por atraso de polling). Tratar isso como um único timestamp obriga a
escolher entre precisão de domínio e ordenação confiável de consumo — as
duas coisas que o sistema precisa, para propósitos diferentes.

## Decisão

- **Imutabilidade:** um evento persistido nunca é alterado. Correções ou
  retratações são modeladas como novos eventos com `causation_id` apontando
  para o evento original (ex. `email.received.retracted`), nunca como
  update in-place.
- **Dois timestamps, dois donos:**
  - `occurred_at` é o tempo de domínio — quando o fato realmente aconteceu,
    fornecido/estimado pela source. É definido pelo producer do evento.
  - `recorded_at` é atribuído **pelo Event Store** no momento da
    persistência — não é definido nem editável pelo producer.
- **Ordenação:** o Event Store garante uma **ordenação de persistência
  consistente para os seus consumidores**, baseada em `recorded_at`. Isso é
  deliberadamente uma garantia mais fraca do que "relógio monotônico
  absoluto" — é uma garantia de que consumidores lendo do mesmo store veem
  uma ordem estável, não uma alegação sobre `recorded_at` como fonte de
  tempo real global. Ordem causal de domínio usa `occurred_at` combinado com
  `causation_id`/`correlation_id`, não a posição no stream.
- **Idempotência:** producers devem, quando possível, derivar `event_id` de
  forma determinística a partir de uma chave natural da source, para que
  reingestão não duplique eventos; o Event Store trata inserção duplicada de
  `event_id` como no-op.

Detalhamento em
[`architecture-contracts.md §5`](../architecture-contracts.md#5-event-contract).

## Alternativas consideradas

- **Um único timestamp** (`timestamp`, atribuído pelo producer): descartada
  — obriga a escolher entre tempo de domínio e ordem de consumo confiável;
  clock skew do lado do producer contaminaria a ordenação usada por todos os
  consumidores.
- **`recorded_at` como garantia de relógio monotônico global** (útil, por
  exemplo, se o Event Store fosse distribuído): descartada por ora —
  garantir monotonicidade absoluta tem custo de implementação real (ex.
  clocks lógicos, coordenação) que não se justifica para um Event Store de
  processo único de um agente pessoal. A garantia adotada (ordenação de
  persistência consistente para consumidores do mesmo store) é suficiente
  para os casos de uso previstos e mais barata.
- **Eventos mutáveis com histórico de versão** (update in-place + log de
  mudanças): descartada — reintroduz a complexidade que o padrão
  event-sourcing (append-only) existe para evitar, sem benefício adicional
  aqui.

## Consequências

- O Event Store pode ser implementado como um log append-only simples,
  sem necessidade de suportar update/lock de linha existente.
- Consumidores podem confiar na ordem de leitura do store sem precisar
  reconciliar clock skew entre sources diferentes.
- Fica mais fácil auditar "o que o sistema sabia e quando" — nada desaparece
  ou muda de baixo dos pés de um consumidor que já processou um evento.
- Não resolve, por si só, o schema de payload por `event_type` nem a
  estratégia de armazenamento (SQLite vs. outro) — decisões da Fase 1,
  não deste ADR.
