# 0034. `memory.forget` é uma Skill sujeita ao Policy Engine — exceção pontual ao ADR-0018

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A Fase 11 (Voice Parity & Self-Awareness Skills) quer que o agente consiga
esquecer uma memória por conta própria — "esqueça minha preferência de X" —
por qualquer canal, voz incluída, através do mesmo caminho que qualquer
outra capacidade usa hoje: `Decision.act` → Policy Engine → Skill → Tool
([ADR-0016](0016-action-execution-orchestrator.md)). `SkillInvocation` só
recebe `ToolAccess` como injeção — nenhuma Skill acessa `MemoryManager`
diretamente —, então isso exige uma Tool nova (`ReflectionToolBackend`, Fase 11.3,
`docs/skills.md`) e uma Skill (`memory.forget`) por cima dela.

Isso esbarra de frente no [ADR-0018](0018-memory-writes-outside-the-policy-engine.md),
que já considerou e **rejeitou** essa forma exata de desenho para escrita de
memória: "Submeter a gravação ao Policy Engine como uma Skill `memory.write`:
descartada — uma Skill existe para compor Tools e tocar o mundo externo
([ADR-0005](0005-skill-tool-mcp-distinction.md)). Uma que só chamasse
`MemoryManager.remember` seria uma indireção para reusar um vocabulário de
risco que não descreve o que ela faz, e ainda daria ao agente um caminho
para escrever memória com parâmetros arbitrários via `Decision.act`." O
mesmo argumento textual se aplica a `forget`: também não toca o mundo
externo, também é uma tabela do próprio Jarvis.

Este ADR não reabre esse argumento para **criação** de memória — `remember`
continua exatamente como o ADR-0018 descreve. Ele registra por que
**esquecer** é o caso em que a conclusão muda.

## Decisão

`remember`/reforço continuam pelo mesmo caminho do ADR-0018: `Decision.memory`,
aplicado direto pelo composition root, sem Policy Engine, sem opt-in por
flag. Isso não muda.

`forget` vira uma Skill nova, `memory.forget`
(`skills/builtin/memory.py`, Fase 11.4), com perfil de risco real, não
decorativo:

- `risk=RiskLevel.MEDIUM`, `effects={Effect.WRITE}`,
  `confirmation_requirement=ConfirmationRequirement.CONDITIONAL` (mesmo
  critério de `file.write`: confirmação exigida quando o ator é `EVENT`,
  nunca quando é o próprio usuário pedindo);
- `capabilities={"memory:forget"}`, **negada por padrão** — mesma convenção
  de toda capacidade nova desde a Computer Skill (Fase 8): um operador
  precisa adicionar `memory:forget` a `policy_granted_capabilities`
  explicitamente antes do agente conseguir esquecer qualquer coisa sozinho.

**Por que a conclusão do ADR-0018 não se estende a `forget`:**

1. **Assimetria de dano.** Uma `remember` errada é ruído: recuperável por
   supersessão, e o pior caso é uma memória a mais que `find_duplicate`
   provavelmente já absorveria. Uma `forget` errada apaga do retrieval
   exatamente o fato que existia para evitar um erro — e o dano só aparece
   depois, quando a ausência já custou uma decisão ruim. Tratar as duas
   operações com o mesmo "sem porteira" ignora essa assimetria.
2. **O contexto do ADR-0018 mudou.** Ele já sinalizava isso como risco
   aceito condicional: *"Se o `agent react` autônomo (7.1, sem usuário na
   frente) mostrar que memórias ruins se acumulam, o lugar de tratar isso é
   uma política de consolidação no Memory System, não o Policy Engine."*
   Isso valia para acúmulo de ruído por criação. A Fase 9–11 tornou real o
   que só era hipotético em agosto: Goal Pursuit Loop (9.2), raciocínio
   multi-passo por voz (11.2) — o agente agora encadeia ações sem um
   humano confirmando cada passo. Dar a esse agente mais autônomo um poder
   de apagamento sem porteira, na mesma hora em que sua autonomia cresce,
   inverteria a direção de cautela que o resto da Fase 11 segue.
3. **O vocabulário do Policy Engine descreve `forget` corretamente**, ao
   contrário do argumento do ADR-0018 sobre `remember`. `capability`/
   `risk`/`effect` existem para nomear o que uma ação **muda no mundo que o
   Jarvis observa** — e apagar uma memória muda exatamente isso: o que o
   agente vai saber da próxima vez que perguntar. `remember` não se encaixa
   nesse vocabulário porque criar uma memória não é "fazer" algo no sentido
   que Policy autoriza; apagar uma é.

`jarvis memory forget` (CLI, sem Policy Engine) continua existindo sem
mudança — é o operador humano na própria máquina, fora do laço de decisão
do agente. A diferença agora é só quando quem pede é o **agente**, via
`Decision.act`.

`docs/architecture-contracts.md §3.7` (Tool Router) listava "Memory" como
dependência proibida — texto herdado da Fase 5, antes de Decision Log
(7.4)/Task Manager (7.5) existirem. Passa a documentar `ReflectionToolBackend`
como exceção pontual, mesmo padrão de anotação usado para `ComputerToolBackend`
na própria seção.

## Alternativas consideradas

- **Manter `forget` fora do Policy Engine, via `Decision.memory` estendido
  (mesmo trilho ungated de `remember`)** — mais consistente com o texto
  literal do ADR-0018, descartada aqui porque joga a decisão de segurança
  para dentro do Agent Runtime (que "propõe e para", ADR-0003) sem
  nenhuma autoridade determinística no meio. Motivo 1 acima (assimetria de
  dano) pesa mais que a consistência textual com um ADR escrito antes do
  agente ganhar autonomia multi-passo real.
- **Não expor `forget` ao agente nesta fase, manter só CLI** — descartada:
  contradiz o objetivo explícito da Fase 11 ("Jarvis de filme", tudo por
  voz) e um dos três problemas que o próprio usuário nomeou (gestão de
  memória mais autônoma). Adiar não resolve a tensão, só a esconde.
- **Criar uma capability "burra" (`memory:forget`) sem risco/confirmação
  real, só para ter o que negar por padrão** — descartada: reproduziria a
  exata crítica do ADR-0018 ("vocabulário de risco que não descreve o que
  ela faz"). `risk=MEDIUM`/`effects={WRITE}` aqui descrevem de verdade.

## Consequências

- `remember` e `forget` passam a ter arquiteturas de autorização
  deliberadamente diferentes — um `if` a mais para quem lê o código pela
  primeira vez, documentado aqui e em `docs/memory-system.md`/
  `docs/skills.md` para não parecer inconsistência acidental.
- Uma instalação nova continua sem `memory:forget` concedida — o agente só
  esquece quando o operador conceder a capacidade explicitamente, mesma
  postura "nega por padrão" de toda capacidade desde a Fase 8.
- `docs/architecture-contracts.md §3.7` ganha uma nota de exceção pontual,
  não uma reescrita — o resto da restrição (LLM, Context, regras de Policy,
  Skills como dependência de um Tool Router genérico) continua valendo.
- **Gatilho para revisitar:** se surgir uma segunda operação destrutiva
  sobre estado do próprio Jarvis pedindo o mesmo tratamento (ex. purge de
  memória, cancelamento de tarefa em massa), vale generalizar esta decisão
  num princípio nomeado ("operações destrutivas sobre estado interno são
  sempre Skills") em vez de acumular ADRs pontuais um por um.
