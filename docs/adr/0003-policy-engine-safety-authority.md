# 0003. Policy Engine como autoridade determinística de segurança

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

A partir da Fase 5, o Jarvis vai executar ações reais no mundo (enviar
email, mexer no calendário, eventualmente interagir com o computador do
usuário). A decisão de *fazer algo* nasce de um raciocínio de LLM no Agent
Runtime — e um LLM pode alucinar, ser manipulado por conteúdo malicioso em
um evento (prompt injection vindo de um email, por exemplo), ou simplesmente
errar a avaliação de risco de uma ação. Se a mesma camada que "decide agir"
também for a única autoridade sobre se a ação *pode* acontecer, não existe
uma rede de segurança independente entre "o modelo quis" e "o Jarvis fez".

## Decisão

O Agent Runtime **nunca executa ações diretamente** — ele apenas emite uma
`Decision` estruturada (`ignore` | `remember` | `notify` | `ask` | `act` |
`act_and_notify`). Uma `Decision.act` é uma **proposta**, não uma ordem de
execução.

Toda proposta de ação passa obrigatoriamente pelo **Policy Engine**: um
componente separado, determinístico (código/configuração, sem chamada de
LLM na própria decisão de autorização), que avalia risco e permissões e
retorna um `PolicyVerdict` (`allow` | `deny` | `require_confirmation`).
Apenas depois de um `allow` (ou de uma confirmação do usuário, no caso
`require_confirmation`) uma Skill pode executar sua parte de risco.

Duas propriedades de suporte a essa decisão:

- `risk` e `confirmation_requirement`, autodeclarados por cada Skill, nunca
  concedem autorização à própria Skill — são apenas insumo para a decisão do
  Policy Engine, que pode divergir dessa autodeclaração (ex. denylist
  estática mais restritiva).
- `PolicyApproval` é o conceito de domínio que representa uma autorização
  emitida pelo Policy Engine para uma execução específica. Sua implementação
  concreta (token opaco, JWT, assinatura, objeto em memória) é decisão da
  Fase 5, não deste ADR — o que fica fixado aqui é que ela existe como
  conceito e que uma Skill não deveria conseguir executar sua parte de risco
  sem uma autorização correspondente.

Detalhamento em
[`architecture-contracts.md §8.4 e §10`](../architecture-contracts.md#10-policy-e-safety-boundary).

## Alternativas consideradas

- **Confiar na autoavaliação de risco de cada Skill** (a Skill decide se
  precisa de confirmação): descartada — coloca a decisão de segurança no
  mesmo lugar que decide *o que* fazer, sem separação de poderes; um bug ou
  uma Skill mal escrita se autoaprovaria.
- **Deixar o próprio LLM decidir se uma ação de risco deve prosseguir**
  (ex. pedir para o modelo "confirmar" antes de agir): descartada
  explicitamente — é o problema que este ADR existe para evitar. Um
  componente não-determinístico não pode ser a única barreira de segurança.
- **Confirmação sempre síncrona e bloqueante no mesmo processo/turno**:
  não descartada, mas não fixada aqui — o mecanismo exato de espera por
  confirmação (evento assíncrono vs. chamada bloqueante) é decisão de
  implementação das Fases 5/7, fora do escopo arquitetural deste ADR.

## Consequências

- Toda ação de risco tem um ponto único e auditável de autorização,
  independente de quantas Skills existirem.
- Fica mais difícil (de propósito) para uma Skill nova pular a checagem de
  política — precisa de um `PolicyApproval` correspondente.
- Adiciona uma indireção (proposta → verdict → execução) em vez de execução
  direta — custo aceito em troca de ter uma autoridade de segurança
  separada do raciocínio.
- Não resolve, por si só, o desenho do fluxo de confirmação assíncrona
  (Policy Engine pedindo confirmação e retomando depois) — fica para a
  implementação das Fases 5.9/7.
