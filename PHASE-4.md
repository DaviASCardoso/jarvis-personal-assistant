# JARVIS — Fase 4

## Agent Runtime, LLM e Interface de Voz

> Documento de especificação para desenvolvimento da Fase 4.
> 
> Este documento deve ser lido junto de `ROADMAP.md`, `CLAUDE.md`, `docs/architecture-contracts.md`, todos os ADRs e a documentação atual dos componentes. Em caso de conflito, os contratos e o ROADMAP prevalecem.

---

# 1. Objetivo da Fase

A Fase 4 transforma os componentes construídos nas fases anteriores em um **agente capaz de raciocinar sobre o estado atual do mundo e conversar com o usuário**.

O objetivo não é simplesmente "integrar uma API de LLM".

O objetivo é implementar o ciclo:

```
Evento / entrada do usuário        ↓Contexto atual        ↓Memória relevante        ↓Agent Runtime        ↓LLM Provider        ↓Decision estruturada        ↓Policy Engine        ↓ação / notificação / silêncio
```

E, no caminho de voz:

```
Áudio  ↓STT  ↓Utterance  ↓Agent Runtime  ↓LLM  ↓Resposta textual  ↓TTS  ↓Áudio
```

A Fase 4 deve fazer isso sem quebrar as fronteiras estabelecidas nas Fases 0–3.

---

# 2. Estado arquitetural esperado

Ao final da Fase 4, a arquitetura deverá se aproximar de:

```
                         ┌──────────────────────┐                         │     WORLD / USER     │                         │                      │                         │ eventos, voz, etc.   │                         └──────────┬───────────┘                                    │                                    ▼                         ┌──────────────────────┐                         │    EVENT SYSTEM      │                         └──────────┬───────────┘                                    │                                    ▼                         ┌──────────────────────┐                         │    CONTEXT ENGINE    │                         └──────────┬───────────┘                                    │                         ┌──────────┴───────────┐                         ▼                      ▼                 ┌──────────────┐       ┌──────────────┐                 │    MEMORY    │       │ CURRENT      │                 │    SYSTEM    │       │  CONTEXT     │                 └──────┬───────┘       └──────┬───────┘                        │                      │                        └──────────┬───────────┘                                   ▼                         ┌──────────────────────┐                         │    AGENT RUNTIME     │                         │                      │                         │  orchestration       │                         │  prompt/context      │                         │  LLM interaction     │                         │  decision parsing    │                         └──────────┬───────────┘                                    │                                    ▼                         ┌──────────────────────┐                         │     LLM PROVIDER     │                         │                      │                         │ vendor-agnostic port │                         └──────────┬───────────┘                                    │                                    ▼                         ┌──────────────────────┐                         │    Gemini Adapter    │                         │      (Cloud)         │                         └──────────────────────┘Decision   ↓Policy Engine   ↓Skill / Notification / Silence
```

O LLM é um componente de raciocínio, não uma autoridade de execução.

---

# 3. Princípio fundamental

## O LLM propõe. O código decide.

O modelo pode produzir algo como:

```
{  "intent": "execute_skill",  "skill": "send_notification",  "parameters": {    "message": "Sua impressão terminou."  }}
```

Isso **não significa que a ação aconteceu**.

O fluxo obrigatório é:

```
LLM ↓Decision ↓Policy Engine ↓PolicyVerdict ↓Skill ↓Tool Router ↓Tool/MCP
```

A arquitetura já estabelece explicitamente que o Agent Runtime produz `Decision` e não efeitos colaterais. fileciteturn12file8L375-L392

---

# 4. LLM Provider

O Core não pode conhecer Gemini.

O contrato deve ser conceitualmente:

```
LLMProvider    │    ├── generate(...)    ├── structured generation    ├── model metadata    └── provider errors
```

O adapter concreto será:

```
GeminiLLMProvider
```

Mas:

```
Agent Runtime      │      ▼LLMProvider      ▲      │GeminiLLMProvider
```

e não:

```
Agent Runtime      │      ▼google.generativeai / SDK Gemini
```

Isso preserva a decisão arquitetural existente de manter o `LLMProvider` vendor-agnóstico. fileciteturn11file1L76-L84

---

# 5. Primeiro provider: Gemini API

A primeira implementação concreta deverá usar:

**Google Gemini API, em nuvem.**

Não haverá modelo local nesta fase.

O objetivo é minimizar:

- consumo de hardware;

- complexidade operacional;

- RAM/VRAM necessária;

- manutenção de modelos;

- latência de desenvolvimento;

- custo financeiro.

A implementação deve ser preparada para que trocar Gemini posteriormente não exija alterar o Agent Runtime.

---

# 6. Política de custo

O projeto é pessoal.

Portanto:

> Não construir infraestrutura paga quando existir uma alternativa gratuita adequada.

A implementação deve utilizar as opções gratuitas disponíveis dos provedores, respeitando os limites e quotas vigentes.

O código deve tratar explicitamente:

- rate limit;

- quota excedida;

- timeout;

- indisponibilidade;

- erro de autenticação;

- resposta inválida;

- erro transitório.

Esses erros devem ser convertidos para a taxonomia interna do Jarvis.

Nunca deixar exceções específicas do SDK do provider vazarem para o Core.

---

# 7. Structured Output

A saída do LLM não deve ser texto arbitrário quando o Agent Runtime precisar tomar uma decisão.

O objetivo é obter uma estrutura validável.

Conceitualmente:

```
LLM response     ↓parse     ↓validate     ↓Decision
```

Uma `Decision` pode representar, por exemplo:

```
NO_ACTIONRESPONDNOTIFYEXECUTE_SKILLREQUEST_CONFIRMATION
```

O conjunto exato deverá seguir o contrato já existente e ser refinado durante a implementação somente quando necessário.

Não criar uma DSL proprietária complexa.

---

# 8. Contexto enviado ao LLM

O LLM não deve receber simplesmente:

```
"Você é Jarvis..."
```

Ele deve receber um contexto estruturado.

Conceitualmente:

```
{  "current_context": {},  "relevant_memories": [],  "recent_events": [],  "user_input": {},  "available_capabilities": [],  "constraints": {}}
```

O Agent Runtime é responsável por construir o envelope de raciocínio.

O provider recebe o request já preparado.

O provider não deve buscar:

- memória;

- contexto;

- eventos;

- ferramentas;

- configuração do Jarvis.

Essas responsabilidades pertencem ao Agent Runtime / Core.

---

# 9. Não enviar contexto indiscriminadamente

O objetivo do Jarvis é possuir contexto amplo, mas isso não significa mandar tudo ao LLM em toda chamada.

O Agent Runtime deve selecionar:

- contexto atual relevante;

- memórias relevantes;

- eventos recentes relevantes;

- entrada do usuário;

- capacidades disponíveis.

Isso evita:

- desperdício de tokens;

- latência;

- contexto poluído;

- decisões piores;

- custo desnecessário.

A memória deve ser recuperada pelo Memory System, não pelo LLM.

---

# 10. Memória

O Agent Runtime poderá consultar:

```
MemoryRepository
```

e receber memórias relevantes.

A distinção já estabelecida deve permanecer:

```
importance ≠ confidence ≠ relevance
```

`relevance` é score de retrieval, não uma propriedade permanente da memória. fileciteturn11file12L580-L588

O Agent Runtime decide quais resultados são relevantes para a chamada atual.

---

# 11. Agent Runtime

O Agent Runtime será o cérebro de orquestração.

Responsabilidades:

1. receber uma entrada;

2. obter contexto;

3. recuperar memória relevante;

4. identificar capacidades disponíveis;

5. construir o request para o LLM;

6. chamar `LLMProvider`;

7. validar a resposta;

8. transformar a resposta em `Decision`;

9. encaminhar a `Decision` ao Policy Engine;

10. retornar o resultado apropriado.

Não deve:

- executar Skill diretamente;

- acessar MCP diretamente;

- acessar banco diretamente;

- conhecer SDK do Gemini;

- decidir permissões;

- armazenar secrets;

- implementar regras de Policy.

---

# 12. Loop do Agent

O loop conceitual é:

```
INPUT  ↓BUILD CONTEXT  ↓RETRIEVE MEMORY  ↓DISCOVER CAPABILITIES  ↓BUILD PROMPT  ↓LLM  ↓PARSE  ↓VALIDATE DECISION  ↓POLICY  ↓EXECUTION / RESPONSE / SILENCE
```

A execução pode gerar novos eventos:

```
Decision ↓Policy ↓Skill ↓Tool ↓Result ↓Event ↓Context / Memory
```

Isso fecha o ciclo de aprendizagem operacional do agente.

---

# 13. Proatividade

Uma característica fundamental do Jarvis é que ele não deve responder apenas quando chamado.

Eventos podem entrar no Agent Runtime:

```
Event ↓Context update ↓Agent evaluation ↓Decision
```

O Agent pode decidir:

```
notify
```

ou:

```
no_action
```

**Silêncio é uma decisão válida.**

Não transformar todo evento em notificação.

---

# 14. Controle de ruído

A arquitetura deve evitar que eventos triviais gerem chamadas desnecessárias ao LLM.

Sempre que possível:

```
evento ↓filtros determinísticos baratos ↓só então LLM
```

Exemplos:

- evento sem relevância;

- evento duplicado;

- evento já processado;

- estado que não mudou significativamente.

Não criar um "AI importance model" separado nesta fase sem necessidade concreta.

---

# 15. Conversação

O Jarvis deve suportar uma interação como:

```
Usuário:"Jarvis, o que aconteceu enquanto eu estava fora?"        ↓Context + Memory + Events        ↓LLM        ↓Resposta
```

A conversa deve possuir contexto próprio.

Distinguir:

- estado atual do mundo;

- memória persistente;

- histórico conversacional;

- mensagem atual.

Não misturar tudo em uma única estrutura de "memory".

---

# 16. Voz

A Voice Interface deve continuar sendo uma camada de interface.

```
Audio ↓STT ↓Text ↓Agent ↓Text ↓TTS ↓Audio
```

Ela não deve conhecer:

- Skills;

- MCP;

- Policy;

- banco;

- Memory internamente.

Isso segue o contrato arquitetural da Voice Interface. fileciteturn11file2L105-L114

---

# 17. STT

O requisito do projeto é:

**STT na nuvem e gratuito.**

Prioridade de avaliação:

1. Groq Whisper ou serviço equivalente gratuito;

2. outro Whisper hospedado gratuitamente, se a opção anterior não for adequada;

3. somente considerar execução local se houver uma razão técnica concreta.

A implementação deve utilizar um `STTProvider` abstrato.

Exemplo conceitual:

```
STTProvider     ▲     │GroqWhisperSTTProvider
```

Não colocar chamadas HTTP diretamente dentro da Voice Interface.

---

# 18. TTS

O requisito do projeto é:

**Google Cloud Text-to-Speech.**

O TTS também deve ser abstraído:

```
TTSProvider     ▲     │GoogleCloudTTSProvider
```

A Voice Interface trabalha apenas com:

```
text → TTSProvider → audio
```

Não deve conhecer o SDK específico do Google.

---

# 19. Wake Word

A wake word deve ser considerada parte da Voice Interface.

Conceitualmente:

```
Microphone    ↓Wake Word Detection    ↓STT    ↓Agent
```

Não enviar áudio continuamente para a API de STT.

O detector de wake word deve funcionar como gate local sempre que isso for tecnicamente viável.

A implementação concreta da wake word deve ser escolhida pela necessidade real da fase, não por preferência antecipada por uma biblioteca.

---

# 20. Privacidade

O uso de serviços cloud implica que:

- áudio enviado ao STT sai do dispositivo;

- texto/contexto enviado ao LLM sai do dispositivo;

- texto enviado ao TTS sai do servidor.

Portanto, o Agent Runtime deve ter uma fronteira clara de dados.

Não enviar secrets ou dados internos desnecessários ao provider.

Particularmente:

```
API keystokenscredentialsinternal policy state
```

nunca devem entrar no prompt.

---

# 21. Secrets

Credenciais deverão continuar pertencendo à categoria de Secrets, separada de:

- configuração;

- preferências;

- estado.

Essa separação já está estabelecida na arquitetura. fileciteturn11file14L742-L744

Usar:

```
JARVIS_GEMINI_API_KEYJARVIS_GOOGLE_CLOUD_...JARVIS_STT_...
```

ou convenção equivalente definida durante a implementação.

Nunca:

- hardcode;

- commit;

- log;

- prompt;

- evento.

---

# 22. Observabilidade

Cada chamada relevante deve preservar:

```
correlation_idcausation_idtimestampcomponent
```

A cadeia deve poder ser reconstruída:

```
Event ↓Agent invocation ↓LLM request ↓Decision ↓Policy verdict ↓Skill ↓Tool ↓Result
```

A arquitetura já define `correlation_id` como espinha dorsal da observabilidade. fileciteturn11file12L574-L580

Nunca registrar conteúdo sensível indiscriminadamente.

---

# 23. Erros

Providers externos devem ser tratados como infraestrutura.

Por exemplo:

```
GeminiRateLimitError       ↓ProviderError(retryable=True)
```

e não:

```
google.api_core.exceptions...
```

no Core.

A taxonomia existente inclui `ProviderError`, `TimeoutError`, `PolicyDenied`, etc. fileciteturn11file14L697-L699

---

# 24. Testes

A Fase 4 precisa testar principalmente comportamento e contratos.

## Testes do LLM Provider

Testar com mocks/fakes:

- request correto;

- parsing;

- structured output;

- timeout;

- rate limit;

- resposta inválida;

- erro de autenticação;

- conversão de erros.

Não depender da API real para toda a suíte.

---

# 25. Testes do Agent Runtime

Testar:

```
input +context +memory ↓expected Decision
```

Casos essenciais:

- nenhuma ação;

- resposta simples;

- ação proposta;

- decisão inválida;

- contexto vazio;

- memória relevante;

- memória irrelevante;

- erro do LLM;

- timeout;

- provider indisponível.

---

# 26. Testes de segurança

Garantir estruturalmente:

```
Agent Runtime ──X──> Skill.execute()Agent Runtime ──X──> Tool RouterAgent Runtime ──X──> MCPAgent Runtime ──X──> Policy bypass
```

O caminho permitido é:

```
Agent ↓Decision ↓Policy ↓Skill ↓Tool Router
```

---

# 27. Testes de integração

Devem existir alguns testes reais do pipeline:

```
Event ↓Context ↓Agent ↓Fake LLM ↓Decision ↓Policy
```

e:

```
Audio/text ↓Voice Interface ↓Agent ↓Fake TTS
```

O objetivo é provar a integração entre componentes sem transformar a suíte em dependente de APIs externas.

---

# 28. Uso da API real

A API real de Gemini/STT/TTS não deve ser requisito da suíte normal.

Pode existir um smoke test separado, se realmente necessário:

```
integration / external
```

mas não deve quebrar:

```
uv run pytest
```

por falta de:

- API key;

- internet;

- quota;

- serviço externo.

---

# 29. Dependências

Não adicionar bibliotecas apenas porque "podem ser úteis".

Para cada dependência nova:

```
necessidade concreta→ alternativa stdlib/existente→ motivo da dependência→ impacto
```

A Fase 4 inevitavelmente poderá introduzir SDKs HTTP/cloud, mas eles devem ficar isolados nos adapters.

---

# 30. Arquitetura de providers

O padrão esperado é:

```
Core│├── LLMProvider├── STTProvider└── TTSProvider        ▲        │Infrastructure│├── GeminiLLMProvider├── GroqWhisperSTTProvider└── GoogleCloudTTSProvider
```

A troca de provider não deve exigir alteração do Agent Runtime.

---

# 31. Composition Root

O wiring deve acontecer na Composition Root.

Exemplo conceitual:

```
Settings   ↓GeminiLLMProvider   ↓AgentRuntime   ↓PolicyEngine   ↓...
```

O Core recebe abstrações.

A Composition Root conhece as implementações concretas.

---

# 32. Documentação

A documentação de implementação deve ser atualizada junto do código.

Não duplicar:

- contratos;

- ADRs;

- documentação arquitetural.

A documentação deve explicar principalmente:

- o que foi implementado;

- como funciona;

- quais providers foram escolhidos;

- limitações;

- configuração;

- testes;

- como trocar provider.

---

# 33. ADRs

Criar ADR apenas quando surgir uma decisão arquitetural difícil de reverter.

Possíveis exemplos:

- escolha definitiva de um protocolo específico;

- mudança da arquitetura de Agent Runtime;

- estratégia de streaming;

- decisão importante sobre cloud/provider que afete o Core.

Não criar ADR para:

- nome de classe;

- nome de método;

- pequenas decisões de implementação;

- testes;

- simples escolha de biblioteca reversível.

---

# 34. Fora de escopo

Não antecipar:

- Skills completas;

- MCP servers reais;

- integrações complexas de serviços;

- Bambu Lab;

- Gmail;

- calendário;

- automações físicas;

- deployment;

- app mobile;

- UI sofisticada;

- infraestrutura distribuída.

A Bambu Lab já foi identificada como uma integração futura possível, mas deve entrar na fase de Tools/MCP/Skills apropriada, não ser incorporada prematuramente ao Agent Runtime.

---

# 35. Critério de sucesso

A Fase 4 será considerada concluída quando o Jarvis puder:

1. receber uma entrada;

2. montar contexto;

3. consultar memória;

4. enviar uma requisição estruturada ao LLM;

5. receber e validar uma resposta;

6. produzir uma `Decision`;

7. passar a decisão pelo Policy Engine;

8. produzir resposta ou ação corretamente;

9. conversar por texto;

10. utilizar STT/TTS através de interfaces abstratas;

11. lidar com falhas dos providers;

12. manter correlação e observabilidade;

13. passar todos os gates de qualidade;

14. manter as fronteiras arquiteturais;

15. operar sem depender de modelos locais.

O resultado não precisa ser ainda o "Jarvis completo".

Ele precisa ser o **cérebro conversacional e decisório funcional sobre o qual as Skills e integrações futuras poderão ser construídas**.

---

# 36. Regra final

Não transformar a Fase 4 em uma implementação gigantesca de tudo que o Jarvis eventualmente fará.

O objetivo é construir:

```
CONTEXT   +MEMORY   +LLM   +AGENT RUNTIME   +VOICE   +POLICY HANDOFF
```

de maneira sólida.

O restante entra posteriormente.
