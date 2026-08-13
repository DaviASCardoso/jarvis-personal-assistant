# 0014. Confirmação: ação pendente como estado; resposta do usuário como evento

**Status:** Accepted
**Data:** 2026-08-13

## Contexto

O [ADR-0003](0003-policy-engine-safety-authority.md) deixou o desenho do fluxo de
confirmação assíncrona explicitamente fora de escopo, para as Fases 5/7. O
`architecture-contracts.md §10.2` fixou uma peça: "`require_confirmation` →
Notification pede confirmação; **resposta do usuário chega como evento**; Policy
decide então".

Uma ação que espera confirmação precisa sobreviver entre dois momentos que, na
prática, são **dois processos**: `jarvis action run` termina e devolve o terminal;
`jarvis action confirm <id>` roda depois. Para executar a ação mais tarde é
preciso ter os **parâmetros** dela — e parâmetros são a coisa mais sensível que a
camada de ação move (caminho de arquivo, corpo de mensagem, destinatário).

Isso cria uma tensão real com o Event System. Um evento é imutável e para sempre
([ADR-0004](0004-event-immutability-and-timestamps.md)); guardar parâmetros nele é
uma decisão irreversível sobre dado pessoal.

## Decisão

Separar as duas coisas pelo que elas **são**, e não pelo que é conveniente:

1. **A ação pendente é estado operacional.** Vive em `data/actions.db`, com os
   parâmetros. É mutável, consultável e apagável — a categoria "estado" de
   `architecture-contracts.md §12`, que pertence ao componente dono. Uma ação
   rejeitada ou expirada pode ser removida; um evento não poderia.
2. **A resposta do usuário é um fato, e vira evento**:
   `action.confirmation_granted` / `action.confirmation_denied`, publicados pela
   interface e carregando **apenas** `execution_id` e `parameters_fingerprint` —
   nunca os parâmetros.
3. **Quem projeta o evento no estado é um `EventConsumer`**
   (`ActionEventConsumer`), exatamente como `ContextEventConsumer` e
   `MemoryEventConsumer`. Ele só muda estado; **não executa nada**.
4. **Quem retoma é o composition root**, num passo separado, e a retomada
   **reavalia a política do zero**.
5. A confirmação é ligada a `execution_id` **e** ao `parameters_fingerprint`, e
   expira (default 900s).

O item 3 não é preferência de estilo. Um consumer que disparasse a execução ao
receber a confirmação seria um caminho até a Tool acionado por evento, sem passar
de novo pelo Policy Engine — precisamente o bypass que a fase existe para
impedir.

O item 4 tem uma consequência que vale mais que a simetria: como o ledger de
aprovações não sobrevive ao processo ([ADR-0013](0013-single-use-policy-approval.md)),
retomar **sempre** reavalia. Uma denylist acrescentada entre o pedido e a
confirmação ainda nega.

## Alternativas consideradas

- **Confirmação síncrona e bloqueante no mesmo turno**: descartada. O CLI não é
  um daemon; bloquear o processo esperando uma pessoa manteria um terminal preso
  e não sobreviveria a um `Ctrl-C`. Também tornaria impossível confirmar de outro
  lugar mais tarde — que é como uma confirmação de verdade funciona.
- **Confirmação inteiramente event-sourced** (pendências como projeção do Event
  Store, sem store próprio): descartada. Era a opção com menos infraestrutura, e
  foi descartada por privacidade: exigiria colocar os parâmetros da ação no
  payload de um evento imutável, para sempre, sem possibilidade de expurgo.
  Trocar um arquivo SQLite por um passivo permanente de dado pessoal é um mau
  negócio num agente que lê e escreve arquivos do usuário.
- **Sem persistência** (pendência só em memória): descartada — a ação
  desapareceria ao fim do processo, e `jarvis action confirm` não teria o que
  confirmar.
- **Marcar a confirmação direto no repositório, sem evento**: descartada por
  contrato (§10.2) e por auditoria: a resposta do usuário é justamente uma das
  perguntas que a trilha precisa responder ("houve confirmação?").

## Consequências

- Um quarto banco SQLite (`actions.db`), seguindo o padrão dos três anteriores:
  um componente, um schema, um `user_version`.
- O Event Store fica livre de parâmetros de ação. O que ele guarda sobre uma
  confirmação é identidade e fingerprint — suficiente para provar *que* houve, e
  *sobre o quê*, sem guardar *o quê*.
- `jarvis action reject` deixa de ser só um registro: a pendência some, e com ela
  os parâmetros.
- Uma pendência esquecida expira sozinha e é marcada — a reavaliação nunca
  estende o prazo, senão uma pendência consultada de vez em quando duraria para
  sempre.
- O canal de apresentação é o **CLI**, não o Notification System — esse é a
  subfase 7.3, e implementá-lo aqui adiantaria fase. O contrato continua
  satisfeito no que importa: a resposta entra como evento.
- Quando a 7.3 existir, ela substitui a interface **sem** tocar neste desenho: o
  Notification System publicará os mesmos dois eventos.
