# 0020. Captura e reprodução de áudio como ports, com backend em extra opcional

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A Fase 6 precisa abrir um microfone e um alto-falante. É a primeira necessidade
do projeto que a biblioteca padrão do Python **não atende de forma alguma** — o
que a distingue de HTTP, onde `urllib` já resolvia e o
[ADR-0011](0011-gemini-rest-llm-adapter.md) pôde recusar `requests`.

Três restrições pesam:

1. o repositório tem **duas** dependências de runtime (`pydantic`,
   `pydantic-settings`), e a regra de `CLAUDE.md §3` proíbe dependência nova sem
   necessidade concreta;
2. o CI roda `ubuntu-latest` headless, e `uv run pytest` precisa continuar
   passando **sem rede, sem credencial e sem placa de som**;
3. o projeto é desenvolvido no Windows e testado no Linux, então qualquer
   solução precisa funcionar nos dois.

## Decisão

1. `AudioSource` e `AudioSink` são **ports** no Core de `jarvis/voice/`. O
   `VoiceLoop` nunca sabe de onde o som vem nem para onde vai.
2. O adapter concreto usa **`sounddevice`** (PortAudio), e ele vive num **extra
   opcional**:

   ```toml
   [project.optional-dependencies]
   voice = ["sounddevice>=0.5"]
   ```

   `uv sync --locked` não instala nada novo; `uv sync --extra voice` habilita a
   voz.
3. O import é **tardio**, dentro de `build_audio_io()` no composition root, e o
   `ImportError` vira `AudioDeviceError` com a instrução de instalação. Ninguém
   descobre a falta do extra por traceback.
4. Um override de mypy (`ignore_missing_imports` para `sounddevice.*`) mantém
   `uv run mypy` verde **com e sem** o extra instalado.
5. Streams **raw** (`RawInputStream`/`RawOutputStream`) com `queue`, nunca
   arrays: assim `numpy` fica fora da árvore, e o timeout de leitura sai de graça
   de `Queue.get(timeout=...)`.

## Alternativas consideradas

- **`subprocess` chamando `ffmpeg`**: zero dependência Python, e foi a candidata
  mais forte pelo precedente do [ADR-0015](0015-stdlib-stdio-mcp-client.md).
  Descartada porque as flags de captura mudam por sistema operacional (`dshow` no
  Windows, `avfoundation` no macOS, `alsa`/`pulse` no Linux): traduzir isso
  colocaria **mais** acoplamento de plataforma dentro do nosso código, não menos.
  PortAudio já abstrai o host API — é exatamente o trabalho que não queremos
  fazer à mão. Some-se a isso um binário externo que o usuário precisaria
  instalar de qualquer forma.
- **`ctypes` sobre `winmm`/ALSA**: prende o projeto a um sistema operacional e
  quebra o CI Linux. Descartada sem hesitação.
- **`sounddevice` como dependência obrigatória**: simplificaria o wiring e
  quebraria o invariante que as cinco fases anteriores preservaram — `uv sync
  --locked` + `uv run pytest` sem nada além do essencial.
- **`PyAudio`**: exige compilar PortAudio em várias plataformas; `sounddevice`
  traz a biblioteca na wheel.

## Consequências

- A árvore ganha `cffi` e `pycparser` **apenas** para quem instala o extra.
- Todo o resto do Jarvis continua funcionando sem áudio: `agent ask`, `action
  run`, `panel serve` e a suíte inteira não sabem que este ADR existe.
- Trocar o backend de áudio é um adapter novo (`ffmpeg`, WASAPI direto,
  `PyAudio`) e uma linha de wiring — o loop nunca soube qual era.
- **Custo aceito:** o adapter de áudio não tem teste automatizado. Não há como
  testar um microfone sem microfone, e um duplo de PortAudio testaria o duplo. A
  verificação é manual (`jarvis voice devices`, `jarvis voice say`) e está na
  Definition of Done da fase.
- **Gatilho para reconsiderar:** um sistema operacional onde o PortAudio
  empacotado não funcione, ou necessidade de cancelamento de eco acústico — aí o
  problema deixa de ser "abrir um dispositivo" e passa a ser DSP, o que muda a
  natureza da escolha.
