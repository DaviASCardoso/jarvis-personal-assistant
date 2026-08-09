# Memory System

> Documentação conceitual do Memory System, previsto para a **Fase 3** do
> [roadmap](../ROADMAP.md). Criada na subfase **0.5** como explicação de um
> contrato já aprovado na 0.3 — **não implementa** retrieval, consolidação
> nem escolhe banco de dados. O contrato normativo completo está em
> [`architecture-contracts.md §7`](architecture-contracts.md#7-memory-contract);
> este documento explica o *porquê* e o *como se relaciona*, sem repetir a
> tabela de metadados.

## Por que memória, além de contexto

O Context Engine ([context-system.md](context-system.md)) responde "o que
é verdade agora". A Memory System responde a uma pergunta diferente: "o que
o Jarvis deveria continuar sabendo mesmo depois que o contexto que gerou
esse conhecimento já expirou?". Um evento específico (uma reunião de ontem)
não precisa ser lembrado para sempre em detalhe — mas o padrão que ele
revela ("o usuário prefere reuniões de manhã") deveria sobreviver ao TTL de
qualquer campo de contexto.

## Tipos de memória

- **Working memory** — estado de curto prazo, escopo de uma tarefa ou
  conversa em andamento. Pode usar backend mais barato ou TTL mais curto
  que os tipos abaixo — decisão de implementação da Fase 3, não deste
  contrato.
- **Episódica** — memória de acontecimentos específicos ("o usuário pediu
  para adiar a reunião de terça na semana passada").
- **Semântica** — conhecimento consolidado, generalizado a partir de
  episódios repetidos ou de fatos declarados diretamente ("o usuário
  trabalha em horário comercial").
- **Preferências** — um tipo específico de memória semântica com um papel
  arquitetural próprio: é onde preferências do usuário vivem, em vez de em
  `Settings` (ver [ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md)
  e §6 abaixo).
- **Procedural** — conhecimento sobre "como fazer" algo dentro do próprio
  sistema (ex. o formato preferido de resposta para um certo tipo de
  pedido).
- **Task memory** — estado durável associado a uma tarefa específica em
  andamento, distinto de working memory por sobreviver além de uma única
  sessão de conversa.

## Metadados: `importance`, `confidence`, `relevance`

Estes três conceitos são frequentemente confundidos porque todos "medem o
quanto uma memória importa" — mas têm papéis e ciclos de vida diferentes:

| Conceito | Definição | Quando existe |
|---|---|---|
| **`importance`** | peso atribuído à memória — o quanto ela deveria pesar na recuperação e no decaimento | atributo permanente, armazenado junto da memória |
| **`confidence`** | quão certo o sistema está de que o conteúdo é verdadeiro/preciso | atributo permanente, armazenado junto da memória |
| **`relevance`** | score de recuperação para uma consulta específica, combinando importance + recência + confidence + match da query | **calculado em tempo de retrieval — nunca armazenado** |

O ponto que mais vale destacar: **`relevance` não é uma propriedade
permanente equivalente a `importance`.** Uma memória de alta `importance`
pode ter `relevance` baixa para uma consulta específica (é importante em
geral, mas não pertinente àquela pergunta); uma memória de `importance`
mediana pode ter `relevance` alta para a consulta certa. Tratar os dois
como sinônimos levaria a armazenar um "score de relevância" fixo que
deixaria de fazer sentido assim que a consulta mudasse.

Metadados adicionais (obrigatórios: `memory_id`, `type`, `content`,
`created_at`, `updated_at`, `last_accessed_at`, `source`; opcionais:
`valid_from`, `valid_until`, `entities`, `tags`, `embedding`) estão
detalhados em [`architecture-contracts.md §7`](architecture-contracts.md#7-memory-contract)
— não repetidos aqui.

## `LLMProvider` vs. `EmbeddingProvider`

A Memory System depende de busca semântica, o que exige gerar embeddings —
tecnicamente também "uma chamada de modelo". Em vez de reusar o mesmo
`LLMProvider` que o Agent Runtime usa para raciocínio, a Memory System
depende de um port **separado**, `EmbeddingProvider` (ver
[ADR-0002](adr/0002-llm-provider-abstraction.md)):

- Trocar o modelo de raciocínio do Agent Runtime não deveria arriscar
  quebrar a busca semântica já indexada, e vice-versa — os dois ciclos de
  vida e motivações de troca são independentes.
- Quando um `embedding` é armazenado junto de uma memória, ele registra
  qual `EmbeddingProvider`/versão o gerou — vetores de modelos diferentes
  não são comparáveis entre si, e trocar de modelo de embedding não pode
  corromper a busca silenciosamente misturando espaços vetoriais
  incompatíveis.
- O mesmo vendor pode, na prática, implementar os dois ports — isso é
  coincidência de infraestrutura, não acoplamento arquitetural entre eles.

## Preferências não vivem em `Settings`

Preferências do usuário (“não notificar depois das 22h”) são modeladas
como memória do tipo preferência — não como configuração estática. A
diferença: preferências têm proveniência e `confidence`, podem mudar/decair
ao longo do tempo, e são escritas pelo próprio agente em runtime a partir
do que ele aprende — nenhuma dessas propriedades faz sentido para
`Settings` (`pydantic-settings`, carregado uma vez, estático). Ver
[ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md) para a
distinção completa entre configuração, secrets, preferências e estado.

## O que esta subfase não decide

- Banco de dados (SQLite, PostgreSQL, pgvector) — decisão da Fase 3.2.
- Algoritmo de retrieval e scoring combinado — decisão das Fases 3.3/3.4.
- Estratégia de consolidação (detecção de padrão episódica → semântica) —
  decisão da Fase 3.5.

## Documentos relacionados

- Contrato normativo completo: [architecture-contracts.md §7](architecture-contracts.md#7-memory-contract)
- Limites do componente: [architecture-contracts.md §3.3](architecture-contracts.md#33-memory-system)
- Separação LLM/Embedding: [ADR-0002](adr/0002-llm-provider-abstraction.md)
- Preferências vs. configuração: [ADR-0006](adr/0006-configuration-vs-preferences-vs-state.md)
- Visão geral: [architecture.md](architecture.md)
