# 0013. `PolicyApproval` como capacidade de uso único, validada pelo emissor

**Status:** Accepted
**Data:** 2026-08-13

## Contexto

O [ADR-0003](0003-policy-engine-safety-authority.md) fixou que `PolicyApproval`
existe como conceito de domínio — uma autorização emitida pelo Policy Engine para
uma execução específica — e deixou o mecanismo concreto explicitamente em aberto
para a Fase 5. A `security.md` repetiu a lacuna: "este documento não define o
mecanismo concreto (token opaco, JWT, assinatura criptográfica, objeto em
memória)".

A pergunta a responder é: **o que faz uma aprovação valer?** Se ela vale por ser
um objeto com os campos certos, qualquer código que consiga construir a dataclass
se autoriza — e a separação de poderes do ADR-0003 vira convenção. A Fase 5
precisa de uma resposta que sobreviva a uma Skill mal escrita, não só a uma Skill
bem-intencionada.

Duas restrições contextuais moldam a escolha. O Jarvis roda **em um processo
único, local**: não há fronteira de confiança entre serviços a atravessar. E a
especificação da fase (`PHASE-5.md §8`) pede explicitamente para não introduzir
JWT, criptografia ou tokens de autorização sem necessidade arquitetural.

## Decisão

Uma `PolicyApproval` vale porque **o Policy Engine que a emitiu a reconhece**, e
não porque ela carrega prova própria.

1. `PolicyEngine.evaluate()` é o único lugar do sistema que cria uma aprovação
   válida: criá-la inclui registrá-la num **ledger interno** do engine.
2. `PolicyEngine.consume(approval)` valida contra esse ledger: a aprovação
   existe? não foi consumida? não expirou? `execution_id`, `skill` e
   `parameters_fingerprint` batem?
3. A aprovação é **de uso único**. Consumir marca; consumir de novo é erro.
4. Ela é ligada ao `parameters_fingerprint` — o sha256 do JSON canônico dos
   parâmetros. Autorizar "apagar A" nunca autoriza "apagar B", e editar os
   parâmetros depois da autorização a invalida.
5. TTL curto (default 60s). Uma aprovação existe para atravessar uma execução,
   não para ser guardada.
6. O ledger é **em memória, por processo**. Aprovações não sobrevivem ao
   processo.

Consequência direta e desejada: uma `PolicyApproval` construída à mão em qualquer
outro módulo tem todos os campos e nenhum valor — `consume()` não a encontra e
levanta `UnknownApprovalError`.

Uma confirmação respondida em outra invocação do CLI, portanto, **não** restaura
a autorização anterior: força uma reavaliação completa da política e uma
aprovação nova. É por isso que uma denylist acrescentada entre o pedido e a
confirmação ainda nega.

## Alternativas consideradas

- **Token opaco persistido em banco**: descartada. Sobreviveria ao processo, mas
  exigiria um store novo, uma política de expurgo e uma decisão sobre o que fazer
  com aprovações órfãs — tudo isso para restaurar poder concedido num processo
  que já morreu. Reavaliar a política é mais barato **e** mais seguro do que
  ressuscitar uma autorização.
- **JWT ou assinatura criptográfica**: descartada. Assinatura resolve o problema
  de validar uma credencial emitida por *outro* processo, que aqui não existe.
  Introduziria gestão de chave, escolha de algoritmo e uma dependência, sem
  fechar nenhum buraco que o ledger não feche. `PHASE-5.md §8` proíbe
  explicitamente adotá-la sem necessidade arquitetural.
- **Objeto de domínio sem ledger** (a aprovação vale por existir): descartada —
  é exatamente o cenário que o ADR-0003 quer evitar. Uma Skill que construísse
  `PolicyApproval(...)` se autoautorizaria, e a fronteira dependeria de ninguém
  ter essa ideia.

## Consequências

- "Skill não se autoriza" deixa de ser disciplina e vira propriedade verificável:
  `test_action_security.py::test_a_handmade_approval_does_not_open_the_door` e um
  teste arquitetural que varre a AST atrás de construções de `PolicyApproval`
  fora de `jarvis/policy/`.
- Zero dependência nova, zero criptografia, zero configuração de chave.
- Uma execução interrompida entre a emissão e o consumo simplesmente perde a
  aprovação — e é reavaliada. Não há estado pendente a limpar.
- **Não** protege contra código malicioso *dentro* do processo: quem pode editar
  `jarvis/policy/engine.py` pode tudo. Essa é a fronteira que este ADR não
  promete, e nenhum mecanismo em processo poderia prometer.
- Se o Jarvis um dia executar ações fora deste processo (daemon separado,
  serviço remoto), este ADR precisará ser superado — aí passa a existir uma
  fronteira de confiança real, e aí assinatura deixa de ser prematura.
