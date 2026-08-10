# 0010. Memória imutável, com supersessão em vez de sobrescrita

**Status:** Accepted
**Data:** 2026-08-10

## Contexto

`PHASE-3.md §7` proíbe explicitamente resolver uma contradição
("Usuário prefere Python" vs. "Usuário prefere Rust") com
`UPDATE memory SET content = ...` sem semântica definida, e `§5` exige que
memórias antigas não sejam "sobrescritas" silenciosamente — "não assumir que
toda memória deve ser sobrescrita". O Event System já havia estabelecido
imutabilidade como propriedade estrutural, não convencional
([ADR-0004](0004-event-immutability-and-timestamps.md)); o Context Engine
estabeleceu expiração *lógica* para snapshots. O Memory System precisa da sua
própria decisão, porque memória — ao contrário de evento e de snapshot — pode
legitimamente precisar ser apagada de verdade (dado pessoal, `PHASE-3.md §16`),
o que nenhum dos dois precedentes cobre sozinho.

## Decisão

1. **Conteúdo imutável, estruturalmente.** `Memory` (a afirmação: conteúdo,
   tipo, proveniência, `created_at`, `importance`) e `StoredMemory` (`Memory` +
   estado de ciclo de vida: `confidence` corrente, acesso, reforço,
   supersessão, invalidação) são dois tipos, como `Event`/`RecordedEvent`. Não
   existe `update(memory)` genérico — cada mutação de ciclo de vida é um método
   nomeado (`reinforce`, `invalidate`, `supersede`, `replace_embedding`), e a
   ausência de um método genérico torna a proibição estrutural, não uma
   convenção de código.
2. **Contradição por supersessão datada.** Duas memórias do mesmo `type` +
   `subject` + `scope` com conteúdos diferentes são uma contradição. A mais
   nova é criada normalmente; a mais antiga recebe `superseded_by` e tem sua
   `valid_until` fechada no `valid_from` da nova — nunca apagada, nunca
   reescrita. A resolução é por **recência**, não por confiança: a memória mais
   nova ganha vigência por ser mais nova; se a crença nela for fraca, isso
   aparece no ranking (`confidence`), não na decisão de qual memória está
   vigente.
3. **`forget` invalida; `purge` apaga — e são operações distintas,
   deliberadamente.** `forget` (invalidação lógica) preserva a evidência,
   simétrico ao `expire_before` lógico do Context Engine. `purge` (remoção
   física) existe porque memória pode conter dado pessoal, e `PHASE-3.md §16`
   trata isso como um direito do usuário, não uma conveniência operacional —
   por isso é sempre explícito, nunca automático, e **assimétrico** em relação
   a `events` e `context_snapshots`: só a tabela de memórias tem um caminho de
   remoção física de verdade.

## Alternativas consideradas

- **Mutação in-place com repositório disciplinado** (o adapter simplesmente não
  emite `UPDATE` de conteúdo por convenção): descartada — é exatamente a
  "convenção informal" que `PHASE-1.md §8` já havia rejeitado para eventos, pelo
  mesmo motivo: nada impede a operação errada de existir além de disciplina.
- **Linhas versionadas com contador incremental** (`version = version + 1` a
  cada mudança, mantendo todas as versões): descartada — duplicaria o que
  `superseded_by` já expressa (qual memória substituiu qual), com mais
  complexidade de consulta para nenhum ganho: a pergunta que importa é "qual é
  a vigente" e "o que veio antes dela", não "quantas revisões houve".
- **Confiança como critério de vigência** (a memória com maior `confidence`
  vence, não a mais recente): descartada — faria o sistema ignorar o usuário
  quando ele mudasse de ideia com hesitação (`confidence` baixa na nova
  afirmação), o oposto do comportamento desejado. Contracts §6 já fixa
  "`observed_at`/mais recente vence" como o padrão do projeto para o Context
  Engine; esta decisão estende o mesmo princípio à memória.
- **Trigger de `DELETE` bloqueado, como em `events`/`context_snapshots`**
  (nenhuma remoção física possível): descartada — memória pode conter dado
  pessoal declarado pelo usuário, e negar a ele a possibilidade de apagá-lo de
  verdade contraria `PHASE-3.md §16` diretamente. A assimetria com os dois
  componentes anteriores é intencional e registrada aqui, não um descuido.

## Consequências

- Toda correção e toda contradição são auditáveis: nada desaparece sem
  `invalidation_reason` ou sem um `superseded_by` explícito apontando para o
  que veio depois.
- O volume de linhas cresce com o tempo (nenhuma correção reduz o total).
  Aceitável na escala de um assistente pessoal; deduplicação por fingerprint
  (ver `memory/consolidation.py`) evita o caso degenerado de reafirmações
  idênticas da mesma fonte inflando a tabela.
- Toda consulta por padrão precisa filtrar vigência (`active_at`,
  `include_invalidated`, `include_superseded`) para não misturar fatos vigentes
  com histórico — o `MemoryRepository` já nasce com esses três parâmetros em
  `MemoryCriteria`, não como adição posterior.
- `purge` sendo irreversível e explícito significa que nenhum fluxo automático
  (consolidação, reforço, expiração por tempo) jamais remove uma linha
  fisicamente — só um pedido humano direto, via CLI (`jarvis memory forget
  --purge`) ou, nas fases futuras, via uma ação equivalente do Agent Runtime
  sob aprovação do Policy Engine.
