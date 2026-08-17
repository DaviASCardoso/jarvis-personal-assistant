# 0030. `psutil` como dependência normal, não extra opcional

**Status:** Accepted
**Data:** 2026-08-17

## Contexto

A Fase 8.1 introduz o Computer Context: três novos `ContextProvider`
(`WindowActivityProvider`, `ResourceUsageProvider`, `ProcessActivityProvider`)
que observam aplicação/janela em primeiro plano, CPU, RAM, GPU, rede,
ociosidade e processos relevantes. Isso exige uma forma multiplataforma de
consultar CPU/RAM/processos/interfaces de rede — nada na stdlib cobre isso
sem código próprio por sistema operacional.

O projeto já tem precedente para dependência de acesso a hardware:
`sounddevice` (Fase 6, voz) é uma dependência **extra opcional**
(`[project.optional-dependencies].voice`), porque exige um dispositivo de
áudio real e um driver — ausente, `uv run pytest` e o resto do sistema
continuam funcionando sem ela, e só os comandos de voz falham de forma
explícita.

## Decisão

`psutil` entra em `[project].dependencies`, não em um extra opcional.

O critério que separa os dois casos: `sounddevice` falha sem hardware físico
presente (um microfone/alto-falante); `psutil` não — ele lê estruturas do
sistema operacional (contadores de CPU, tabela de processos, interfaces de
rede) que existem em qualquer ambiente, incluindo CI headless e contêineres,
sem exigir driver ou dispositivo algum. Não há cenário de teste ou execução
normal do Jarvis em que `psutil` genuinamente não funcione — ao contrário de
voz, onde "sem microfone" é um estado real e esperado em CI.

Tratá-lo como extra opcional replicaria o padrão de voz sem a justificativa
que o originou, e obrigaria todo o resto do sistema (Context Engine,
composition root) a lidar com sua ausência como se fosse um caso real —
complexidade sem necessidade concreta (regra 11 do `ROADMAP.md`).

## Alternativas consideradas

- **Extra opcional (`[project.optional-dependencies].computer`)**: descartada
  pelo motivo acima — não existe ambiente onde `psutil` falhe por ausência de
  hardware, então não há proteção real a ganhar, só uma superfície de
  configuração a mais.
- **Implementação própria por sistema operacional (sem `psutil`)**: descartada
  — reimplementaria, com mais código e mais superfície de bug, o que uma
  biblioteca madura e amplamente usada já resolve; não há necessidade
  concreta que justifique o custo (mesma regra 11).

## Consequências

- `psutil` some da lista de "dependências que podem estar ausentes" que o
  composition root precisa considerar — os três novos providers assumem sua
  presença, como assumem a de qualquer outra dependência de
  `[project].dependencies`.
- `psutil` não é `py.typed`; `[[tool.mypy.overrides]]` com
  `ignore_missing_imports = true` para `psutil.*` foi adicionado ao
  `pyproject.toml`, mesmo padrão já usado para `sounddevice.*`. Adicionar
  `types-psutil` como dependência de dev foi considerado e descartado: o uso
  aqui é só leitura (CPU/RAM/processos/rede), sem superfície grande o
  suficiente para justificar mais uma dependência de tipos.
- Cada leitura de métrica dentro dos providers continua isolada e tolerante a
  falha individual (uma exceção de `psutil.Error` em uma métrica não derruba
  as outras) — essa robustez é do design dos providers, não uma consequência
  desta decisão sobre onde a dependência é declarada.
