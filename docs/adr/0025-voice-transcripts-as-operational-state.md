# 0025. Transcrição de voz como estado operacional, nunca como evento

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A subfase 6.4 do [roadmap](../../ROADMAP.md) pede `VoiceSession` com identidade,
integração com a conversa, timeout e controle de estado. O docstring de
`agent/conversation.py` já apontava a pendência desde a Fase 4: "persistir sessão
é escopo de Voice Sessions (6.4); guardar diálogo em disco sem política de
retenção seria criar um repositório de dado pessoal sem quem responda por ele".

O que uma sessão de voz produz é a coisa mais sensível que o Jarvis passou a
manipular: **o que uma pessoa falou em voz alta na própria casa**. Onde isso é
guardado é uma decisão irreversível na prática, porque o Event Store é imutável
por contrato ([ADR-0004](0004-event-immutability-and-timestamps.md)).

Há um precedente direto: o [ADR-0014](0014-confirmation-state-and-event-answers.md)
tirou os **parâmetros de ação** do Event Store pelo mesmo motivo, deixando lá só
identidade e fingerprint.

## Decisão

Separar pelo que as coisas **são**, e não pelo que é conveniente:

1. **A conversa é estado operacional.** Vive em `data/voice.db` — quinto SQLite
   do projeto, um componente, um schema, um `PRAGMA user_version`. É mutável,
   consultável e apagável.
2. **A sessão é um fato, e vira evento** — `voice.session_started` e
   `voice.session_ended`, publicados pelo composition root, carregando **apenas**
   `session_id`, `turn_count`, `reason` e `duration_ms`. Nenhuma palavra do que
   foi dito.
3. **Áudio não é persistido em lugar nenhum.** Nem bytes, nem WAV, nem caminho de
   arquivo. O schema não tem coluna para isso, e um teste compara a lista de
   colunas com um conjunto fechado.
4. **Retenção por default**: `JARVIS_VOICE_RETENTION_DAYS=7`, aplicada na
   inicialização do processo residente. `0` desliga o expurgo automático, e
   `jarvis voice sessions purge` apaga sob demanda.

Os dois eventos também passam a alimentar o campo `conversation` do Context
Engine, que existe desde a Fase 2 e nunca teve fonte — `voice.session_ended`
registra **ausência observada**, como `user.activity_ended` já fazia.

## Alternativas consideradas

- **Transcrições no Event Store**: era a opção com menos infraestrutura — nenhum
  banco novo, reconstrução de graça, correlação automática. Descartada por
  privacidade: colocaria fala pessoal num registro imutável, para sempre, sem
  possibilidade de expurgo. Trocar um arquivo SQLite por um passivo permanente é
  um mau negócio num assistente que fica ouvindo a sala.
- **Não persistir nada** (sessão só em memória): `jarvis voice sessions` não
  teria o que mostrar, o painel perderia a conversa ao reiniciar, e a subfase 6.4
  ficaria sem o "controle de estado" que ela pede.
- **Transcrições como Memory**: confundiria conversa com conhecimento. Memória
  tem importância, confiança, decaimento e consolidação; um "oi, tudo bem?" não
  tem nada disso e poluiria todo retrieval futuro. O que **merece** virar memória
  já vira, pelo caminho normal de `Decision.memory`
  ([ADR-0018](0018-memory-writes-outside-the-policy-engine.md)).
- **Uma tabela dentro de `actions.db`**: misturaria dois estados operacionais sem
  relação, com ciclos de retenção diferentes.

## Consequências

- O Event Store fica livre de fala. O que ele guarda sobre uma conversa é
  suficiente para provar **que** houve, quando e por quantos turnos — sem guardar
  o quê.
- `data/` já está no `.gitignore`; a conversa nunca entra em commit.
- O campo `conversation` do contexto passa a ser preenchido de verdade, e o
  agente sabe, no prompt, que está numa sessão de voz — sem nenhuma mudança em
  `jarvis.agent`.
- **A reavaliação que o ADR-0018 pediu está feita, e o resultado é manter.**
  Aquele ADR registrou que, quando conversas fossem persistidas, `reference` no
  caminho do usuário passaria a ter para onde apontar. Passou — e continua sem
  `reference`, por dois motivos: uma referência por sessão faria `find_duplicate`
  tratar cada conversa como um universo novo, trocando reforço por linha nova; e
  `voice.db` é apagável por retenção, então o ponteiro apontaria para o nada
  depois de sete dias.
- **Custo aceito:** uma sessão perdida entre dois saves (crash no meio da
  conversa) perde os turnos desde o último. Turno de conversa é conveniência, não
  fato auditável — o fato já está no evento.
