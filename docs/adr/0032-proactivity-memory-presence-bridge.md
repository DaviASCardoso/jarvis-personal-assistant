# 0032. Proactivity pode consultar presença de memória, só via bridge adapter

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A subfase 7.6 fechou os Conditional Triggers com seis operadores
(`always`/`context_equals`/`context_present`/`payload_equals`/`and`/`or`/
`not`), deliberadamente sem nenhum que consultasse memória de longo prazo —
"nenhum operador de condição chegou a consultar memória, porque nenhuma
regra concreta desta fase precisa disso" (`ROADMAP.md`, subfase 7.6).
`docs/architecture-contracts.md §3.17` tornou essa omissão uma proibição
explícita: `jarvis.proactivity` está listado como não podendo conhecer
`jarvis.memory`.

A Fase 9 (Deepening Reasoning + Autonomy) traz um caso de uso real, não
hipotético: uma preferência do tipo "não notificar depois das 22h",
registrada em Memory (`docs/architecture-contracts.md` já documenta
preferências do usuário como memórias tipadas, com `confidence`/`source`),
deveria poder suprimir ou adiar uma notificação proativa antes mesmo de o
Agent Runtime ou a `InterruptionPolicy` entrarem em cena — hoje isso é
impossível sem violar a proibição do §3.17.

## Decisão

`jarvis.proactivity` ganha uma dependência de leitura, unidirecional, sobre
Memory — mas nunca por import direto do Core. Réplica exata do padrão já
usado para o mesmo problema entre Memory e Context
(`memory/adapters/context_bridge.py`, Fase 3.7), na direção oposta:

1. **Port definido pelo próprio Proactivity** —
   `jarvis.proactivity.ports.MemoryPresence`, um único método
   (`content_for(subject) -> str | None`). O Core de `jarvis.proactivity`
   (`conditions.py`) conhece esse Protocol, nunca `jarvis.memory`.
2. **Bridge adapter** — `jarvis.proactivity.adapters.memory_bridge.
   MemoryPresenceBridge`, o único módulo do pacote autorizado a importar
   `jarvis.memory` (`MemoryManager`, `MemoryCriteria`, `RetrievalQuery`).
   Traduz um `subject` de condição numa consulta `active_at=agora,
   limit=1`, devolvendo o `content` da memória vigente ou `None` — ausente,
   ainda não válida, expirada e inválida contam igualmente como ausência.
3. **Dois operadores novos, fechados** — `memory_present(subject)` e
   `memory_equals(subject, value)`, seguindo o mesmo vocabulário fechado dos
   seis existentes (nenhum `eval`, nenhum acesso livre). Sem um
   `MemoryPresence` injetado, os dois nunca casam — a ausência do port não
   vira "presença assumida".
4. **Composition root injeta a ponte** — `cli._build_proactivity` só monta
   `MemoryPresenceBridge` quando `proactivity_execute_actions` está ligado
   (mesmo gate de execução que Conditional Triggers já exigem desde o
   ADR-0029), e passa a instância para `ConditionalTriggerConsumer`.

`architecture-contracts.md §3.17` é atualizado para remover `jarvis.memory`
da lista "proibido conhecer" e documentar a exceção pontual. O teste
arquitetural (`tests/test_proactivity_architecture.py`) passa a permitir
`jarvis.memory` só em `memory_bridge.py`, com um teste dedicado garantindo
que nenhum outro adapter do pacote ganha essa exceção de carona — mesma
disciplina de `test_memory_architecture.py::test_adapters_may_depend_on_core`
para o par Memory/Context.

## Alternativas consideradas

- **Manter a proibição, resolver via Trigger Engine (LLM) em vez de
  Conditional Trigger** — descartada: obrigaria uma regra determinística e
  barata ("se há esta preferência, suprime") a pagar uma chamada de LLM só
  para ler um fato já registrado. Contradiz a própria razão de existir dos
  Conditional Triggers (ADR-0029): automação 100% legível, sem
  probabilidade.
- **`ConditionEngine` importar `MemoryManager` diretamente, sem port** —
  descartada: reproduziria exatamente o acoplamento que `architecture-
  contracts.md` evita desde a Fase 1 entre componentes-irmãos (o mesmo
  motivo do `context_bridge.py` existir em vez de `memory/manager.py`
  importar `jarvis.context`).
- **Passar a memória inteira (não só presença) para a condição** —
  descartada: uma condição não precisa rankear, pontuar ou explicar uma
  memória — só saber se ela existe e, quando muito, comparar seu conteúdo.
  Devolver `RetrievalOutcome`/`StoredMemory` completo exporia superfície sem
  consumidor real, violando `architecture-contracts.md §1`.
- **Novo tipo de `AgentInput`/depender do Agent Runtime para a leitura** —
  descartada: misturaria a fronteira que o `FORBIDDEN_ALWAYS` de
  `test_proactivity_architecture.py` protege (`jarvis.agent` continua
  inteiramente fora do alcance de `jarvis.proactivity`); memória e agente
  são portas independentes por desenho desde a Fase 3/4.

## Consequências

- `jarvis.proactivity` ganha sua primeira dependência de leitura sobre outro
  componente de domínio (Memory), mas só através de um port que ele mesmo
  define — a direção de conhecimento continua de fora para dentro do
  pacote, nunca o contrário.
- Uma regra `memory_present`/`memory_equals` sem `proactivity_execute_
  actions` ligado nunca é avaliada com um port real (`ConditionalTrigger-
  Consumer` só é inscrito nesse caso) — consistente com o restante do
  ADR-0029: automação condicional continua behind o mesmo interruptor de
  execução.
- **Gatilho para revisitar:** se surgir necessidade de mais de um método no
  port (ex. listar todas as memórias de um `subject`, não só a mais
  recente), este ADR precisa ser revisto — `MemoryPresence` foi desenhado
  deliberadamente mínimo para o caso de uso real de hoje.
