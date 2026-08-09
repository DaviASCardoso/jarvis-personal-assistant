# 0008. Event Bus síncrono em processo

**Status:** Accepted
**Data:** 2026-08-09

## Contexto

A subfase [1.2 do roadmap](../../ROADMAP.md) pede que o Event Bus implemente
`publish`, `subscribe`, consumo, **acknowledgement**, **retry** e tratamento de
falhas; a 1.4 acrescenta "processamento assíncrono quando necessário" e
"dead-letter". Lidos isoladamente, esses itens descrevem um message broker.

Ao mesmo tempo, a regra 11 do próprio roadmap ("não adicionar infraestrutura
complexa sem necessidade concreta") e
[`architecture-contracts.md §1`](../architecture-contracts.md#1-princípios-e-escopo)
proíbem infraestrutura e abstração especulativas. Na Fase 1 existe exatamente um
consumidor (um consumer de logging); o Context Engine, primeiro consumidor real,
só chega na Fase 2.

A tensão precisa ser resolvida explicitamente porque a escolha contamina todo
consumidor futuro: o modelo de execução do bus define como Context, Memory e Agent
Runtime serão escritos.

## Decisão

O Event Bus é **síncrono e em processo**, e sua semântica de entrega é:

- **Dispatch**: `publish` entrega o evento a cada consumer inscrito, em ordem de
  inscrição, na thread de quem publicou. Um consumer pode filtrar por `event_type`.
- **Acknowledgement**: retornar normalmente de `handle` é o ack; levantar exceção é
  a recusa. Não existe API de ack manual — o resultado da chamada já é o sinal.
- **Retry**: `RetryPolicy(max_attempts, delay)` por inscrição, com default de uma
  tentativa (sem retry). A função de espera é injetável, para que testes não durmam.
- **Isolamento**: a falha de um consumer não impede os demais nem propaga para quem
  publicou. Um evento registrado é um fato histórico; falhar em reagir a ele não o
  desfaz.
- **Dead letter**: esgotadas as tentativas, a falha vira um `DeadLetter` entregue a
  um handler injetado, cujo default apenas registra em log. Não há fila persistente.
- **Assincronia**: não implementada. "Quando necessário" é a condição posta pelo
  próprio roadmap, e não é necessário nesta fase — nenhum consumer faz I/O
  bloqueante.

O bus **não é um port**: existe uma única implementação e nenhuma necessidade de
substituí-la, então um `Protocol` seria abstração sem consumidor real. O Event
Store, em contraste, é port porque o contrato §11 exige que o domínio não conheça a
tecnologia de persistência.

## Alternativas consideradas

- **Bus baseado em `asyncio`**: descartada por ora. Mudaria o modelo de execução de
  todo o sistema (CLI, store, consumers futuros) para resolver um problema que não
  existe: nenhum consumer da Fase 1 é I/O-bound, e o Event Store é síncrono. Adotar
  async depois é caro — mas adotá-lo agora seria pagar esse custo sem contrapartida
  e ainda assim ter que revisitá-lo quando houvesse requisito real.
- **Broker externo (Redis Streams, NATS, RabbitMQ)**: descartada. Traz durabilidade
  de fila, consumo entre processos e replay — nada disso com consumidor nesta fase —
  ao custo de um serviço externo em um agente pessoal de processo único. Também
  duplicaria a responsabilidade do Event Store, que já é o registro durável.
- **Sem retry nem dead-letter, só propagar a exceção**: descartada por contrariar
  explicitamente ROADMAP 1.2 e 1.4, e por transformar a falha de um consumer em
  falha do registro do evento.
- **Bus e Store como um componente só** (persistir e notificar no mesmo objeto):
  descartada — `PHASE-1.md §13` separa as duas perguntas ("o que foi registrado?" e
  "quem precisa processar isto?"), e juntá-las tornaria impossível trocar a
  persistência sem tocar na distribuição.

## Consequências

- Consumers são funções síncronas simples, triviais de testar sem event loop.
- A ordem de entrega é determinística, o que torna os testes de integração
  verificáveis sem sincronização.
- Um consumer lento ou travado bloqueia a publicação. Aceitável enquanto o único
  produtor for o CLI; passa a ser um problema quando houver watchers contínuos, e é
  esse o gatilho concreto para reavaliar esta decisão.
- Migrar para async ou para um broker depois exigirá tocar em todos os consumers
  existentes — por isso a decisão está registrada aqui, e não escondida no código.
- Não resolve entrega garantida entre reinícios: um evento persistido cujo consumer
  falhou não é reentregue automaticamente na próxima execução. O Event Store guarda
  o fato, e reprocessamento deliberado é assunto da fase que precisar dele.
