# 0001. Ports & Adapters como regra de dependência

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

O Jarvis vai crescer por doze fases, cada uma introduzindo um componente
novo (Event System, Context Engine, Memory, Agent Runtime, Skills, MCP,
Voice...). Sem uma regra de dependência explícita desde o início, é fácil
que cada fase importe diretamente o que for mais conveniente naquele
momento — um Skill chamando o SDK da OpenAI direto, um componente de Memory
importando `psycopg2` direto — e o projeto vira gradualmente um monólito
acoplado, que é exatamente o resultado que a subfase 0.3 existe para evitar.

Um esboço de referência foi proposto como ponto de partida:

```text
Domain
  ↑
Application
  ↑
Infrastructure
  ↑
Interfaces
```

Lido literalmente, isso diz que `Interfaces` depende de `Infrastructure`,
que depende de `Application`, que depende de `Domain`. Isso permite (e até
sugere) que uma CLI ou um daemon de voz importem um adapter de banco ou de
LLM diretamente, porque "infraestrutura é a camada logo abaixo" — exatamente
o tipo de acoplamento (`Skill → OpenAI`, `Event → PostgreSQL`) que o projeto
quer impedir.

## Decisão

Adotar **Ports & Adapters (arquitetura hexagonal)**, com duas zonas
concêntricas em vez de uma pilha linear de quatro camadas:

- **Core** (Domain + Application): entidades, value objects, ports
  (interfaces que a infraestrutura deve implementar), lógica pura sem I/O, e
  serviços de orquestração que dependem apenas de ports. Zero dependência de
  qualquer tecnologia ou vendor concreto.
- **Infrastructure**: adapters que implementam os ports do Core (bancos, LLM
  providers, MCP client, STT/TTS, canais de notificação). Depende do Core
  (para conhecer a assinatura dos ports) — nunca o contrário.
- **Interfaces**: pontos de entrada que acionam casos de uso do Core (CLI,
  daemon de voz, futura API). Dependem do Core — nunca de Infrastructure
  diretamente.
- **Composition Root**: único módulo autorizado a conhecer Core,
  Infrastructure e Interfaces simultaneamente, responsável por instanciar
  adapters concretos e injetá-los nos serviços do Core.

Regra de dependência: tudo aponta para dentro, para o Core. Infrastructure e
Interfaces são pares que dependem do Core de formas diferentes; elas não
dependem uma da outra, e só se conectam via Composition Root.

Ver o detalhamento operacional desta regra em
[`architecture-contracts.md §2`](../architecture-contracts.md#2-regra-de-dependência-ports--adapters).

## Alternativas consideradas

- **Pilha linear literal do esboço original** (Domain→Application→
  Infrastructure→Interfaces): descartada porque implica que Interfaces
  depende de Infrastructure, permitindo o próprio acoplamento que o projeto
  quer evitar.
- **Clean Architecture com quatro pastas top-level separadas** desde já
  (`domain/`, `application/`, `infrastructure/`, `interfaces/` como pacotes
  Python distintos, já na Fase 1): descartada por ora — o valor está na
  regra de dependência, não na estrutura de pastas. Criar a separação física
  completa antes de haver componentes reais o suficiente para justificá-la
  seria abstração especulativa. A distinção Domain/Application permanece
  conceitual até que o volume de código peça a separação física.
- **Nenhuma regra explícita, revisão de código caso a caso**: descartada —
  não escala em um projeto de 16 semanas com sessões de desenvolvimento
  distintas que não compartilham memória entre si; a regra precisa estar
  escrita para ser verificável.

## Consequências

- Fica mais fácil trocar qualquer peça de infraestrutura (banco, LLM
  provider, canal de notificação) sem tocar em Core.
- Fica mais fácil testar Core isoladamente, com adapters fake/in-memory
  implementando os mesmos ports.
- Fica mais difícil (de propósito) para um componente "atalhar" e chamar
  infraestrutura diretamente — exige passar pela injeção via Composition
  Root.
- Não resolve, por si só, a decisão de *quais* ports existem em cada
  componente — isso é definido componente a componente em
  `architecture-contracts.md §3` e será refinado conforme cada fase é
  implementada.
