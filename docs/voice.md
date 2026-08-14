# Camada de voz

> **Documentação de implementação**: descreve o que existe em
> `src/jarvis/voice/` desde a Fase 6. Contratos normativos ficam em
> [`architecture-contracts.md §3.9`](architecture-contracts.md#39-voice-interface);
> as decisões, nos [ADR-0020 a 0025](adr/).

---

## 1. O que a camada de voz é

Uma **Interface** no sentido de Ports & Adapters: um ponto de entrada que aciona
o Core sem conhecê-lo.

```text
Microfone → Wake Word → VAD → STT → ConversationalAgent → TTS → Alto-falante
```

`jarvis.voice` importa de `jarvis` **apenas `jarvis.errors`**. Nem
`jarvis.agent`. Todo o resto do sistema chega por um único port,
`ConversationalAgent`, implementado no composition root — e
`tests/test_voice_architecture.py` verifica isso módulo a módulo.

A consequência prática é que o loop inteiro da conversa é testável sem LLM, sem
banco, sem rede e sem placa de som: `tests/test_voice_loop.py` roda a máquina de
estados completa com doubles.

---

## 2. Ports

| Port | Responsabilidade |
|---|---|
| `AudioSource` | de onde vem o som; `read` nunca bloqueia além do timeout e devolve `None` no silêncio |
| `AudioSink` | para onde vai; `play` é síncrono e **cancelável** entre blocos |
| `SpeechToText` | áudio entra, texto sai; sem estado, sem decisão |
| `TextToSpeech` | texto entra, áudio sai |
| `WakeWordDetector` | recebe blocos (modelo *push*) e decide que o Jarvis foi chamado |
| `ConversationalAgent` | a única porta para o resto do Jarvis |
| `VoiceSessionRepository` | persistência das sessões |

Não são ports, por terem implementação única e nenhum substituto real:
`Segmenter`, `VoiceLoop`, `VoiceSession`. É a mesma assimetria de
`EventBus`/`EventStore` (Fase 1) e `MemoryManager`/`MemoryRepository` (Fase 3).

---

## 3. Wake word

Duas estratégias, escolhidas por `JARVIS_WAKE_STRATEGY`. Nenhuma delas usa IA
local — restrição da fase, registrada no [ADR-0021](adr/0021-wake-word-without-local-ai.md).

### `push_to_talk` (default)

Uma thread lê `stdin`; qualquer linha (Enter basta) arma o gatilho. Custo zero,
latência zero e — o que mais importa — **nenhum áudio sai do dispositivo antes de
você pedir**.

### `transcription` (opt-in)

```text
blocos → VAD (energia, determinístico) → segmento de 0,3–3,0 s
       → orçamento por minuto → STT → casamento da frase
```

Quatro controles, porque mandar tudo que se ouve para a nuvem seria inaceitável:

| controle | configuração | o que ele impede |
|---|---|---|
| gate de energia/duração | `JARVIS_VAD_*` | silêncio, tosse e clique virarem requisição |
| teto de segmento | 3 s (constante) | transcrever conversa contínua |
| orçamento | `JARVIS_STT_WAKE_BUDGET_PER_MINUTE` | uma TV ligada consumir a quota |
| suspensão na fala | automático | o Jarvis se acordar com a própria voz |

O casamento da frase é restrito: ela precisa começar no **primeiro token** do
enunciado, com distância de edição ≤ 1 e só em palavras de 4 caracteres ou mais.
`jarvis, apague o arquivo` ativa; `o jarvis do filme apaga tudo` não. Quem quiser
`ei jarvis` registra a frase inteira em `JARVIS_WAKE_PHRASES`.

Quando a wake word já ouviu o comando inteiro, ele **não é pedido de novo**: o
`remainder` da detecção vira o enunciado do turno.

---

## 4. Detecção de fala (VAD)

`voice/vad.py` é aritmética sobre PCM: RMS por bloco, contagem de silêncio,
duração mínima de fala e um anel de *pre-roll*. Zero modelo, zero I/O.

O pre-roll existe por um motivo concreto: sem ele o limiar corta a primeira
sílaba, e o que chega ao transcritor é "arvis, que horas são".

Determinismo é a propriedade que se está comprando — a mesma sequência de blocos
produz exatamente os mesmos segmentos, o que torna o comportamento testável com
PCM sintético.

---

## 5. STT e TTS

| | STT | TTS |
|---|---|---|
| provider | Groq (`whisper-large-v3-turbo`) | Google Cloud Text-to-Speech |
| transporte | `urllib` + multipart montado à mão | `urllib` + JSON |
| credencial | `Authorization: Bearer` | `x-goog-api-key` |
| formato | WAV 16 kHz mono s16le | `LINEAR16` (volta em 24 kHz) |
| retry | 2 tentativas, respeitando `Retry-After` | idem |

Sem SDK de vendor, pelo precedente do [ADR-0011](adr/0011-gemini-rest-llm-adapter.md)
e registrado no [ADR-0022](adr/0022-cloud-speech-over-stdlib-rest.md).

A taxa de reprodução vem **do arquivo**, não do que foi pedido: o sink abre o
stream na taxa do clip, o que evita reamostrar 24 kHz para 16 kHz.

Texto acima de `JARVIS_TTS_MAX_CHARS` é cortado na última fronteira de frase que
couber — cortar no caractere exato terminaria a fala no meio de uma sílaba.

---

## 6. Sessão, estados e interrupção

```text
        ┌────────────────── idle / erro de áudio ──────────────────┐
        ▼                                                          │
     IDLE ──start()──► LISTENING ──wake──► CAPTURING ──► TRANSCRIBING
                          ▲                   ▲                │
                          │                   │ fala nova      ▼
                          │             FOLLOW_UP ◄─── SPEAKING ◄─── THINKING
                          │                   │            │
                          └──── timeout ──────┘  barge-in ──┘
```

- **`FOLLOW_UP`** é a janela em que o Jarvis continua ouvindo sem wake word. Sem
  ela, uma conversa de cinco turnos exigiria cinco "Jarvis".
- **Barge-in**: durante a fala, `AudioSink.play` consulta uma função que lê o
  microfone entre blocos; dois blocos acima do limiar cancelam a reprodução, e o
  áudio já capturado vira o começo do próximo enunciado. Sem thread, sem lock.
  Pressupõe fone — sem ele, o alto-falante alimenta o microfone
  (`JARVIS_VOICE_BARGE_IN=false` desliga).
- **Silêncio é uma decisão válida**: `AgentReply.text is None` (`Decision.ignore`)
  não sintetiza nada e não cria turno do assistente.
- **Falha não fecha a sessão**: erro de transcrição, de síntese ou do agente vira
  uma frase curta e o turno seguinte continua. Só erro de áudio encerra.

Uma ação de risco proposta por voz cai em `require_confirmation` e é confirmada
falando "sim"/"não" — a resposta percorre o mesmo caminho da confirmação
digitada: publica evento e **reavalia a política do zero**
([ADR-0014](adr/0014-confirmation-state-and-event-answers.md)). Uma resposta
ambígua ("talvez") **não** confirma.

---

## 7. Persistência e retenção

`data/voice.db` — quinto banco do projeto, com duas tabelas
(`voice_sessions`, `voice_turns`), `PRAGMA user_version = 1` e WAL.

**Áudio nunca é gravado em disco. Transcrição nunca entra em evento.** Os dois
eventos que a voz produz — `voice.session_started` e `voice.session_ended` —
carregam identidade e contagem, e nada mais
([ADR-0025](adr/0025-voice-transcripts-as-operational-state.md)).

Retenção default de 7 dias, aplicada quando o processo residente sobe.
`JARVIS_VOICE_RETENTION_DAYS=0` desliga o expurgo automático.

Efeito colateral bem-vindo: os dois eventos alimentam o campo `conversation` do
Context Engine, que existia desde a Fase 2 sem fonte — então o agente passa a
saber, no prompt, que está numa conversa por voz e qual é ela.

---

## 8. O que sai do dispositivo

Honestidade explícita, porque a fase aumenta a superfície:

| dado | vai para | quando |
|---|---|---|
| áudio do enunciado | Groq | a cada enunciado capturado |
| trechos curtos do ambiente | Groq | **só** com `JARVIS_WAKE_STRATEGY=transcription` |
| transcrição + contexto + memórias | Google (Gemini) | a cada turno que consulta o modelo |
| texto da resposta | Google (Cloud TTS) | a cada resposta falada |

As três credenciais (`JARVIS_GEMINI_API_KEY`, `JARVIS_GROQ_API_KEY`,
`JARVIS_GOOGLE_TTS_API_KEY`) são `SecretStr`, lidas **só** no composition root, e
viajam em header — nunca em query string, nunca em log, nunca em evento.

---

## 9. Comandos

```bash
uv sync --extra voice            # habilita o áudio (ADR-0020)

jarvis voice devices             # lista microfones e alto-falantes
jarvis voice say "Olá."          # fala; --out grava um WAV
jarvis voice transcribe a.wav    # transcreve um arquivo
jarvis voice listen              # conversa, sem painel
jarvis voice listen --execute    # ... e submete ações ao Policy Engine
jarvis voice sessions list       # o que ficou registrado
jarvis voice sessions show <id>
jarvis voice sessions purge <id> # ou --all
jarvis run                       # voz + painel no mesmo processo
```

Sem o extra instalado, os comandos que precisam de dispositivo falham com
`áudio indisponível: instale o extra com uv sync --extra voice` — e todo o resto
do Jarvis continua funcionando.

---

## 10. Limitações conhecidas

- **Sem streaming**: o turno é enunciado-a-enunciado. A latência é a soma de
  STT + LLM + TTS.
- **Barge-in pressupõe fone**; sem ele, ajuste `JARVIS_VOICE_BARGE_IN_RMS` ou
  desligue.
- **Sem cancelamento de eco, supressão de ruído ou diarização.**
- **O adapter de áudio não tem teste automatizado** — não há como testar um
  microfone sem microfone. A verificação é manual (`jarvis voice devices`,
  `jarvis voice say`).
- **Notificação fora do painel não existe**: `notify`/`ask` continuam sem canal
  próprio até a subfase 7.3.
- **A wake word por transcrição depende da nuvem**: sem rede, ela degrada para
  "não ativou". Push-to-talk continua funcionando.
