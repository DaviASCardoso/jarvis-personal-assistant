# 0006. Configuração vs. Secrets vs. Preferências vs. Estado

**Status:** Accepted
**Data:** 2026-08-08

## Contexto

A 0.1/0.2 já estabeleceram um mecanismo de configuração (`Settings` via
`pydantic-settings`, prefixo `JARVIS_`, com fallback para `.env`). Conforme o
sistema cresce, surgem outras categorias de dado que "parecem configuração"
mas têm ciclo de vida muito diferente: chaves de API (não deveriam ser
tratadas como qualquer outro valor de config — nunca podem vazar em log),
preferências que o próprio agente aprende sobre o usuário (ex. "não
notificar depois das 22h" — mutáveis em runtime, com proveniência e
confidence, não estáticas), e estado operacional específico de um
componente (ex. último event offset processado). Tratar essas quatro coisas
como uma única categoria "configuração" leva a um `Settings` que mistura
responsabilidades incompatíveis: um arquivo estático de deploy não é o lugar
certo para um valor que o próprio agente muda sozinho em runtime a partir do
que aprendeu sobre o usuário.

## Decisão

Quatro categorias, sem mistura:

- **Configuração de sistema**: técnica, deploy-time, estática. Continua
  usando `Settings`/`pydantic-settings`, o mecanismo já existente.
- **Secrets**: mesmo mecanismo de leitura (env/`.env`), mas com regra
  adicional — nunca aparecem em log, evento, payload de memória ou audit log
  em texto claro.
- **Preferências do usuário**: modeladas como **Memory** (tipo preferência,
  já previsto na 3.1 do roadmap), não como `Settings` — porque têm
  proveniência, confidence, podem mudar/decair, e são escritas pelo próprio
  agente em runtime, não pelo usuário editando um arquivo de configuração.
- **Estado operacional**: específico de cada componente (ex. Event
  System guarda seu próprio cursor de leitura), não centralizado em um
  `Settings` global.

Configuração é carregada uma vez, na composition root, e injetada
explicitamente nos componentes que precisam dela — não consultada
ad hoc (`load_settings()`) de dentro de código de Core/Application conforme
esse código crescer. Chamar `load_settings()` diretamente em um entry point
(como `cli.py` faz hoje) continua correto — é exatamente o papel de um entry
point compor a configuração antes de acionar o Core.

Detalhamento em
[`architecture-contracts.md §12`](../architecture-contracts.md#12-configuration-boundary).

## Alternativas consideradas

- **Preferências do usuário como parte de `Settings`** (ex. um bloco
  `[preferences]` no `.env`): descartada — um arquivo de configuração
  estático não é um bom lugar para dados que o agente atualiza sozinho a
  partir de inferência, com grau de confiança variável; forçaria `Settings`
  a suportar escrita em runtime e versionamento de confidence, que não é o
  papel dele.
- **Um único mecanismo de config genérico para tudo (config + secrets +
  preferências + estado)**: descartada — simplicidade aparente que esconde
  quatro ciclos de vida e regras de segurança diferentes atrás de uma
  interface só; o risco concreto é secrets vazando para onde preferências
  (mais frequentemente lidas/logadas) circulam.

## Consequências

- Preferências aprendidas se beneficiam de toda a infraestrutura de Memory
  (retrieval, confidence, decay) sem precisar reinventar nada disso dentro
  de `Settings`.
- Secrets ganham uma regra clara e verificável (nunca em log/evento/memória)
  sem precisar de um cofre de secrets dedicado neste estágio do projeto.
- Fica mais fácil raciocinar sobre "o que muda quando" — configuração muda
  no deploy, preferência muda com o uso, estado muda a cada execução.
- Não exige, ainda, nenhuma mudança em `src/jarvis/config.py` — a distinção
  vale a partir de onde novas categorias de dado (preferências, estado)
  começarem a existir, nas fases correspondentes.
