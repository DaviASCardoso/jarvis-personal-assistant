# 0022. STT e TTS em nuvem por REST da stdlib, com ports separados por papel

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A Fase 6 precisa transcrever voz (Groq) e sintetizar fala (Google Cloud TTS).
Duas perguntas de contrato aparecem juntas e são independentes:

1. **como falar** com os dois serviços — SDK do vendor ou HTTP da stdlib;
2. **quantos ports** existem — um "provider de fala" ou dois papéis distintos.

O precedente da primeira pergunta está no
[ADR-0011](0011-gemini-rest-llm-adapter.md) (Gemini por `urllib`) e no
[ADR-0015](0015-stdlib-stdio-mcp-client.md) (cliente MCP próprio). O da segunda
está no [ADR-0002](0002-llm-provider-abstraction.md), que recusou juntar
`LLMProvider` e `EmbeddingProvider` num port só.

## Decisão

**Dois ports distintos**, `SpeechToText` e `TextToSpeech`, cada um com uma
operação. Reconhecer e sintetizar são papéis com ciclos de troca independentes:
trocar a voz do Jarvis não pode arriscar a qualidade do reconhecimento, e
vice-versa.

**Dois adapters por REST da biblioteca padrão**, ambos com `opener` injetável:

| | Groq | Google Cloud TTS |
|---|---|---|
| endpoint | `POST /openai/v1/audio/transcriptions` | `POST /v1/text:synthesize` |
| credencial | `Authorization: Bearer` | `x-goog-api-key` |
| corpo | `multipart/form-data` montado à mão | JSON |
| resposta | `{"text": ...}` | `{"audioContent": <base64>}` |

Quatro detalhes que não são óbvios e valem registro:

1. **`LINEAR16`, não MP3.** MP3 economizaria banda que ninguém paga num loopback
   local e custaria um decoder — que custaria uma dependência. `LINEAR16` volta
   embrulhado em RIFF, e o módulo `wave` da stdlib resolve.
2. **O formato de reprodução vem do arquivo, não do que pedimos.** A síntese
   volta em 24 kHz e a captura roda em 16 kHz; o sink abre o stream na taxa do
   clip. Reamostrar seria DSP sem necessidade.
3. **Credencial sempre em header.** Uma URL com segredo vaza em log de exceção,
   proxy e histórico de shell — e `HTTPError` imprime a URL por padrão.
4. **Nenhum ramo de erro repete o corpo da resposta.** Ele ecoa a transcrição
   (fala do usuário) ou o texto enviado (resposta do agente sobre o contexto
   dele).

Erros são traduzidos para a taxonomia do Core (`Stt*`/`Tts*`), e a política de
retry é local ao pacote — duas tentativas, respeitando `Retry-After`.

## Alternativas consideradas

- **SDKs oficiais (`groq`, `google-cloud-texttospeech`)**: trariam `httpx`,
  `grpcio`, `protobuf` e `google-auth` para dois POSTs, e enfraqueceriam o teste
  que afirma "nenhum SDK de vendor entra aqui" — que passaria a significar
  "nenhum **além destes**". Descartada pelo mesmo raciocínio do ADR-0011.
- **Um único port `SpeechProvider` com `transcribe` e `synthesize`**: junta dois
  motivos de troca diferentes numa interface só. É exatamente o erro que o
  ADR-0002 recusou para LLM/embedding.
- **Reusar a `LLMRetryPolicy` do Agent Runtime**: daria a `jarvis.voice` uma
  aresta de import para `jarvis.agent`, que é a fronteira que a fase inteira
  existe para criar. Quinze linhas duplicadas contra uma dependência — o mesmo
  cálculo que `skills/skill.py` já fez com `_NAME_PATTERN`.
- **Whisper local** (mencionado como alternativa na especificação da fase):
  proibido pela restrição "nenhuma IA local", e incompatível com o ADR-0020.

## Consequências

- Zero dependência nova para falar com os dois serviços.
- Os dois adapters são testáveis inteiros sem rede: corpo da requisição, parsing
  e mapeamento de erro, todos verificáveis com um `opener` falso.
- Trocar de provider de STT ou de TTS é um adapter novo mais um valor de
  configuração; `VoiceLoop`, wake word, sessão e painel não mudam.
- **Custo declarado:** a fala do usuário vai para a Groq e o texto da resposta
  vai para o Google. É a mesma contrapartida que o ADR-0011 já havia aceitado
  para o prompt, agora com áudio, e está documentada onde o usuário a vê.
- **Não resolve:** streaming (transcrição/síntese incremental), diarização e
  múltiplos idiomas simultâneos. O gatilho para streaming é latência percebida
  acima de ~2,5 s por turno de forma consistente.
