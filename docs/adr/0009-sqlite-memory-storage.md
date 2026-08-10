# 0009. SQLite como armazenamento do Memory System

**Status:** Accepted
**Data:** 2026-08-10

## Contexto

O `ROADMAP.md` original prevê PostgreSQL + pgvector para a memória (subfase 3.2).
A Fase 1, no entanto, já havia escolhido deliberadamente SQLite para o Event Store
([ADR-0007](0007-sqlite-event-store.md)) por o projeto ser pessoal, de processo
único, e por evitar infraestrutura externa sem necessidade concreta — regra 11 do
roadmap e `architecture-contracts.md §1`.

`PHASE-3.md §10` exige que essa tensão seja avaliada explicitamente, com pelo
menos três opções comparadas (PostgreSQL + pgvector; SQLite + extensão vetorial;
armazenamento vetorial separado), e proíbe escolher tecnologia "apenas por ser
mais profissional" — a escolha precisa ser justificada pela necessidade real
desta fase.

A necessidade real foi medida, não suposta: varredura exata de cosseno em Python
puro (`array` + `map`), neste mesmo ambiente (CPython 3.13.14, Windows AMD64):

| memórias × dimensões | tempo |
|---|---|
| 1 000 × 256 | 11 ms |
| 10 000 × 256 | 109 ms |
| 10 000 × 768 | 321 ms |
| 50 000 × 768 | 1,6 s |

Dez mil memórias é um volume muito maior do que um assistente pessoal de um
usuário só acumula em uso normal, e 109 ms é irrelevante para uma CLI ou para um
ciclo de agente. O índice aproximado que o pgvector oferece resolveria um
gargalo que este projeto não tem — e ainda trocaria exatidão por velocidade,
quando a varredura exata é justamente o que torna o retrieval determinístico e
testável (`PHASE-3.md §18`).

## Decisão

Um único banco SQLite (`<JARVIS_DATA_DIR>/memory.db`) guarda memórias e
embeddings, atrás do port `MemoryRepository`
([`architecture-contracts.md §11`](../architecture-contracts.md#11-persistence-boundary)).
O embedding é uma coluna `BLOB` (`float32` little-endian) com
`embedding_provider`/`embedding_model`/`embedding_dimensions` ao lado. A busca
semântica filtra candidatos por SQL (tipo, validade, `subject`, modelo de
embedding compatível) e calcula o cosseno **no Core**, por varredura exata,
sobre esse conjunto já filtrado — nunca no adapter, e nunca com índice
aproximado.

## Alternativas consideradas

| Critério | PostgreSQL + pgvector | SQLite + varredura (escolhida) | SQLite + `sqlite-vec` | Vector store separado |
|---|---|---|---|---|
| Instalação | serviço externo + Docker ou instalação local | nenhuma (stdlib) | wheel extra + `load_extension` | serviço ou dependência pesada |
| Dependências novas | driver (`psycopg`) + serviço | zero | `sqlite-vec` | cliente + servidor |
| Testes | precisa de instância real ou fixture pesada | `:memory:`, instantâneo | idem, com risco por plataforma | mock ou serviço em CI |
| Busca vetorial | madura, com índice ANN | exata, ~109 ms @ 10k | ANN embutido | madura |
| Manutenção | upgrades, backup, tuning | copiar um arquivo | acompanhar versão da extensão | mais um sistema |
| Reversibilidade | — | alta: o port isola; migrar = novo adapter + export/import | alta | média |

- **PostgreSQL + pgvector**: descartada para esta fase. Resolve um gargalo que a
  medição mostra não existir, ao custo de um serviço externo permanente e Docker,
  que o [README](../../README.md) evita deliberadamente. `ADR-0007` já havia
  previsto essa possibilidade como condicional ("a Fase 3 pode adotá-lo"), não
  obrigatória.
- **SQLite + `sqlite-vec`**: descartada por ora, mas verificada —
  `sqlite3.enable_load_extension` funciona neste ambiente. Adicioná-la agora
  seria uma dependência e um formato de índice a manter para ganhar velocidade
  que não falta. Fica registrada como o gatilho de escalada: se a varredura
  passar de ~300 ms em uso real, troca-se o cálculo dentro do adapter, sem tocar
  no Core.
- **Vector store separado**: descartada — acrescenta um segundo sistema de
  armazenamento e a necessidade de mantê-lo consistente com o relacional, sem
  nenhum requisito que peça isso.

## Consequências

- O projeto passa a ter três arquivos SQLite (`events.db`, `context.db`,
  `memory.db`), um por componente, cada um atrás do seu próprio port — coerente
  com o padrão já estabelecido nas Fases 1 e 2.
- **Diverge do `ROADMAP.md` 3.2**, que previa PostgreSQL + pgvector
  explicitamente. A divergência está documentada em
  [`docs/phase-3-plan.md`](../phase-3-plan.md) §29 e refletida no `ROADMAP.md`
  com a mesma anotação inline usada nas subfases 1.4/2.2 para desvios
  equivalentes.
- Migrar para PostgreSQL depois, se a necessidade se materializar, é contido: um
  novo `PostgresMemoryRepository` + configuração; nenhuma mudança em domínio,
  ranking, retrieval ou nos testes que não são do adapter — exatamente a
  garantia que a regra de dependência (Ports & Adapters) existe para dar.
- Não resolve concorrência de escrita entre múltiplos processos. Se o Jarvis
  passar a rodar como vários processos acessando a mesma memória, esta decisão
  precisa ser revisitada por um novo ADR — não por uma alteração deste.
