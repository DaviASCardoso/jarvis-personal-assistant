# Jarvis — Fase 5: Skills, Policy Engine, Tool Router e MCP

## 1. Objetivo da fase

A Fase 5 transforma o Jarvis de um sistema capaz de observar, contextualizar, armazenar memória e raciocinar sobre eventos em um sistema capaz de **agir no mundo de forma estruturada e segura**.

O objetivo não é simplesmente "criar funções que o LLM pode chamar".

O objetivo é implementar a cadeia arquitetural:

Event / User Input
        ↓
Context + Memory
        ↓
Agent Runtime
        ↓
Decision
        ↓
Policy Engine
        ↓
Skill
        ↓
Tool Router
        ↓
MCP Server
        ↓
MCP Tool / External System

E também o caminho de retorno:

External System
        ↓
Tool result
        ↓
Skill result
        ↓
Agent Runtime
        ↓
Memory / Events / User response

A fase deve transformar os contratos arquiteturais previamente definidos em componentes executáveis, mantendo as fronteiras estabelecidas desde a Foundation.

---

# 2. Estado arquitetural esperado antes da Fase 5

As fases anteriores já estabeleceram a base do sistema.

O Claude Code deve tratar o estado real do repositório como autoridade.

Antes de implementar qualquer coisa, deve ler:

- ROADMAP.md
- CLAUDE.md
- README.md
- docs/architecture-contracts.md
- docs/architecture.md
- docs/event-system.md
- docs/context-system.md
- docs/memory-system.md
- docs/agent-runtime.md
- docs/skills.md
- docs/mcp.md
- docs/security.md
- docs/adr/README.md
- todos os ADRs existentes
- documentação específica das fases anteriores
- código existente em src/
- testes existentes em tests/

Não assumir que a estrutura atual do código corresponde exatamente à estrutura prevista nesta especificação.

O código existente é a fonte de verdade sobre a implementação atual.

Esta especificação define o objetivo arquitetural da Fase 5.

---

# 3. Problema que a fase resolve

Até esta fase, o Jarvis possui capacidade crescente de:

- receber eventos;
- persistir eventos;
- distribuir eventos;
- construir contexto;
- armazenar e recuperar memória;
- executar o runtime cognitivo;
- receber decisões;
- trabalhar com LLM;
- compreender o mundo atual.

Mas existe uma diferença fundamental entre:

> "o Jarvis decidiu que deveria fazer X"

e

> "o Jarvis está autorizado e tecnicamente capacitado a fazer X".

Essa diferença é responsabilidade da Fase 5.

O Agent Runtime não deve executar diretamente ferramentas externas.

O LLM também não deve executar diretamente ferramentas externas.

Uma Skill não deve possuir autoridade própria para decidir se uma ação é permitida.

A cadeia correta deve ser:

LLM / Agent
    ↓
Decision
    ↓
Policy Engine
    ↓
allow / deny / require_confirmation
    ↓
Skill
    ↓
Tool Router
    ↓
MCP
    ↓
External system

---

# 4. Conceitos fundamentais

## 4.1 Skill

Uma Skill representa uma **capacidade de alto nível do Jarvis**.

Exemplos conceituais:

- enviar uma mensagem;
- consultar agenda;
- criar uma tarefa;
- controlar uma impressora;
- consultar informações de um sistema;
- abrir uma aplicação;
- iniciar uma impressão;
- consultar status de uma máquina.

Uma Skill não deve ser simplesmente uma função genérica.

Ela representa uma intenção operacional conhecida pelo agente.

Exemplo conceitual:

    print_document

é uma Skill.

Ela pode internamente utilizar uma ou várias Tools.

---

# 5. Skill não é Tool

Esta distinção deve ser preservada.

### Skill

Representa:

> "O que o Jarvis quer realizar."

### Tool

Representa:

> "Uma operação técnica que pode ser executada."

### MCP Server

Representa:

> "Um servidor que disponibiliza ferramentas para o Jarvis."

### MCP Tool

Representa:

> "Uma ferramenta específica exposta por um MCP Server."

Exemplo:

Skill:

    print_document

Pode utilizar:

    Tool:
        upload_file
        start_print
        get_printer_status

Essas Tools podem ser disponibilizadas por:

    MCP Server:
        bambu-lab

---

# 6. Policy Engine

O Policy Engine é uma das partes mais importantes da Fase 5.

Ele é a **autoridade determinística de autorização**.

O LLM pode sugerir uma ação.

A Skill pode declarar características de risco.

Nenhuma dessas duas coisas significa que a ação está autorizada.

Somente o Policy Engine pode produzir:

    allow
    
    deny
    
    require_confirmation

---

# 7. Regra fundamental de autoridade

A seguinte regra deve ser estruturalmente preservada:

> Skill nunca autoriza a si mesma.

Uma Skill pode declarar:

- risk;
- confirmation_requirement;
- efeitos esperados;
- ferramentas necessárias;
- parâmetros;
- escopo.

Mas isso é apenas informação utilizada pelo Policy Engine.

Exemplo:

    Skill:
        name = "send_message"
        risk = "medium"
        confirmation_requirement = "conditional"

Isso NÃO significa:

    allow = true

A decisão continua sendo:

    Policy Engine
        ↓
    PolicyVerdict

---

# 8. PolicyVerdict

A implementação deve representar explicitamente o resultado da política.

Conceitualmente:

    PolicyVerdict {
        decision:
            allow | deny | require_confirmation
    
        reason
    
        policy_id / policy_version
    
        approval
    }

Os campos exatos devem ser determinados pelo planejamento da fase e pelos contratos existentes.

Não introduzir mecanismos criptográficos, JWT ou tokens de autorização sem necessidade arquitetural.

A ideia de `PolicyApproval` já existe como conceito de domínio.

A implementação concreta deve respeitar o ADR correspondente.

---

# 9. PolicyApproval

`PolicyApproval` representa uma autorização emitida pelo Policy Engine para uma execução específica.

Ele não deve ser confundido com:

- confirmação do usuário;
- decisão do LLM;
- metadado da Skill;
- permissão permanente.

Exemplo:

    Decision
       ↓
    Policy Engine
       ↓
    PolicyApproval
       ↓
    Skill execution

A aprovação deve ser vinculada à ação/execution específica.

Não deve existir um mecanismo onde uma Skill obtenha uma autorização genérica e reutilizável indefinidamente.

---

# 10. Confirmation

A política pode exigir confirmação do usuário.

Exemplo:

    User:
        "Mande uma mensagem para João dizendo que vou chegar às 20h."

O Agent pode produzir a intenção.

O Policy Engine pode decidir:

    require_confirmation

O Jarvis deve então apresentar uma solicitação ao usuário.

Somente após a confirmação explícita a execução pode continuar.

A confirmação deve ser diferente de:

    allow

e diferente de:

    deny

---

# 11. Tool Router

O Tool Router é a fronteira entre Skills e mecanismos concretos de execução.

Responsabilidades:

- receber uma requisição de execução;
- identificar a Tool adequada;
- resolver o provider/server;
- validar parâmetros;
- executar;
- normalizar o resultado;
- devolver resultado estruturado;
- produzir eventos/auditoria quando necessário.

O Tool Router não deve decidir políticas.

Ele recebe autorização já determinada pelo Policy Engine.

---

# 12. MCP

MCP deve ser tratado como protocolo/fronteira de integração, não como sinônimo de Skill.

O Jarvis deve ser capaz de conversar com MCP Servers externos.

A arquitetura deve permitir:

    Jarvis
       ↓
    Tool Router
       ↓
    MCP Client
       ↓
    MCP Server
       ↓
    MCP Tool
       ↓
    External System

O Jarvis não deve acoplar seu domínio aos detalhes específicos de um MCP Server.

---

# 13. MCP Server

Um MCP Server externo pode disponibilizar ferramentas para o Jarvis.

Exemplos futuros:

- Todoist;
- Google Calendar;
- Gmail;
- computador;
- impressora;
- serviços web;
- automações;
- sistemas pessoais.

Essas integrações devem ficar atrás das interfaces apropriadas.

O domínio não deve importar SDKs ou clientes MCP concretos.

---

# 14. MCP Tool

Uma MCP Tool possui:

- nome;
- descrição;
- schema de entrada;
- schema de saída;
- mecanismo de execução.

O Jarvis deve tratar esses dados como capacidade externa.

Não assumir que toda MCP Tool é segura.

MCP disponibiliza capacidade técnica.

Policy determina autorização.

Essa distinção é crítica.

---

# 15. Segurança

O sistema deve assumir que ferramentas externas são potencialmente perigosas.

Exemplos de ações de risco:

- enviar mensagens;
- enviar emails;
- apagar arquivos;
- apagar dados;
- comprar algo;
- publicar conteúdo;
- iniciar máquinas;
- iniciar impressão;
- alterar configurações;
- executar comandos no computador.

O Policy Engine deve ser capaz de classificar ou receber classificação de risco suficiente para decidir.

Nunca permitir:

    LLM → Tool

sem passar pela fronteira de autorização definida na arquitetura.

---

# 16. Princípio LLM ≠ autoridade

O LLM é um componente de raciocínio.

Ele pode:

- interpretar intenção;
- escolher uma Skill;
- preencher parâmetros;
- propor uma ação;
- interpretar resultados.

Ele não pode:

- conceder autorização;
- alterar políticas;
- ignorar confirmação;
- executar diretamente ferramentas;
- decidir que uma ação proibida está permitida.

A regra:

    LLM proposes.
    Code authorizes.
    Skill executes.

deve permanecer verdadeira.

---

# 17. Execução de Skill

Uma execução conceitual deve seguir:

    SkillExecutionRequest
        ↓
    Policy Engine
        ↓
    PolicyVerdict
        ↓
    [deny]
        → ExecutionDenied
    
    [require_confirmation]
        → ConfirmationRequested
        → UserConfirmation
        → Policy approval
        → continue
    
    [allow]
        ↓
    Tool Router
        ↓
    Tool
        ↓
    Result

A implementação deve garantir que não exista caminho alternativo que permita executar uma Skill sem passar pela política.

---

# 18. Identidade da execução

Cada execução deve possuir uma identidade própria.

Exemplo conceitual:

    execution_id

Essa identidade deve permitir correlacionar:

- decisão;
- policy verdict;
- approval;
- skill execution;
- tool execution;
- MCP request;
- resultado;
- eventos;
- auditoria.

Utilizar os mecanismos de correlation/causation já estabelecidos pelo Event System.

Não criar um segundo sistema paralelo de rastreamento sem necessidade.

---

# 19. Idempotência

A arquitetura deve considerar ações que podem ser repetidas.

Exemplo:

    send_message

Se uma execução for repetida devido a:

- retry;
- timeout;
- reconexão;
- duplicação de evento;

o sistema não deve enviar a mesma mensagem duas vezes quando a operação exigir idempotência.

A estratégia exata deve ser determinada durante o planejamento.

Não assumir que todas as Tools possuem comportamento idempotente.

---

# 20. Erros

Os erros devem ser estruturados.

Diferenciar:

- policy denial;
- confirmation required;
- invalid arguments;
- tool unavailable;
- MCP connection failure;
- external API failure;
- timeout;
- authentication failure;
- permission failure;
- execution failure.

Não transformar tudo em uma exceção genérica.

O Agent Runtime precisa conseguir interpretar esses resultados.

---

# 21. Resultados de Tools

Uma Tool não deve retornar texto arbitrário como único contrato.

O resultado deve possuir estrutura suficiente para:

- indicar sucesso;
- indicar falha;
- transportar dados;
- fornecer mensagem legível;
- permitir correlação;
- preservar metadados relevantes.

A implementação exata deve seguir os contratos existentes e o plano produzido pelo Claude Code.

---

# 22. Eventos gerados

A execução das Skills deve integrar-se ao Event System existente.

Exemplos conceituais:

    SkillExecutionRequested
    
    PolicyEvaluated
    
    ConfirmationRequested
    
    SkillExecutionStarted
    
    SkillExecutionCompleted
    
    SkillExecutionFailed
    
    ToolExecutionStarted
    
    ToolExecutionCompleted
    
    ToolExecutionFailed

Não criar eventos apenas porque "parece legal".

Cada evento deve possuir propósito operacional ou de auditoria.

Respeitar:

- imutabilidade;
- occurred_at;
- recorded_at;
- event_id;
- correlation_id;
- causation_id;
- idempotência.

---

# 23. Auditoria

A execução de ações importantes deve ser observável posteriormente.

Deve ser possível responder:

- quem solicitou a ação?
- qual foi a intenção?
- qual Skill foi escolhida?
- qual política foi aplicada?
- qual foi o verdict?
- houve confirmação?
- qual Tool foi executada?
- qual MCP Server foi utilizado?
- qual foi o resultado?
- quando ocorreu?
- qual evento causou a execução?

A auditoria deve reutilizar o Event System quando apropriado.

Não criar um banco paralelo de auditoria sem necessidade.

---

# 24. Observabilidade

A execução deve permitir debugging.

Registrar, quando apropriado:

- execution_id;
- skill;
- tool;
- MCP server;
- duração;
- resultado;
- erro;
- policy verdict;
- correlation_id.

Não registrar:

- secrets;
- tokens;
- credenciais;
- conteúdo sensível desnecessário.

---

# 25. Descoberta de Tools

O Jarvis deverá eventualmente conseguir descobrir capacidades disponíveis.

Conceitualmente:

    MCP Server
       ↓
    Tool discovery
       ↓
    Tool registry
       ↓
    Tool Router

O registry não deve virar uma segunda fonte de verdade para o domínio.

Ele representa capacidades disponíveis no ambiente.

A estratégia de cache, refresh e persistência deve ser definida no plano.

---

# 26. Registro de Skills

Skills internas do Jarvis devem possuir registro explícito.

Exemplo conceitual:

    SkillRegistry

Cada Skill pode declarar:

- nome;
- descrição;
- schema;
- risco;
- requisitos;
- tools necessárias;
- executor.

O registro deve permitir que o Agent Runtime encontre Skills disponíveis.

Não permitir que o LLM invente arbitrariamente o nome de uma Skill e consiga executá-la.

---

# 27. Schemas

As entradas de Skills e Tools devem ser validadas antes da execução.

O sistema deve rejeitar:

- campos desconhecidos quando isso violar o contrato;
- tipos inválidos;
- campos obrigatórios ausentes;
- valores fora dos limites;
- parâmetros inconsistentes.

O LLM não é confiável como validador.

Validação deve ocorrer em código.

---

# 28. Separação entre intenção e execução

Não misturar:

    "quero fazer X"

com:

    "X foi executado."

A arquitetura deve preservar essa diferença.

Exemplo:

    Intent
       ↓
    Decision
       ↓
    Policy
       ↓
    Execution
       ↓
    Result

Isso é essencial para:

- confirmação;
- auditoria;
- retries;
- memória;
- debugging;
- eventos.

---

# 29. Integração com Agent Runtime

O Agent Runtime existente deve ser adaptado para utilizar Skills.

O fluxo esperado é:

    Context
    +
    Memory
    +
    Event/User input
        ↓
    Agent
        ↓
    LLM
        ↓
    Decision
        ↓
    Policy
        ↓
    Skill
        ↓
    Tool
        ↓
    Result
        ↓
    Agent
        ↓
    Response / Memory / Events

O Agent Runtime não deve conhecer detalhes concretos de:

- SQLite;
- HTTP clients;
- SDKs;
- MCP servers específicos;
- ferramentas externas.

---

# 30. Integração com MCP

A implementação deve possuir uma abstração suficientemente limpa para que futuramente seja possível conectar:

- serviços pessoais;
- aplicações;
- sistemas locais;
- serviços cloud;
- dispositivos físicos.

A arquitetura não deve ser desenhada exclusivamente para uma integração.

---

# 31. Impressora 3D

A arquitetura deve permanecer compatível com integrações físicas futuras.

Um exemplo importante é uma impressora 3D.

Futuramente:

    Jarvis
       ↓
    Skill: manage_print
       ↓
    Tool
       ↓
    MCP / adapter
       ↓
    Bambu Lab

Isso não significa que a Fase 5 deva implementar uma integração específica com a Bambu Lab.

A Fase 5 deve criar a arquitetura que permita essa integração sem quebrar o Core.

---

# 32. Confirmação e ações físicas

Ações físicas devem poder receber políticas mais restritivas.

Exemplo:

    start_print

pode exigir confirmação.

Já:

    get_printer_status

pode ser permitido automaticamente.

A política deve diferenciar:

- leitura;
- alteração;
- ação destrutiva;
- ação física;
- comunicação externa.

---

# 33. Princípio de menor privilégio

Cada Skill deve possuir apenas acesso às Tools necessárias.

Não criar uma Skill genérica:

    execute_anything

ou:

    call_any_tool_without_policy

Isso destruiria a arquitetura de segurança.

---

# 34. Secrets

Secrets nunca devem entrar em:

- eventos;
- memória;
- logs;
- respostas do LLM;
- commits;
- documentos de arquitetura.

Credenciais devem permanecer na camada apropriada de infraestrutura/configuração.

O Agent Runtime não deve receber secrets diretamente.

---

# 35. Testes

A Fase 5 deve ter testes suficientes para provar as fronteiras arquiteturais.

Testar especialmente:

### Skill

- registro;
- descoberta;
- validação;
- execução;
- erros.

### Policy Engine

- allow;
- deny;
- require_confirmation;
- regras de risco;
- impossibilidade de Skill autoautorizar;
- impossibilidade de bypass.

### Tool Router

- resolução;
- validação;
- execução;
- falha;
- timeout;
- correlação.

### MCP

- discovery;
- chamada;
- erro;
- resposta inválida;
- server indisponível.

### Agent Runtime

- decisão → policy → skill;
- deny;
- confirmation;
- successful execution;
- failed execution.

### Arquitetura

Testes devem impedir imports indevidos entre:

- domain;
- application;
- infrastructure;
- interfaces.

Seguir o padrão de teste arquitetural já estabelecido na Fase 1 quando aplicável.

---

# 36. Testes de segurança

Os seguintes caminhos devem ser explicitamente testados:

    LLM → Tool

deve ser impossível.

    Skill → self-authorize

deve ser impossível.

    Tool → bypass Policy

deve ser impossível.

    require_confirmation → execute

sem confirmação deve ser impossível.

    deny → execute

deve ser impossível.

Esses testes são mais importantes do que aumentar artificialmente a cobertura percentual.

---

# 37. Testes de integração

Utilizar implementações fake/in-memory quando isso for suficiente.

Não depender de serviços externos reais para a maior parte da suíte.

MCP real pode ser coberto por:

- fake server;
- mock controlado;
- test server local.

O objetivo é que CI permaneça:

- determinístico;
- rápido;
- gratuito;
- sem secrets.

---

# 38. Compatibilidade com CI

Tudo deve continuar funcionando com:

    uv sync --locked
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy
    uv run pytest

Não adicionar dependências pesadas sem necessidade.

Não adicionar infraestrutura externa obrigatória para os testes.

---

# 39. Documentação

A Fase 5 deve atualizar a documentação correspondente à implementação.

No mínimo, verificar:

- docs/skills.md
- docs/mcp.md
- docs/security.md
- docs/agent-runtime.md
- docs/architecture.md
- docs/architecture-contracts.md, somente se um contrato realmente precisar mudar
- novos ADRs quando houver decisões arquiteturais novas

Não alterar contratos apenas para acomodar uma implementação ruim.

Se uma decisão arquitetural nova for necessária:

1. identificar;
2. avaliar alternativas;
3. criar ADR;
4. atualizar contratos se necessário;
5. implementar.

---

# 40. ADRs

Não criar ADRs artificialmente.

Criar somente quando houver uma decisão:

- arquitetural;
- relevante;
- difícil de reverter;
- que afete futuras fases.

Exemplos que podem exigir ADR:

- estratégia de Tool Registry;
- modelo de Policy;
- estratégia de MCP connection lifecycle;
- modelo de confirmação;
- persistência de approvals;
- estratégia de retry/idempotência.

Esses exemplos não são decisões pré-aprovadas.

O planejamento deve determinar se realmente são necessárias.

---

# 41. Banco de dados

Não assumir automaticamente uma nova tecnologia de banco.

Reutilizar a infraestrutura existente quando apropriado.

Adicionar persistência somente quando houver necessidade real.

Não criar PostgreSQL, Redis, Kafka etc. apenas por "escalabilidade futura".

O projeto é pessoal.

Simplicidade operacional é uma prioridade.

---

# 42. Cloud

A Fase 5 não deve introduzir infraestrutura cloud desnecessária.

O Jarvis deve continuar sendo um projeto pessoal com:

- baixo custo;
- baixa complexidade;
- fácil desenvolvimento;
- fácil execução local;
- CI gratuito.

Integrações cloud futuras devem ficar atrás das interfaces adequadas.

---

# 43. Escopo

## Dentro do escopo

- Skill model;
- Skill registry;
- Skill execution;
- Policy Engine;
- PolicyVerdict;
- PolicyApproval;
- confirmation flow;
- Tool Router;
- Tool abstraction;
- MCP client boundary;
- MCP discovery;
- MCP execution;
- integração com Agent Runtime;
- integração com Event System;
- auditoria;
- erros;
- testes;
- documentação;
- ADRs necessários.

## Fora do escopo

Não implementar nesta fase:

- novas integrações específicas com serviços pessoais;
- Bambu Lab;
- Todoist;
- Gmail;
- WhatsApp;
- Google Calendar;
- STT;
- TTS;
- novas capacidades complexas de memória;
- novos provedores de LLM;
- UI completa;
- aplicação mobile;
- wake word;
- automações avançadas.

A Fase 5 cria a infraestrutura para essas capacidades futuras.

---

# 44. Princípio de simplicidade

O Jarvis é um projeto pessoal.

Não transformar a arquitetura em um sistema distribuído empresarial.

Preferir:

- interfaces simples;
- processos locais;
- SQLite quando suficiente;
- objetos Python claros;
- poucas dependências;
- testes determinísticos;
- código fácil de entender.

Não adicionar:

- microservices;
- filas distribuídas;
- Kubernetes;
- brokers;
- infraestrutura cloud;

sem uma necessidade concreta.

---

# 45. Critério de conclusão

A Fase 5 está concluída quando:

1. Skills podem ser registradas.
2. Agent Runtime pode solicitar uma Skill.
3. Policy Engine avalia a execução.
4. Deny impede execução.
5. Confirmation bloqueia execução até confirmação.
6. Allow permite execução.
7. Skill executa através do Tool Router.
8. Tool Router consegue trabalhar com Tools.
9. MCP pode ser utilizado como boundary de integração.
10. Resultados retornam ao Agent Runtime.
11. Execuções são correlacionáveis.
12. Eventos de execução são registrados quando apropriado.
13. Auditoria é possível.
14. Erros são estruturados.
15. Secrets não vazam.
16. Testes arquiteturais impedem bypass.
17. CI continua verde.
18. Documentação está atualizada.
19. ADRs necessários estão registrados.
20. Nenhum código de fases posteriores foi implementado prematuramente.

---

# 46. Regra final

A implementação deve preservar a seguinte arquitetura:

    WORLD
      ↓
    EVENTS
      ↓
    CONTEXT + MEMORY
      ↓
    AGENT RUNTIME
      ↓
    LLM
      ↓
    DECISION
      ↓
    POLICY ENGINE
      ↓
    SKILL
      ↓
    TOOL ROUTER
      ↓
    MCP
      ↓
    WORLD

A inteligência decide.

O código valida.

A política autoriza.

A Skill representa a capacidade.

A Tool executa.

O MCP conecta o Jarvis ao mundo.

O Event System registra o que aconteceu.

A Memory permite que o Jarvis aprenda com o histórico.

Nenhuma camada deve assumir responsabilidades pertencentes à outra.
