# 0017. Trilha de auditoria como eventos, sem store de auditoria próprio

**Status:** Accepted
**Data:** 2026-08-13

## Contexto

O `architecture-contracts.md §10.4` exige que "todo `PolicyVerdict` e toda
execução real de Tool sejam registrados via `AuditLog` port, com
`correlation_id`, timestamp, ator, decisão e resultado — consultável
posteriormente". O §14 acrescenta que audit log é categoria separada dos logs de
debug, sempre durável.

O contrato define o **port** e as garantias; não define o adapter. E
`PHASE-5.md §23` dá a direção: "a auditoria deve reutilizar o Event System quando
apropriado. Não criar um banco paralelo de auditoria sem necessidade."

Há também um fato de escopo: a subfase 8.4 do roadmap é inteiramente sobre Audit
Logging. Decidir agora o substrato da trilha condiciona aquela fase, e por isso a
decisão é arquitetural em vez de detalhe de implementação.

## Decisão

O adapter do port `AuditLog` publica **eventos** no Event System. Não existe
`audit.db`.

O port `AuditLog` vive em `jarvis/audit.py` — na raiz, ao lado de `errors.py`.
Não é capricho de organização: `jarvis.policy` registra vereditos,
`jarvis.tools` registra execuções de Tool e `jarvis.execution` registra
desfechos, e nenhum dos três pode importar os outros dois sem desfazer as
fronteiras que a fase existe para criar. Um port usado por componentes que não se
conhecem não pertence a nenhum deles.

Nove tipos de evento, cada um respondendo a uma pergunta da `PHASE-5.md §23`:
`action.requested`, `policy.evaluated`, `action.confirmation_requested`,
`action.confirmation_granted`, `action.confirmation_denied`,
`tool.execution_completed`, `tool.execution_failed`, `action.completed`,
`action.failed`. Não existe `action.started` (redundante com o par
`requested`/`completed`) nem `tool.execution_started` (sem consumidor
operacional; a duração já vai no término).

Três regras que a decisão carrega:

1. **`event_id` determinístico por marco**, derivado de
   `(execution_id, kind, ordinal, discriminator)`. Republicar o mesmo marco é
   no-op no store; registrar um marco diferente nunca é confundido com duplicata.
   O `discriminator` existe por um caso concreto: uma execução confirmada é
   avaliada pela política **duas vezes**, e sem ele o veredito que autoriza
   colidiria com o que pediu confirmação — a trilha perderia exatamente o
   registro mais importante.
2. **Nenhum payload carrega parâmetros de ação** — só o
   `parameters_fingerprint`. Provar *qual* execução aconteceu não exige guardar
   *o que* ela dizia ([ADR-0014](0014-confirmation-state-and-event-answers.md)).
3. **Fail-closed no veredito, best-effort no resto.** Se `policy.evaluated` não
   pode ser gravado, a execução aborta — sem trilha, sem ação. Falha ao gravar os
   marcos posteriores é logada mas não desfaz o efeito: não existe compensação
   honesta para "o arquivo já foi escrito".

## Alternativas consideradas

- **`audit.db` dedicado**: descartada. Seria um quinto schema a manter e uma
  segunda fonte a divergir do Event Store, para ganhar o quê? O Event Store já é
  durável, imutável ([ADR-0004](0004-event-immutability-and-timestamps.md)),
  consultável por `correlation_id` e deduplicado por `event_id` — que é
  exatamente a lista de garantias que um audit log precisa ter.
- **Só log estruturado**: descartada. Não é durável nem consultável, e o §14
  exige as duas coisas. Log estruturado continua existindo, para depuração — é
  categoria diferente, com retenção diferente.
- **Tabela de auditoria dentro de `actions.db`**: descartada. Misturaria estado
  operacional (mutável, apagável) com fato histórico (imutável, permanente) no
  mesmo schema — a distinção que o ADR-0014 acabou de estabelecer.

## Consequências

- As oito perguntas de auditoria da `PHASE-5.md §23` são respondíveis com um
  comando que já existia antes da fase:
  `jarvis events list --correlation-id <id>`.
- A trilha herda de graça a imutabilidade, a ordenação estável e a idempotência
  do Event System.
- A subfase 8.4 (Audit Logging) começa com o substrato pronto: o que faltará lá é
  consulta e retenção, não persistência.
- **Custo aceito:** eventos de auditoria compartilham o `events.db` com eventos
  de domínio, e uma execução com muitas chamadas de Tool produz vários eventos.
  Para um agente pessoal isso é ruído aceitável; se um dia incomodar, o filtro
  por `event_type` já separa as duas famílias sem migração.
- Um consumer inscrito no bus passa a ver eventos de auditoria. Nenhum consumer
  atual se inscreve neles, e nenhum deve: são registro, não gatilho.
