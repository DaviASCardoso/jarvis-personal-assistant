# 0029. Autonomia real em três interruptores independentes; automação condicional sem LLM

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

Até a Fase 6, nada no Jarvis agia sem um humano pedir na hora: `agent react`
avalia um evento só quando alguém digita o comando; `--execute`/
`JARVIS_VOICE_EXECUTE_ACTIONS` são opt-in para toda submissão de ação. A
Fase 7 introduz a primeira capacidade real de o sistema iniciar raciocínio e
ação **sem** esse pedido imediato — um evento publicado durante `jarvis run`
pode, sozinho, levar a uma chamada ao LLM e a uma execução de Skill.

Essa é a mudança de postura mais significativa do projeto desde o ADR-0003
(o LLM não é autoridade de segurança). Não é suficiente que a cadeia
Policy → Skill → Tool continue correta (ela continua — nada na Fase 7 muda
o ADR-0016); é preciso que **a decisão de sequer tentar** seja tão
deliberada quanto a decisão de autorizar.

## Decisão

Três interruptores, e os três precisam estar "ligados" para que qualquer
coisa aconteça sem pedido imediato — nenhum deles sozinho basta:

1. **`JARVIS_PROACTIVITY_ENABLED`** (default `false`) — sem ele, nenhum
   `TriggerEventConsumer`/`ConditionalTriggerConsumer` é sequer inscrito no
   bus de `jarvis run` (`_build_proactivity`, `cli.py`). O sistema se
   comporta byte a byte como antes da Fase 7.
2. **Allowlist não vazia** — `JARVIS_PROACTIVITY_TRIGGER_EVENT_TYPES` (para
   o caminho de raciocínio, 7.1) e `JARVIS_PROACTIVITY_RULES_PATH` apontando
   para um arquivo com ao menos uma regra habilitada (para o caminho
   condicional, 7.6). Mesmo critério de `JARVIS_POLICY_GRANTED_CAPABILITIES`
   desde a Fase 5: uma lista vazia nega tudo, nunca permite tudo.
3. **`JARVIS_PROACTIVITY_EXECUTE_ACTIONS`** (default `false`) — controla se
   uma proposta de ação chega a `ActionExecutor.submit`. Sem ele, o Trigger
   Engine ainda raciocina e ainda notifica (uma decisão `notify`/`ask` não
   depende deste interruptor), mas uma decisão `act`/`act_and_notify` fica
   só na trilha, sem execução. **O caminho condicional (7.6) exige este
   interruptor mesmo com `PROACTIVITY_ENABLED` ligado** — ao contrário do
   Trigger Engine, uma `ConditionalRule` não tem modo "só avisar": o único
   efeito que ela produz é uma execução, então gateá-la por um interruptor
   que só controla execução (não um interruptor de "raciocinar") é a
   correspondência exata, não uma analogia.

O segundo pilar desta decisão: **Conditional Triggers (7.6) nunca chamam o
LLM.** `ConditionEngine.evaluate` é uma função determinística sobre um
vocabulário fechado de seis operadores (`always`/`context_equals`/
`context_present`/`payload_equals`/`and`/`or`/`not`) que produz uma
`ActionRequest(actor=Actor.SYSTEM)` diretamente. Isso não é uma otimização —
é a razão de este caminho poder existir com um interruptor mais simples que
o do Trigger Engine: uma automação cujo comportamento é 100% legível no
arquivo de regras que o usuário escreveu não carrega a mesma incerteza que
"o que o modelo vai decidir fazer com este evento".

## Alternativas consideradas

- **Um único interruptor (`PROACTIVITY_ENABLED`) controlando tudo**:
  descartada — colapsaria "o sistema pode raciocinar sobre eventos" e "o
  sistema pode agir sem confirmação" na mesma decisão, quando são riscos de
  natureza diferente (uma notificação errada é inconveniente; uma ação
  errada pode ser irreversível). O precedente de `--execute` separado de
  "conversar com o agente" já estabelecia essa distinção desde a Fase 4/5.
- **Conditional Triggers sob o mesmo escrutínio que o Trigger Engine
  (LLM opcional por regra)**: descartada — misturaria automação
  determinística com raciocínio probabilístico no mesmo componente,
  tornando "por que isso executou" uma pergunta às vezes sem resposta
  fechada. Duas responsabilidades, dois componentes (`TriggerEngine` para
  "vale raciocinar", `ConditionEngine` para "isto sempre faz aquilo").
- **Regras condicionais executando com o mesmo interruptor do Trigger
  Engine (raciocínio), sem exigir `EXECUTE_ACTIONS`**: descartada — daria a
  um arquivo de configuração (7.6) mais poder de execução automática que
  ligar `PROACTIVITY_ENABLED` sozinho já dá ao caminho de raciocínio, que
  ainda depende de `EXECUTE_ACTIONS` para agir. Inverteria a ordem de
  cautela: automação sem LLM merece **pelo menos** o mesmo cuidado que
  automação com LLM, não menos.

## Consequências

- `jarvis run` sem nenhuma variável de proatividade configurada é,
  operacionalmente, o `jarvis run` da Fase 6 — testado explicitamente em
  `tests/test_cli_proactivity.py::TestBuildProactivity` (a assinatura do bus
  tem exatamente as duas inscrições que já existiam: log e confirmação).
- Ligar só `PROACTIVITY_ENABLED` + uma allowlist de triggers dá ao Jarvis a
  capacidade de notificar proativamente sem nunca poder agir sozinho — um
  meio-termo real, não binário.
- **Custo aceito:** três variáveis de ambiente para entender antes de ligar
  autonomia de verdade, em vez de uma. É o custo deliberado de tornar
  "quanta autonomia" uma escolha explícita em vez de um pacote fechado.
- **Gatilho para revisitar:** se um caso de uso legítimo precisar de
  Conditional Triggers que só notificam (sem executar), este ADR precisa ser
  revisto — hoje `ConditionEngine` não tem essa forma, e criá-la reabriria a
  pergunta de por que ela não existe para o Trigger Engine também.
