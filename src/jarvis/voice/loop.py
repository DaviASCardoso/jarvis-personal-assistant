"""O laço da conversa por voz.

```text
LISTENING → (wake) → CAPTURING → TRANSCRIBING → THINKING → SPEAKING → FOLLOW_UP
```

O que o loop **faz**: escuta, segmenta, transcreve, entrega o texto ao
`ConversationalAgent`, fala a resposta e administra a sessão.

O que o loop **não faz**, e não pode passar a fazer sem quebrar a fronteira que a
fase inteira existe para criar: montar prompt, ler contexto, recuperar memória,
gravar memória, avaliar política, executar Skill, publicar evento, tocar banco.
Nada disso é alcançável a partir daqui — `jarvis.voice` importa `jarvis.errors` e
mais nada de `jarvis`.

Três comportamentos que o desenho torna possíveis, e que valem registro:

- **silêncio é uma decisão válida**: `AgentReply.text is None` não sintetiza nada.
  Pagar uma síntese e três segundos de fala para não dizer nada seria o oposto do
  que o princípio significa;
- **interrupção sem thread**: `AudioSink.play` consulta `cancelled()` entre
  blocos, e `cancelled` é quem lê o microfone. Sem lock, sem fila, sem corrida;
- **falha não fecha a sessão**: um erro de transcrição, de síntese ou do agente
  vira uma frase curta e o turno seguinte continua. Só áudio quebrado encerra.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from jarvis.voice.audio import AudioChunk, PcmClip
from jarvis.voice.errors import (
    AudioError,
    SpeechToTextError,
    TextToSpeechError,
    VoiceError,
)
from jarvis.voice.ports import (
    AgentReply,
    AudioSink,
    AudioSource,
    ConversationalAgent,
    SpeechToText,
    TextToSpeech,
    VoiceSessionRepository,
    WakeWordDetection,
    WakeWordDetector,
)
from jarvis.voice.session import (
    SessionSettings,
    TurnRole,
    VoiceSession,
    VoiceState,
    VoiceStatus,
    VoiceTurn,
    new_session_id,
)
from jarvis.voice.vad import Segmenter, VadSettings
from jarvis.voice.wake import normalize

logger = logging.getLogger(__name__)

#: Blocos consecutivos acima do limiar para considerar que alguém falou por cima.
#: Um só seria qualquer estalo; dois já é voz.
BARGE_IN_BLOCKS: Final = 2

#: Respostas que confirmam ou recusam uma ação pendente. Lista **fechada**: o que
#: não estiver aqui não é confirmação, é um enunciado comum — errar para o lado
#: de não executar é o desfecho seguro.
AFFIRMATIVE: Final[frozenset[str]] = frozenset(
    {"sim", "isso", "confirmo", "confirmar", "pode", "claro", "ok", "positivo", "manda"}
)
NEGATIVE: Final[frozenset[str]] = frozenset(
    {"nao", "cancela", "cancelar", "para", "negativo", "esquece", "deixa"}
)

# As quatro frases que o Jarvis diz quando algo dá errado. São constantes, e não
# o texto da exceção, porque `architecture-contracts.md §13` proíbe expor detalhe
# interno ao usuário — e porque uma stack trace falada seria absurda.
COULD_NOT_HEAR: Final = "Não consegui te ouvir agora."
COULD_NOT_THINK: Final = "Tive um problema para pensar nisso."
COULD_NOT_SPEAK: Final = "(falha ao sintetizar a resposta)"
ENDED_BY_ERROR: Final = "audio_error"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSettings:
    vad: VadSettings = field(default_factory=VadSettings)
    session: SessionSettings = field(default_factory=SessionSettings)
    language: str | None = "pt"
    stt_timeout_seconds: float = 30.0
    tts_timeout_seconds: float = 15.0
    barge_in: bool = True
    #: Mais alto que o limiar do VAD de propósito: sem fone, o próprio
    #: alto-falante alimenta o microfone.
    barge_in_rms: float = 0.06
    read_timeout_seconds: float = 0.5
    speak_errors: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnOutcome:
    """O que um enunciado produziu. Existe para o teste e para o log — o loop não
    devolve isto a ninguém de fora."""

    session: VoiceSession
    transcript: str = ""
    reply: AgentReply | None = None
    spoke: bool = False
    interrupted: bool = False
    failure: str = ""


class VoiceLoop:
    def __init__(
        self,
        *,
        source: AudioSource,
        sink: AudioSink,
        stt: SpeechToText,
        tts: TextToSpeech,
        wake: WakeWordDetector,
        agent: ConversationalAgent,
        sessions: VoiceSessionRepository | None = None,
        settings: VoiceSettings | None = None,
        on_status: Callable[[VoiceStatus], None] = lambda status: None,
        on_session: Callable[[VoiceSession, bool], None] = lambda session, started: None,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        new_id: Callable[[], str] = new_session_id,
    ) -> None:
        self._source = source
        self._sink = sink
        self._stt = stt
        self._tts = tts
        self._wake = wake
        self._agent = agent
        self._sessions = sessions
        self._settings = settings if settings is not None else VoiceSettings()
        self._on_status = on_status
        self._on_session = on_session
        self._clock = clock
        self._monotonic = monotonic
        self._new_id = new_id

        self._segmenter = Segmenter(settings=self._settings.vad)
        self._pending: list[AudioChunk] = []
        self._last_transcript = ""
        self._last_reply = ""
        self._awaiting: str | None = None

    # --- laço externo --------------------------------------------------------

    def run(self, *, stop: Callable[[], bool] = lambda: False) -> None:
        """Sessão após sessão, até `stop()`. É o que `jarvis voice listen` chama."""
        self._source.start()
        try:
            while not stop():
                self.run_session(stop=stop)
        finally:
            self._source.stop()
            self._emit(VoiceState.IDLE, session=None)

    def run_session(self, *, stop: Callable[[], bool] = lambda: False) -> VoiceSession | None:
        """Uma sessão completa: da wake word ao encerramento."""
        detection = self._await_wake(stop=stop)
        if detection is None:
            return None

        session = VoiceSession(session_id=self._new_id(), started_at=self._clock())
        logger.info(
            "voice.session_started",
            extra={"session_id": session.session_id, "detector": detection.detector},
        )
        self._on_session(session, True)

        reason = "stopped"
        try:
            session, reason = self._converse(session, detection=detection, stop=stop)
        except AudioError as error:
            # Áudio quebrado é o único erro que encerra a sessão: sem dispositivo
            # não há conversa. O processo segue vivo — o painel continua servindo.
            logger.warning(
                "voice.session_audio_error",
                extra={"session_id": session.session_id, "error_type": type(error).__name__},
            )
            reason = ENDED_BY_ERROR

        session = session.end(at=self._clock(), reason=reason)
        self._save(session)
        self._on_session(session, False)
        logger.info(
            "voice.session_ended",
            extra={
                "session_id": session.session_id,
                "turns": session.turn_count,
                "reason": reason,
            },
        )
        self._emit(VoiceState.LISTENING, session=None)
        return session

    # --- estágios ------------------------------------------------------------

    def _await_wake(self, *, stop: Callable[[], bool]) -> WakeWordDetection | None:
        self._wake.reset()
        self._emit(VoiceState.LISTENING, session=None)
        while not stop():
            chunk = self._next_chunk()
            if chunk is None:
                continue
            detection = self._wake.feed(chunk)
            if detection is not None:
                return detection
        return None

    def _converse(
        self,
        session: VoiceSession,
        *,
        detection: WakeWordDetection,
        stop: Callable[[], bool],
    ) -> tuple[VoiceSession, str]:
        # O enunciado que ativou **é** o enunciado processado quando o detector já
        # o transcreveu inteiro. Sem isso, "jarvis, que horas são" exigiria falar
        # duas vezes.
        text = detection.remainder.strip()

        while True:
            if not text:
                captured = self._capture(session, stop=stop)
                if captured is None:
                    return session, "stopped" if stop() else "timeout"
                text = self._transcribe(session, captured)
                if not text:
                    continue

            outcome = self._handle(session, text=text)
            session = outcome.session
            text = ""

            if session.turn_count >= self._settings.session.max_turns:
                return session, "max_turns"
            if stop():
                return session, "stopped"
            self._emit(VoiceState.FOLLOW_UP, session=session)

    def _capture(self, session: VoiceSession, *, stop: Callable[[], bool]) -> PcmClip | None:
        """Grava um enunciado. `None` = a janela fechou sem ninguém falar."""
        self._emit(VoiceState.CAPTURING, session=session)
        self._segmenter.reset()
        deadline = self._monotonic() + self._settings.session.follow_up_seconds

        while not stop():
            chunk = self._next_chunk()
            if chunk is None:
                if not self._segmenter.is_speaking and self._monotonic() >= deadline:
                    return None
                continue

            segment = self._segmenter.feed(chunk)
            if segment is not None:
                return segment.clip
            if not self._segmenter.is_speaking and self._monotonic() >= deadline:
                return None

        self._segmenter.reset()
        return None

    def _transcribe(self, session: VoiceSession, clip: PcmClip) -> str:
        self._emit(VoiceState.TRANSCRIBING, session=session)
        try:
            transcript = self._stt.transcribe(
                clip,
                language=self._settings.language,
                timeout_seconds=self._settings.stt_timeout_seconds,
            )
        except SpeechToTextError as error:
            logger.warning(
                "voice.transcription_failed",
                extra={"session_id": session.session_id, "error_type": type(error).__name__},
            )
            self._say_error(session, COULD_NOT_HEAR)
            return ""

        if transcript.is_empty:
            # Silêncio transcrito não é uma pergunta: nenhum turno, nenhuma
            # chamada paga ao modelo.
            return ""
        self._last_transcript = transcript.text
        return transcript.text

    def _handle(self, session: VoiceSession, *, text: str) -> TurnOutcome:
        started = self._monotonic()
        self._emit(VoiceState.THINKING, session=session, transcript=text)
        session = session.append(
            VoiceTurn(
                role=TurnRole.USER,
                text=text,
                at=self._clock(),
                correlation_id=session.correlation_id,
            )
        )

        try:
            reply = self._ask(session, text=text)
        except Exception as error:  # o implementador do port vive fora deste pacote
            logger.warning(
                "voice.agent_failed",
                extra={"session_id": session.session_id, "error_type": type(error).__name__},
            )
            self._say_error(session, COULD_NOT_THINK)
            self._save(session)
            return TurnOutcome(session=session, transcript=text, failure=type(error).__name__)

        self._awaiting = reply.awaiting_confirmation
        latency_ms = (self._monotonic() - started) * 1000

        if reply.text is None:
            # Silêncio deliberado: nada é sintetizado, nada é falado, e o turno do
            # assistente não existe.
            logger.info(
                "voice.silent_turn",
                extra={"session_id": session.session_id, "decision_type": reply.decision_type},
            )
            self._save(session)
            return TurnOutcome(session=session, transcript=text, reply=reply)

        session = session.append(
            VoiceTurn(
                role=TurnRole.ASSISTANT,
                text=reply.text,
                at=self._clock(),
                latency_ms=latency_ms,
                decision_type=reply.decision_type,
                correlation_id=reply.correlation_id or session.correlation_id,
            )
        )
        self._last_reply = reply.text
        spoke, interrupted = self._speak(session, reply.text)
        self._save(session)
        return TurnOutcome(
            session=session,
            transcript=text,
            reply=reply,
            spoke=spoke,
            interrupted=interrupted,
        )

    def _ask(self, session: VoiceSession, *, text: str) -> AgentReply:
        """Uma resposta a uma confirmação pendente não é um enunciado comum."""
        pending = self._awaiting
        if pending is not None:
            answer = _confirmation_answer(text)
            if answer is not None:
                logger.info(
                    "voice.confirmation_answered",
                    extra={"execution_id": pending, "granted": answer},
                )
                return self._agent.answer_confirmation(pending, granted=answer, session=session)
        return self._agent.respond(text, session=session)

    def _speak(self, session: VoiceSession, text: str) -> tuple[bool, bool]:
        self._emit(VoiceState.SPEAKING, session=session, reply=text)
        try:
            clip = self._tts.synthesize(text, timeout_seconds=self._settings.tts_timeout_seconds)
        except TextToSpeechError as error:
            # Ficar mudo sem sinal é pior que responder por texto: a resposta já
            # está na sessão e no painel, e o log diz por que ela não foi falada.
            logger.warning(
                "voice.synthesis_failed",
                extra={"session_id": session.session_id, "error_type": type(error).__name__},
            )
            return False, False

        result = self._sink.play(clip, cancelled=self._barge_in())
        if result.interrupted:
            logger.info(
                "voice.playback_interrupted",
                extra={
                    "session_id": session.session_id,
                    "played_seconds": round(result.played_seconds, 2),
                },
            )
        return True, result.interrupted

    def _barge_in(self) -> Callable[[], bool]:
        """A função que `AudioSink.play` consulta entre blocos.

        Ela **lê o microfone** e guarda o que ouviu: o áudio da interrupção vira o
        início do próximo enunciado, em vez de ser jogado fora e obrigar a pessoa
        a repetir.
        """
        if not self._settings.barge_in:
            return lambda: False

        hits = 0

        def cancelled() -> bool:
            nonlocal hits
            chunk = self._source.read(timeout_seconds=0.0)
            if chunk is None:
                return False
            self._pending.append(chunk)
            hits = hits + 1 if chunk.rms >= self._settings.barge_in_rms else 0
            return hits >= BARGE_IN_BLOCKS

        return cancelled

    # --- utilitários ---------------------------------------------------------

    def _next_chunk(self) -> AudioChunk | None:
        """O que a interrupção capturou vem antes do que o dispositivo tem agora."""
        if self._pending:
            return self._pending.pop(0)
        return self._source.read(timeout_seconds=self._settings.read_timeout_seconds)

    def _say_error(self, session: VoiceSession, message: str) -> None:
        if not self._settings.speak_errors:
            return
        try:
            clip = self._tts.synthesize(message, timeout_seconds=self._settings.tts_timeout_seconds)
            self._sink.play(clip)
        except (TextToSpeechError, AudioError, VoiceError) as error:
            logger.warning(
                "voice.error_message_not_spoken",
                extra={"session_id": session.session_id, "error_type": type(error).__name__},
            )

    def _save(self, session: VoiceSession) -> None:
        if self._sessions is None:
            return
        self._sessions.save(session)

    def _emit(
        self,
        state: VoiceState,
        *,
        session: VoiceSession | None,
        transcript: str | None = None,
        reply: str | None = None,
    ) -> None:
        if transcript is not None:
            self._last_transcript = transcript
        if reply is not None:
            self._last_reply = reply
        self._on_status(
            VoiceStatus(
                state=state,
                at=self._clock(),
                session_id=session.session_id if session is not None else None,
                last_transcript=self._last_transcript,
                last_reply=self._last_reply,
            )
        )


def _confirmation_answer(text: str) -> bool | None:
    """`True`/`False` só para as listas fechadas; `None` para todo o resto."""
    tokens = normalize(text).split()
    if not tokens:
        return None
    if tokens[0] in AFFIRMATIVE:
        return True
    if tokens[0] in NEGATIVE:
        return False
    return None
