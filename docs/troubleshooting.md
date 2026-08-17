# Troubleshooting

> Consolida problemas de setup conhecidos entre todas as fases, a partir das
> mensagens de erro que já existem no código — nada aqui é um mecanismo
> novo, só o mesmo texto reunido num lugar navegável. Criado na Fase 8
> (subfase 8.9).

---

## Credencial ausente

Cada credencial é lida **uma única vez**, no composition root
(`cli.py`), e falha de forma explícita quando o comando que precisa dela
roda sem ela configurada:

| Variável | Usada por | Erro |
|---|---|---|
| `JARVIS_GEMINI_API_KEY` | `jarvis agent ask/react` | `JARVIS_GEMINI_API_KEY não configurada; veja .env.example` |
| `JARVIS_GROQ_API_KEY` | `jarvis voice transcribe/listen` | `JARVIS_GROQ_API_KEY não configurada; veja .env.example` |
| `JARVIS_GOOGLE_TTS_API_KEY` | `jarvis voice say/listen` | `JARVIS_GOOGLE_TTS_API_KEY não configurada; veja .env.example` |

**Correção:** copie `.env.example` para `.env` e preencha a variável que
falta. O resto do sistema (eventos, contexto, memória, Skills locais)
continua funcionando sem nenhuma das três — nenhuma credencial é
pré-requisito de arranque.

---

## Extra de voz não instalado

`jarvis voice devices/say/transcribe/listen` e `jarvis run` sem
`--no-voice` exigem o extra `voice` (`sounddevice` + o driver de áudio do
sistema operacional). Sem ele:

```text
áudio indisponível: instale o extra com `uv sync --extra voice`
```

**Correção:** `uv sync --extra voice`. Ver
[ADR-0020](adr/0020-audio-io-ports-and-optional-backend.md) para por que é
extra opcional e não dependência normal (ao contrário de `psutil`, ver
[ADR-0030](adr/0030-psutil-as-a-normal-dependency.md) — a diferença é
"exige hardware real" vs. "roda em qualquer ambiente, incluindo CI
headless").

---

## `psutil` sem permissão em ambiente restrito

Ao contrário das credenciais e do extra de voz, isto **não produz um erro
visível**. Os três Computer Context Providers (Fase 8.1) tratam qualquer
falha individual de leitura — inclusive permissão negada — como ausência
daquele campo, nunca como exceção que interrompe o resto do contexto (ver
[`computer.md` §2](computer.md#2-computer-context-81)). Em contêiner sem
`/proc` montado, sandbox restrito, ou usuário sem privilégio para consultar
outros processos, é esperado que `cpu_percent`/`memory_percent`/
`relevant_process_count` fiquem simplesmente ausentes de `jarvis context
show` — o resto do Jarvis continua funcionando normalmente.

**Se isso for inesperado** (o ambiente deveria ter a permissão e não tem):
confira se o processo tem acesso a `/proc` (Linux) ou se está rodando numa
sessão com privilégio suficiente para enumerar processos (Windows/macOS).

---

## Painel não abre no navegador

`jarvis panel`/`jarvis run` com `JARVIS_PANEL_OPEN_BROWSER=true` (o
default) tentam abrir o navegador padrão automaticamente; a falha é
**silenciosa de propósito** (navegador é conveniência, não pré-requisito —
ver `open_browser()` em `interface/adapters/http_panel.py`).

**Correção:** o comando sempre imprime a URL antes de tentar abrir o
navegador —

```text
painel     http://127.0.0.1:8765
```

— copie e cole manualmente, ou rode com `JARVIS_PANEL_OPEN_BROWSER=false`
para nunca tentar abrir automaticamente.

---

## Nenhum destes resolveu?

Confira `jarvis info` — mostra a política efetiva, os caminhos de banco em
uso e o estado de proatividade/notificação sem precisar adivinhar a partir
de variáveis de ambiente espalhadas. Credenciais nunca aparecem ali, por
desenho (`SecretStr`, nunca impressa) — o sinal de que uma está ausente é
sempre o erro explícito do comando que a exige, listado acima.
