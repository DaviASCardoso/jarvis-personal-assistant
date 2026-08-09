# Fase 1 — Event System

## 1. Objetivo

Implementar o primeiro núcleo funcional do Jarvis: um sistema de eventos confiável, tipado, persistível e desacoplado do restante da aplicação.

O Event System será a fundação sobre a qual posteriormente serão construídos Context, Memory, Agent Runtime, Skills, Policy e MCP.

A implementação desta fase deve transformar os contratos arquiteturais definidos na Foundation em código real, sem antecipar componentes das fases posteriores.

O objetivo não é criar um "assistente" ainda.

O objetivo é criar a infraestrutura que permita ao futuro Jarvis observar acontecimentos do mundo digital/físico, representá-los de forma consistente e distribuí-los aos componentes consumidores.

---

# 2. Contexto arquitetural

Antes desta fase, a Foundation foi concluída.

A fonte de verdade arquitetural é, nesta ordem:

1. `ROADMAP.md`

2. `CLAUDE.md`

3. `docs/architecture-contracts.md`

4. ADRs aceitos em `docs/adr/`

5. documentação arquitetural em `docs/`

6. código existente

Em caso de conflito, não invente uma nova arquitetura silenciosamente.

A implementação deve respeitar especialmente:

- Ports & Adapters;

- separação entre domínio e infraestrutura;

- imutabilidade de eventos;

- `occurred_at` diferente de `recorded_at`;

- `event_id`;

- correlação e causalidade;

- idempotência;

- Event Store como autoridade sobre persistência;

- ausência de acoplamento do domínio a banco de dados, filesystem ou fornecedor específico;

- ausência de acoplamento a LLM;

- ausência de acoplamento a MCP;

- ausência de implementação prematura de Context, Memory, Agent Runtime, Skills ou Policy.

Consulte os documentos canônicos antes de decidir qualquer detalhe de implementação.

---

# 3. Escopo da Fase

A Fase 1 deve implementar o Event System completo definido pelo `ROADMAP.md`.

O resultado deve contemplar, conforme exigido pelo roadmap e pelos contratos:

- representação de eventos;

- identidade de eventos;

- timestamps;

- origem do evento;

- payload;

- metadados necessários;

- correlação;

- causalidade;

- versionamento quando previsto pelos contratos;

- validação;

- imutabilidade;

- Event Store;

- leitura/recuperação de eventos;

- mecanismo de consumo/distribuição de eventos, quando previsto;

- idempotência;

- interfaces/ports;

- adapters concretos necessários para a primeira implementação;

- testes unitários;

- testes de integração apropriados;

- documentação de implementação necessária.

Não implemente componentes que pertencem às fases posteriores apenas para "preparar" o sistema.

---

# 4. Limites explícitos

Esta fase NÃO deve implementar:

- Context System;

- Context Snapshot;

- Memory System;

- Memory retrieval;

- Agent Runtime;

- LLM Provider;

- Embedding Provider;

- Policy Engine;

- Skills;

- Tool Router;

- MCP Server;

- MCP Tools;

- STT;

- TTS;

- wake word;

- proatividade;

- interface de voz;

- interface gráfica;

- banco de dados de produção;

- autenticação de usuário;

- deployment;

- Docker, salvo se o `ROADMAP.md` explicitamente determinar isso para esta fase.

Se alguma dessas funcionalidades aparecer como dependência futura na documentação, trate-a apenas como contrato/fonte de integração futura.

Não implemente placeholders complexos, mocks arquiteturais ou abstrações vazias apenas para simular componentes futuros.

---

# 5. Princípio central

O Event System deve ser uma infraestrutura genérica.

Um evento representa algo que aconteceu.

Ele não representa:

- uma intenção do agente;

- uma decisão do agente;

- uma Skill;

- uma chamada de ferramenta;

- uma resposta do LLM.

Esses conceitos podem futuramente gerar eventos, mas não fazem parte do núcleo semântico desta fase.

---

# 6. Event Envelope

A implementação deve refletir o contrato definido na Foundation.

Um evento deve possuir uma identidade própria e metadados suficientes para:

- identificar unicamente o evento;

- determinar quando o fato ocorreu;

- determinar quando o evento foi registrado;

- identificar sua origem;

- identificar seu tipo;

- transportar seu conteúdo;

- relacioná-lo a outros eventos;

- rastrear causalidade;

- permitir deduplicação.

Os nomes e tipos exatos devem ser derivados dos contratos existentes e do `ROADMAP.md`.

Não crie campos apenas porque parecem úteis.

Cada campo deve ter uma justificativa arquitetural.

---

# 7. `occurred_at` e `recorded_at`

Preservar obrigatoriamente a distinção estabelecida no ADR-0004.

`occurred_at`:

- representa quando o acontecimento ocorreu no mundo ou no sistema de origem.

`recorded_at`:

- é atribuído pelo Event Store no momento do registro;

- representa quando o sistema registrou o evento.

Não tratar esses timestamps como equivalentes.

Não exigir monotonicidade global de relógio, conforme decisão já estabelecida na Foundation.

---

# 8. Imutabilidade

Eventos registrados são fatos históricos.

Depois que um evento for registrado, ele não deve ser alterado.

Uma correção de informação deve ser representada conforme os contratos por um novo evento, e não por mutação do evento original.

Essa propriedade deve existir tanto no modelo de domínio quanto na persistência.

Não confiar apenas em uma convenção informal.

---

# 9. Identidade e idempotência

Cada evento deve possuir um identificador único.

O sistema deve permitir detectar uma tentativa de registrar/consumir novamente o mesmo evento quando isso fizer parte do contrato.

A implementação de idempotência deve ser real, não apenas documentada.

Não assumir que todos os sistemas externos são exatamente-once.

Projetar o sistema considerando que duplicatas podem ocorrer.

---

# 10. Correlação e causalidade

Preservar a distinção entre:

- identificação de uma cadeia/contexto de eventos relacionados;

- identificação do evento que causou diretamente outro evento.

A implementação deve permitir reconstruir relações causais quando essas informações estiverem disponíveis.

Não transformar `correlation_id` e `causation_id` em sinônimos.

---

# 11. Event Store

O Event Store deve ser definido por uma interface/port no lugar apropriado da arquitetura.

O domínio não deve conhecer:

- SQL;

- SQLite;

- PostgreSQL;

- filesystem;

- ORM;

- driver específico.

A implementação concreta deve ficar atrás da fronteira arquitetural correta.

### Persistência inicial

A tecnologia concreta de persistência deve ser determinada pelo `ROADMAP.md` e pelos contratos existentes.

Se houver uma escolha ainda aberta, escolher a solução mais simples que:

- satisfaça os requisitos;

- seja adequada a um projeto pessoal;

- tenha baixa complexidade operacional;

- seja facilmente substituível;

- não comprometa a arquitetura futura.

Não introduzir infraestrutura pesada sem necessidade.

---

# 12. Consulta de eventos

O Event Store deve possuir apenas as operações realmente necessárias para o Event System.

Não construir uma API genérica de consulta "para o futuro".

As operações devem ser orientadas pelos casos de uso definidos na fase.

Questões como:

- paginação avançada;

- busca textual;

- analytics;

- full-text search;

- índices prematuros;

- consultas para Memory;

- consultas para Context;

não devem ser implementadas sem requisito explícito nesta fase.

---

# 13. Event Consumption

Se o roadmap exigir um Event Bus ou mecanismo equivalente nesta fase, ele deve ser separado conceitualmente do Event Store.

Persistência e distribuição são responsabilidades diferentes.

O Event Store responde à pergunta:

> "O que foi registrado?"

O mecanismo de consumo/distribuição responde à pergunta:

> "Quem precisa receber/processar este evento?"

Não misturar essas responsabilidades apenas para simplificar a implementação.

Se o roadmap não exigir um mecanismo de distribuição nesta fase, não criá-lo especulativamente.

---

# 14. Ports & Adapters

A implementação deve seguir o ADR-0001.

Dependências devem apontar para dentro.

Componentes externos devem depender de abstrações apropriadas.

O domínio não pode importar diretamente infraestrutura.

Evitar uma estrutura de diretórios artificialmente profunda se ela não for necessária.

A estrutura física deve ser criada conforme o plano aprovado e o estágio real da arquitetura.

---

# 15. Tipagem

Usar tipagem estática forte compatível com:

- Python 3.13;

- mypy strict;

- Ruff configurado no projeto.

Preferir modelos explícitos e tipos precisos.

Evitar:

- `Any` desnecessário;

- dicionários não tipados para representar conceitos de domínio;

- strings mágicas;

- APIs ambíguas.

Quando um conceito possui estrutura própria, representá-lo explicitamente.

---

# 16. Serialização

A representação persistida de um evento deve ser estável e suficientemente explícita para permitir sua recuperação posterior.

Separar:

- modelo de domínio;

- representação persistida;

- transporte, se existir.

Não acoplar o modelo de domínio a uma biblioteca de serialização sem necessidade.

Se uma decisão de serialização tiver impacto arquitetural relevante, ela deve ser tratada conforme o processo de ADR já definido.

---

# 17. Versionamento

Se o contrato de eventos exigir versionamento, a versão pertence ao contrato do evento e deve ser tratada explicitamente.

Não implementar migrações complexas nesta fase sem necessidade.

Não usar "versionamento" como desculpa para permitir alterações arbitrárias em eventos já registrados.

Eventos existentes permanecem interpretáveis conforme suas versões.

---

# 18. Erros

Erros devem ser explícitos e previsíveis.

Distinguir, quando relevante:

- evento inválido;

- evento duplicado;

- falha de persistência;

- falha de recuperação;

- falha de consumo;

- erro de infraestrutura.

Não esconder falhas com `except Exception` genérico.

Não retornar valores ambíguos como `None` para representar qualquer tipo de erro.

---

# 19. Observabilidade

Utilizar a infraestrutura de logging existente.

Registrar informações úteis para diagnosticar:

- registro de evento;

- falhas de persistência;

- duplicatas;

- consumo;

- erros de infraestrutura.

Não adicionar uma plataforma de observabilidade externa nesta fase.

Não registrar payloads sensíveis indiscriminadamente.

---

# 20. Segurança e dados

O Event System deve ser projetado assumindo que eventos podem futuramente conter dados pessoais ou sensíveis.

Não:

- imprimir payload completo em logs indiscriminadamente;

- versionar secrets;

- armazenar credenciais em eventos;

- introduzir mecanismos de autorização pertencentes ao Policy Engine.

A política de autorização continua sendo responsabilidade futura do Policy Engine.

---

# 21. Testes

Os testes devem validar comportamento real.

Cobrir no mínimo os requisitos comportamentais relevantes definidos pelo roadmap, incluindo:

- criação/validação de eventos;

- imutabilidade;

- timestamps;

- identidade;

- correlação;

- causalidade;

- persistência;

- recuperação;

- idempotência;

- erros;

- comportamento dos adapters;

- isolamento entre domínio e infraestrutura;

- integração dos componentes.

Não criar testes artificiais apenas para aumentar cobertura.

Testar invariantes arquiteturais quando houver algo concreto para verificar.

---

# 22. Testes de integração

Testes de integração devem utilizar a implementação concreta de persistência escolhida para esta fase.

Eles devem demonstrar que:

1. um evento válido pode ser registrado;

2. o evento pode ser recuperado;

3. os dados permanecem consistentes;

4. duplicatas são tratadas conforme o contrato;

5. falhas são expostas adequadamente.

Não depender de serviços externos para os testes da Fase 1, salvo exigência explícita do roadmap.

---

# 23. Documentação

A documentação deve ser atualizada junto da implementação quando necessário.

Não duplicar:

- contratos;

- ADRs;

- decisões já documentadas na Foundation.

A documentação de implementação deve explicar o que realmente existe no código.

Se uma decisão arquitetural nova surgir, seguir o processo de ADR em vez de esconder a decisão em documentação comum.

---

# 24. Compatibilidade futura

O Event System será utilizado por:

- Context;

- Memory;

- Agent Runtime;

- Skills;

- observabilidade;

- futuras integrações digitais e físicas.

Portanto, sua API deve ser estável e genérica.

Mas não construir APIs para funcionalidades futuras que ainda não possuem requisitos.

A regra é:

> projetar para extensão, não implementar o futuro antecipadamente.

---

# 25. Qualidade de código

Ao final da fase, devem passar:

```
uv sync --lockeduv run ruff format --check .uv run ruff check .uv run mypyuv run pytest
```

E todos os comandos relevantes da aplicação devem continuar funcionando.

A CI existente deve permanecer verde.

---

# 26. Git

A Fase 1 é uma unidade de desenvolvimento.

Claude deve poder criar commits intermediários quando forem úteis para manter o histórico coerente, mas não deve fazer push.

Os commits devem:

- representar mudanças coerentes;

- possuir mensagens claras;

- não conter arquivos temporários;

- não conter secrets;

- não misturar alterações não relacionadas.

Ao final da fase, o working tree deve estar limpo.

---

# 27. Autonomia

Esta fase será executada como uma única unidade.

O processo será:

1. Claude lê o repositório;

2. Claude lê este documento;

3. Claude lê o `ROADMAP.md` e a documentação canônica;

4. Claude entra em Plan Mode;

5. Claude produz um plano completo da Fase 1;

6. o plano é revisado externamente;

7. após aprovação, Claude executa a fase inteira;

8. Claude testa e revisa seu próprio trabalho;

9. Claude cria os commits necessários;

10. Claude para antes do push.

Durante a execução, Claude deve tomar autonomamente decisões pequenas e reversíveis.

Deve parar somente diante de:

- conflito arquitetural real;

- mudança de contrato;

- decisão difícil de reverter não prevista no plano aprovado;

- requisito contraditório;

- problema que possa comprometer dados existentes;

- bloqueio técnico que não possa ser resolvido razoavelmente dentro do escopo.

Não parar para perguntar sobre:

- nomes de variáveis;

- nomes de arquivos;

- pequenos detalhes de implementação;

- organização interna;

- escolhas triviais de teste;

- pequenas correções de documentação;

- decisões reversíveis e de baixo risco.

---

# 28. Regra de interpretação

O `ROADMAP.md` continua sendo a fonte de verdade sobre o escopo exato da Fase 1.

Este documento complementa o roadmap.

Se este documento e o roadmap entrarem em conflito:

1. identifique o conflito;

2. não invente uma solução silenciosamente;

3. siga o roadmap;

4. somente interrompa se o conflito impedir uma implementação segura.

Para decisões arquiteturais, os contratos e ADRs aceitos continuam sendo normativos.

---

# 29. Critérios de conclusão

A Fase 1 somente estará concluída quando:

- todos os itens obrigatórios do `ROADMAP.md` estiverem implementados;

- o Event System estiver funcional;

- os contratos relevantes estiverem refletidos no código;

- os testes cobrirem o comportamento essencial;

- a persistência funcionar;

- idempotência funcionar conforme especificado;

- os limites arquiteturais forem respeitados;

- documentação necessária estiver atualizada;

- CI continuar verde;

- Ruff estiver limpo;

- mypy estiver limpo;

- pytest estiver verde;

- não existirem secrets versionados;

- não houver escopo de fases posteriores implementado sem necessidade;

- commits estiverem criados;

- working tree estiver limpo;

- nenhum push tiver sido realizado.

O resultado final deve ser uma base de eventos que possa ser utilizada pela Fase 2 sem exigir uma reconstrução arquitetural do Event System.
