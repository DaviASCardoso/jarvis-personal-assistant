JARVIS — Fase 3: Memory System

1. Objetivo

A Fase 3 implementará o Memory System do JARVIS.

O objetivo não é apenas criar um banco de dados para armazenar informações. O objetivo é transformar o contrato conceitual de memória em um subsistema capaz de:

- armazenar memórias persistentes;
- diferenciar tipos de memória;
- controlar validade temporal;
- representar importância e confiança;
- registrar origem e proveniência;
- recuperar memórias relevantes;
- suportar busca semântica quando apropriado;
- combinar relevância semântica, recência, importância e confiança;
- impedir que a memória fique acoplada ao LLM;
- permitir que o Agent Runtime consulte e escreva memória por meio de ports;
- manter a arquitetura preparada para o futuro Context Engine e Agent Runtime;
- preservar a arquitetura Ports & Adapters existente;
- fornecer testes determinísticos e suficientes para provar as invariantes.

A Fase 3 deve produzir um Memory System real e utilizável pelo restante do JARVIS, mas não deve implementar Agent Runtime, LLM reasoning, Skills, Policy Engine, MCP ou voz.

---

2. Estado anterior

A Foundation está concluída.

A Fase 1 implementou o Event System, incluindo:

- Event;
- RecordedEvent;
- Event Store persistente;
- Event Bus;
- consumers;
- idempotência;
- correlação e causalidade;
- consultas temporais;
- CLI;
- testes de arquitetura;
- persistência SQLite.

A documentação arquitetural já estabelece que o Memory System deve ser independente do LLM.

O contrato existente define:

- "MemoryRepository" como port de persistência;
- "EmbeddingProvider" como port separado;
- "LLMProvider" como abstração diferente;
- preferências do usuário como memória, não configuração;
- memória com metadados explícitos;
- "relevance" como score derivado durante retrieval, não como propriedade persistida.

Essas decisões devem ser consideradas normativas.

---

3. Contratos de Memory

O contrato atual define seis tipos principais:

1. episódica;
2. semântica;
3. preferência;
4. procedural;
5. working;
6. task.

Uma memória possui conceitualmente:

memory_id
type
content

created_at
updated_at
last_accessed_at

importance
confidence

source

valid_from
valid_until

entities
tags

embedding
embedding_provider
embedding_model_version

Nem todos os campos precisam necessariamente ser obrigatórios para todos os tipos.

O planejamento deve definir quais são:

- obrigatórios;
- opcionais;
- derivados;
- mutáveis;
- imutáveis depois da criação.

---

4. Distinções obrigatórias

4.1 Importance

"importance" representa o quanto uma memória é importante para ser preservada/recuperada.

Não significa que a informação seja verdadeira.

Exemplo:

importance = 0.95
confidence = 0.40

pode significar:

«"Esta informação seria muito importante se fosse verdadeira, mas temos baixa confiança nela."»

---

4.2 Confidence

"confidence" representa o grau de confiança de que a memória representa corretamente um fato.

Não deve ser confundida com importância.

---

4.3 Relevance

"relevance" não é armazenada como atributo permanente da memória.

É calculada durante uma consulta.

O score pode considerar, conforme o planejamento técnico:

semantic_similarity
+
recency
+
importance
+
confidence
+
query/type filters

A fórmula exata ainda não está determinada.

O planejamento da Fase 3 deve propor uma fórmula simples, explicável e testável, evitando um sistema sofisticado de ranking sem necessidade.

---

5. Memory Lifecycle

O planejamento deve definir o ciclo de vida completo:

Candidate Memory
       ↓
Validation
       ↓
Creation
       ↓
Persistence
       ↓
Retrieval
       ↓
Access
       ↓
Update / Reinforcement
       ↓
Expiration / Invalidation

Também deve definir:

- quando uma memória pode ser criada;
- quando pode ser atualizada;
- como "updated_at" funciona;
- como "last_accessed_at" funciona;
- como memórias temporárias expiram;
- se memória expirada é apagada ou apenas marcada como inválida;
- como memórias contraditórias coexistem;
- como memórias antigas são substituídas ou reforçadas.

Não assumir que toda memória deve ser sobrescrita.

---

6. Proveniência

Toda memória relevante deve possuir uma origem rastreável.

Exemplos:

source = user
source = event
source = agent
source = system
source = imported

O planejamento deve definir se "source" será apenas uma categoria ou se haverá uma estrutura mais detalhada de provenance.

Sempre que possível, a memória deve conseguir responder:

«"De onde esta informação veio?"»

Isso é especialmente importante para evitar que uma inferência do agente seja tratada como fato fornecido pelo usuário.

---

7. Contradições

O sistema precisa tratar situações como:

Memory A:
"Usuário prefere Python."
confidence = 0.9

Memory B:
"Usuário prefere Rust."
confidence = 0.8

Não implementar simplesmente:

UPDATE memory SET content = ...

sem definir a semântica.

O planejamento deve decidir como representar:

- versões;
- fatos conflitantes;
- confidence diferente;
- validade temporal;
- proveniência;
- eventual resolução futura.

A regra deve evitar apagar silenciosamente evidências anteriores.

---

8. Embeddings

O Memory System pode utilizar embeddings para retrieval semântico.

A arquitetura exige que:

Memory System
      ↓
EmbeddingProvider

e não:

Memory System
      ↓
LLMProvider
      ↓
embedding

"EmbeddingProvider" deve ser um port independente.

O sistema deve saber qual provider/modelo produziu determinado embedding.

Isso é necessário porque embeddings produzidos por modelos diferentes não devem ser comparados silenciosamente.

O planejamento deve decidir:

- interface do "EmbeddingProvider";
- formato do vetor;
- dimensionalidade;
- quando gerar embedding;
- se a geração é síncrona;
- como tratar falha do provider;
- como versionar embeddings;
- como lidar com mudança futura de modelo;
- se embeddings podem ser regenerados;
- como identificar embeddings incompatíveis.

---

9. Persistência

A arquitetura exige:

Core
  ↓
MemoryRepository
  ↓
Infrastructure adapter
  ↓
database

O domínio não deve importar:

- PostgreSQL;
- pgvector;
- psycopg;
- SQLAlchemy;
- drivers específicos;
- detalhes de schema.

O Repository deve trafegar entidades de domínio e objetos próprios do Core, não linhas SQL ou dictionaries crus.

---

10. PostgreSQL + pgvector

O roadmap original prevê PostgreSQL + pgvector para a memória.

Entretanto, a Fase 1 deliberadamente escolheu SQLite para o Event Store porque o projeto é pessoal e evitar infraestrutura externa era uma prioridade.

Portanto, o planejamento da Fase 3 deve avaliar explicitamente:

Opção A — PostgreSQL + pgvector

Vantagens:

- banco apropriado para produção;
- excelente suporte a dados relacionais;
- pgvector;
- busca vetorial madura;
- possibilidade de crescer posteriormente.

Desvantagens:

- serviço externo;
- maior complexidade operacional;
- Docker ou instalação local;
- configuração adicional;
- maior custo de desenvolvimento para um projeto pessoal.

Opção B — SQLite + extensão vetorial

Deve ser considerada caso seja tecnicamente suficiente.

Opção C — armazenamento vetorial separado

Só considerar se existir necessidade concreta.

Regra

Não escolher tecnologia apenas por "ser mais profissional".

A escolha deve ser justificada pela necessidade real da Fase 3.

Se PostgreSQL + pgvector for escolhido, o plano deve especificar exatamente como será executado localmente, considerando o ambiente de desenvolvimento existente.

Se uma nova decisão arquitetural difícil de reverter surgir, criar ADR.

---

11. Retrieval

O Memory System deve oferecer pelo menos dois conceitos diferentes:

Lookup estruturado

Exemplos:

buscar por tipo
buscar por período
buscar por entidade
buscar por tags
buscar por validade
buscar por importance

Semantic retrieval

Exemplo:

query:
"o que eu costumo usar para programar?"

→ embedding da consulta

→ candidatos semanticamente próximos

→ ranking

→ resultado ordenado

Os dois mecanismos não devem ser confundidos.

O planejamento deve decidir se serão APIs separadas ou uma API de retrieval capaz de combinar filtros.

---

12. Ranking

A Fase 3 deve implementar um ranking inicial simples.

Uma possível estrutura conceitual:

relevance =
    semantic_score
    × semantic_weight
    +
    recency_score
    × recency_weight
    +
    importance
    × importance_weight
    +
    confidence
    × confidence_weight

Isso é apenas uma direção inicial.

O Claude deve avaliar uma fórmula melhor durante o planejamento.

Requisitos:

- determinística;
- explicável;
- testável;
- sem LLM;
- sem treinamento;
- sem sistema complexo de ML.

O resultado deve permitir entender por que uma memória foi considerada relevante.

---

13. Recência

O sistema deve considerar que memórias podem perder relevância com o tempo.

O planejamento deve definir:

- função de decay;
- se o decay depende do tipo;
- como "valid_until" interage com recência;
- como memória permanente se comporta;
- como "last_accessed_at" influencia ou não o score.

Evitar transformar isso em um sistema de recomendação complexo.

---

14. Working Memory e Task Memory

Esses tipos podem ter características diferentes das memórias persistentes.

O planejamento deve avaliar:

Working Memory
→ curta duração
→ alto acesso
→ possível TTL

Task Memory
→ associada a uma tarefa
→ pode expirar quando a tarefa termina

Não criar um segundo banco apenas por princípio.

Se o mesmo backend for suficiente, utilizar o mesmo backend com semântica diferente.

---

15. Integração com Event System

A Fase 3 pode utilizar o Event System existente para eventos relacionados à memória.

Exemplos:

memory.created
memory.updated
memory.invalidated
memory.accessed

Entretanto, não criar uma avalanche de eventos sem necessidade.

O planejamento deve decidir quais eventos são realmente úteis para:

- observabilidade;
- auditoria;
- integração futura;
- reconstrução de estado.

O Memory System não deve depender do Agent Runtime para funcionar.

---

16. Segurança e privacidade

Memória potencialmente contém informações pessoais.

Portanto:

- não registrar conteúdo sensível em logs;
- não colocar memória inteira em mensagens de erro;
- não expor conteúdo desnecessariamente;
- não armazenar secrets como memória comum;
- manter separação entre secrets e memory;
- testar caminhos de acesso e isolamento.

A implementação não deve inventar um sistema completo de criptografia ou controle de usuários se isso não for necessário nesta fase.

---

17. Independência do LLM

É uma regra arquitetural central.

Isto é proibido:

MemoryRepository
    ↓
OpenAI SDK

Também é proibido:

MemoryManager
    ↓
LLMProvider.generate(...)

para realizar operações básicas de memória.

O Memory System deve funcionar mesmo sem nenhum LLM configurado.

---

18. Testes

A Fase 3 deve possuir testes para:

Domínio

- criação;
- validação;
- imutabilidade quando aplicável;
- tipos de memória;
- timestamps;
- validade;
- importance;
- confidence.

Repository

- criação;
- leitura;
- atualização;
- filtros;
- validade;
- isolamento;
- persistência.

Retrieval

- filtros estruturados;
- busca semântica;
- ranking;
- recência;
- importance;
- confidence;
- combinação de scores.

Embeddings

- provider correto;
- incompatibilidade de modelo;
- falha do provider;
- ausência de embedding.

Contratos arquiteturais

Garantir que:

Memory Core
    não importa
        banco concreto
        SDK de embedding
        SDK de LLM

Integração

Testar o fluxo completo:

Memory
→ Repository
→ persistência
→ retrieval
→ ranking

Os testes devem ser determinísticos.

---

19. CLI / ferramenta de diagnóstico

A Fase 3 deve fornecer uma forma simples de demonstrar o sistema.

O planejamento deve definir comandos equivalentes a:

jarvis memory add ...
jarvis memory list ...
jarvis memory search ...
jarvis memory get ...

A CLI é principalmente uma interface de diagnóstico e teste.

Ela não deve antecipar o Agent Runtime.

---

20. Documentação

Ao final da fase, atualizar:

- "docs/memory-system.md";
- "docs/README.md";
- "CLAUDE.md", caso a estrutura real tenha mudado;
- "README.md", caso o uso público do projeto tenha mudado;
- "ROADMAP.md".

Criar ADRs somente para decisões arquiteturais realmente significativas.

Não criar ADR para:

- nomes triviais;
- funções internas;
- detalhes facilmente reversíveis;
- escolhas que já estejam determinadas pelos contratos.

---

21. Fora de escopo

Não implementar nesta fase:

- Agent Runtime;
- LLM reasoning;
- Policy Engine;
- Skills;
- Tool Router;
- MCP;
- Gmail;
- calendário;
- WhatsApp;
- STT;
- TTS;
- wake word;
- interface gráfica;
- automação do computador;
- proactive agent completo;
- autenticação multiusuário;
- deployment;
- cloud hosting;
- sistema distribuído;
- treinamento de modelos;
- fine-tuning.

O Memory System deve apenas fornecer uma infraestrutura sólida para esses componentes futuros.

---

22. Critérios de conclusão

A Fase 3 só está concluída quando:

- Memory domain implementado;
- MemoryRepository definido;
- adapter persistente implementado;
- EmbeddingProvider definido;
- embedding storage implementado, se necessário;
- retrieval estruturado implementado;
- semantic retrieval implementado;
- ranking implementado;
- recência implementada;
- importance/confidence corretamente diferenciados;
- validade temporal implementada;
- provenance implementada;
- contradições tratadas conforme decisão explícita;
- Working/Task Memory tratadas;
- CLI de diagnóstico funcionando;
- testes abrangentes passando;
- teste arquitetural garantindo independência do LLM e banco;
- documentação atualizada;
- ADRs necessários criados;
- CI verde;
- "uv sync --locked" funcionando;
- "ruff" verde;
- "mypy" verde;
- "pytest" verde;
- working tree limpo;
- commits organizados;
- nenhum push realizado durante a execução da fase.

---

23. Regra de desenvolvimento

A Fase 3 deve ser executada como uma única unidade de desenvolvimento.

Primeiro:

PLANEJAR

Depois:

IMPLEMENTAR

Depois:

VALIDAR

Depois:

REVISAR RESULTADO

Depois:

COMMITAR

Não dividir artificialmente a fase em várias sessões humanas se isso não trouxer benefício técnico.

O plano deve, entretanto, definir internamente uma ordem segura de implementação.

---

24. Princípio principal

O Memory System não deve tentar ser "inteligente".

Ele deve ser uma infraestrutura determinística, previsível e testável que permita ao futuro Agent Runtime ter memória.

A inteligência vem depois.

A memória precisa primeiro ser correta.
