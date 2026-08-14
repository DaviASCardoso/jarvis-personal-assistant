# 0021. Wake word sem IA local: gate determinístico e verificação por transcrição

**Status:** Accepted
**Data:** 2026-08-14

## Contexto

A subfase 6.1 do [roadmap](../../ROADMAP.md) pede um `WakeWordDetector` com
interface própria. A especificação da fase acrescenta uma restrição que elimina
quase todo o mercado: **nenhum modelo local, nenhuma inferência local, nenhum
servidor local de IA.**

Isso descarta Porcupine, openWakeWord, Precise e qualquer detector acústico
treinado — todos são inferência rodando na máquina. Descarta também a saída
"clássica" (MFCC + DTW sobre amostras gravadas): além de ser um modelo por
enrolamento, exigiria DSP pesado em Python puro, com qualidade imprevisível e
sem forma honesta de testar.

O que sobra é verificar a frase **no texto**, o que significa mandar áudio para a
nuvem — e áudio do ambiente, não do enunciado que o usuário decidiu dizer. O
problema real deste ADR não é "como detectar", é **como controlar o custo e a
privacidade de detectar**.

## Decisão

`WakeWordDetector` é um port com modelo **push**: o loop já está lendo o
microfone e alimenta o detector com blocos. Nenhum detector abre dispositivo por
conta própria — é o que permite que o mesmo stream sirva wake word, captura e
barge-in sem disputa.

Dois adapters, para dois momentos de uso:

1. **`PushToTalkWakeWord` — o default.** Uma thread lê `stdin`; qualquer linha
   arma o gatilho. Custo zero, latência zero, determinístico, e **nenhum áudio
   sai do dispositivo antes de o usuário pedir**. É default por isso, não por
   simplicidade.
2. **`TranscriptionWakeWord` — opt-in.** Um `Segmenter` (VAD por energia,
   aritmética pura, sem modelo) fecha segmentos de fala; cada segmento vira uma
   transcrição, e o texto é comparado com a frase configurada.

Quatro controles no segundo caminho, cada um por um cenário concreto:

- **gate de energia e duração**: silêncio, tosse e clique nunca viram requisição;
- **teto de segmento** (3 s): um trecho longo é conversa, não uma chamada pelo
  nome;
- **`WakeBudget`** (12/min, janela deslizante): uma TV ligada consumiria a quota
  inteira em minutos;
- **suspensão durante a fala do Jarvis**: sem isso ele transcreve a própria voz e
  se acorda sozinho.

O casamento é restrito: a frase precisa começar no **primeiro token** do
enunciado, com distância de edição ≤ 1 e apenas em palavras de 4 caracteres ou
mais. "jarvis, apague o arquivo" ativa; "o jarvis do filme apaga tudo" não.

O detector por transcrição depende do **port** `SpeechToText`, nunca da Groq.

## Alternativas consideradas

- **Porcupine / openWakeWord**: a melhor solução técnica disponível, e proibida
  pela restrição da fase. Se a restrição for revista, entram como um terceiro
  adapter — o port existe para isso.
- **MFCC + DTW artesanal**: DSP pesado em Python puro, qualidade imprevisível, e
  ainda assim um modelo (por enrolamento). Muito risco para o problema.
- **Só push-to-talk**: cumpriria a subfase pela metade. Um botão não é uma wake
  word, e a 6.1 pede uma.
- **Streaming contínuo para a nuvem, sem gate**: seria a implementação mais
  simples e a pior decisão de privacidade e custo do projeto inteiro.
- **Casar a frase em qualquer posição do enunciado**: tolerar uma palavra antes
  do nome reabriria o buraco do contraexemplo, que começa com "o".

## Consequências

- O modo padrão do Jarvis **não envia áudio ambiente para lugar nenhum**.
- Ligar `JARVIS_WAKE_STRATEGY=transcription` é uma escolha informada: o `README`,
  o `.env.example` e a `docs/voice.md` dizem, em português claro, que trechos do
  ambiente passam a ser enviados enquanto o modo de escuta estiver ativo.
- O VAD, por ser aritmética determinística, é testável com PCM sintético: a mesma
  sequência de blocos produz exatamente os mesmos segmentos.
- **Custo aceito:** a wake word por transcrição tem latência de rede (algumas
  centenas de ms) e falha quando a Groq falha. Ela degrada para "não ativou", que
  é o desfecho seguro.
- **Gatilho para reconsiderar:** revisão da restrição "sem IA local". Um
  `PorcupineWakeWord` entraria como adapter, sem tocar `VoiceLoop`, `VoiceSession`
  ou o CLI — só o wiring e um valor de configuração.
