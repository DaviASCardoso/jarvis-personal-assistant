"""O laço da conversa por voz, de ponta a ponta e sem nada real.

Microfone, alto-falante, Groq, Google, Gemini, política e banco: todos
substituídos por doubles. É a propriedade que o port `ConversationalAgent`
comprou — o loop inteiro é verificável sem LLM, sem rede e sem hardware.
"""

from collections.abc import Sequence

import pytest

from jarvis.voice.audio import AudioChunk
from jarvis.voice.errors import AudioError
from jarvis.voice.loop import COULD_NOT_HEAR, COULD_NOT_THINK, VoiceLoop, VoiceSettings
from jarvis.voice.ports import AgentReply
from jarvis.voice.session import SessionSettings, TurnRole, VoiceSession, VoiceState, VoiceStatus
from jarvis.voice.vad import VadSettings
from tests.voice_doubles import (
    FakeAudioSource,
    FakeMonotonic,
    InMemoryVoiceSessions,
    RecordingAudioSink,
    ScriptedAgent,
    ScriptedSpeechToText,
    ScriptedTextToSpeech,
    ScriptedWakeWord,
    stream,
    stt_error,
    tts_error,
)

#: Um enunciado: o bloco que acorda, fala, e o silêncio que fecha o segmento.
UTTERANCE = [("loud", 0.6), ("quiet", 1.0)]

SETTINGS = VoiceSettings(
    vad=VadSettings(silence_ms=500),
    session=SessionSettings(follow_up_seconds=1.0, idle_timeout_seconds=2.0),
    barge_in=False,
)


class Harness:
    """Monta o loop com doubles e encerra quando o áudio acaba."""

    def __init__(
        self,
        *,
        pattern: Sequence[tuple[str, float]] = tuple(UTTERANCE),
        transcripts: Sequence[str] = ("que horas são",),
        replies: Sequence[AgentReply] = (),
        settings: VoiceSettings = SETTINGS,
        sink: RecordingAudioSink | None = None,
        stt: ScriptedSpeechToText | None = None,
        tts: ScriptedTextToSpeech | None = None,
        wake: ScriptedWakeWord | None = None,
        sessions: InMemoryVoiceSessions | None = None,
        source: FakeAudioSource | None = None,
    ) -> None:
        self.source = source if source is not None else FakeAudioSource(stream(list(pattern)))
        self.sink = sink if sink is not None else RecordingAudioSink()
        self.stt = stt if stt is not None else ScriptedSpeechToText(list(transcripts))
        self.tts = tts if tts is not None else ScriptedTextToSpeech()
        self.wake = wake if wake is not None else ScriptedWakeWord(trigger_after=1)
        self.agent = ScriptedAgent(replies=list(replies))
        self.sessions = sessions
        self.statuses: list[VoiceStatus] = []
        self.opened: list[VoiceSession] = []
        self.closed: list[VoiceSession] = []
        self.loop = VoiceLoop(
            source=self.source,
            sink=self.sink,
            stt=self.stt,
            tts=self.tts,
            wake=self.wake,
            agent=self.agent,
            sessions=sessions,
            settings=settings,
            on_status=self.statuses.append,
            on_session=self._on_session,
            # Passo curto: a janela de follow-up (1 s) precisa sobreviver a
            # dezenas de blocos de áudio e ainda assim expirar rápido quando o
            # silêncio se estende.
            monotonic=FakeMonotonic(step=0.05),
        )

    def _on_session(self, session: VoiceSession, started: bool) -> None:
        (self.opened if started else self.closed).append(session)

    def stop(self) -> bool:
        return self.source.remaining == 0

    def run_session(self) -> VoiceSession | None:
        return self.loop.run_session(stop=self.stop)

    @property
    def states(self) -> list[VoiceState]:
        return [status.state for status in self.statuses]


def reply(text: str | None = "nove e vinte", **kwargs: object) -> AgentReply:
    return AgentReply(text=text, decision_type="notify", **kwargs)  # type: ignore[arg-type]


# --- caminho feliz -----------------------------------------------------------


def test_a_whole_turn_goes_from_wake_word_to_spoken_answer() -> None:
    harness = Harness(replies=[reply()])

    session = harness.run_session()

    assert session is not None
    assert [turn.role for turn in session.turns] == [TurnRole.USER, TurnRole.ASSISTANT]
    assert session.turns[0].text == "que horas são"
    assert session.turns[1].text == "nove e vinte"
    assert harness.agent.heard == ["que horas são"]
    assert harness.tts.calls == ["nove e vinte"]
    assert len(harness.sink.played) == 1


def test_the_session_carries_its_own_id_as_correlation() -> None:
    session = Harness(replies=[reply()]).run_session()

    assert session is not None
    assert session.correlation_id == session.session_id


def test_the_states_follow_the_documented_machine() -> None:
    harness = Harness(replies=[reply()])

    harness.run_session()

    assert harness.states[:6] == [
        VoiceState.LISTENING,
        VoiceState.CAPTURING,
        VoiceState.TRANSCRIBING,
        VoiceState.THINKING,
        VoiceState.SPEAKING,
        VoiceState.FOLLOW_UP,
    ]


def test_the_wake_word_that_already_heard_the_command_skips_capture_and_stt() -> None:
    # "jarvis, que horas são" não pode exigir falar duas vezes. Um bloco de áudio
    # só: o suficiente para acordar, e nada a capturar depois.
    harness = Harness(
        source=FakeAudioSource(stream([("loud", 0.1)])),
        wake=ScriptedWakeWord(trigger_after=1, remainder="que horas sao"),
    )

    session = harness.run_session()

    assert session is not None
    assert harness.stt.calls == []
    assert harness.agent.heard == ["que horas sao"]


def test_the_session_is_opened_and_closed_through_the_callback() -> None:
    harness = Harness(replies=[reply()])

    harness.run_session()

    assert len(harness.opened) == 1
    assert len(harness.closed) == 1
    assert harness.closed[0].ended_at is not None
    assert harness.opened[0].session_id == harness.closed[0].session_id


def test_no_audio_means_no_session_at_all() -> None:
    harness = Harness(source=FakeAudioSource([]))

    assert harness.run_session() is None
    assert harness.opened == []


# --- silêncio ----------------------------------------------------------------


def test_a_silent_decision_speaks_nothing() -> None:
    # Pagar uma síntese para não dizer nada seria o oposto do princípio.
    harness = Harness(replies=[AgentReply(text=None, decision_type="ignore")])

    session = harness.run_session()

    assert session is not None
    assert [turn.role for turn in session.turns] == [TurnRole.USER]
    assert harness.tts.calls == []
    assert harness.sink.played == []


def test_a_transcript_with_nothing_in_it_never_reaches_the_agent() -> None:
    harness = Harness(transcripts=[""])

    session = harness.run_session()

    assert session is not None
    assert session.turns == ()
    assert harness.agent.heard == []


# --- falhas ------------------------------------------------------------------


def test_a_transcription_failure_keeps_the_session_alive() -> None:
    harness = Harness(stt=ScriptedSpeechToText(["oi"], error=stt_error()))

    session = harness.run_session()

    assert session is not None
    assert harness.agent.heard == []
    assert COULD_NOT_HEAR in harness.tts.calls


def test_a_synthesis_failure_still_records_what_was_answered() -> None:
    harness = Harness(replies=[reply()], tts=ScriptedTextToSpeech(error=tts_error()))

    session = harness.run_session()

    assert session is not None
    assert session.turns[1].text == "nove e vinte"
    assert harness.sink.played == []


def test_an_agent_failure_becomes_a_short_sentence_not_a_crash() -> None:
    harness = Harness()
    harness.agent.error = RuntimeError("qualquer coisa vinda de fora do pacote")

    session = harness.run_session()

    assert session is not None
    assert [turn.role for turn in session.turns] == [TurnRole.USER]
    assert COULD_NOT_THINK in harness.tts.calls


def test_an_audio_failure_ends_the_session_without_raising() -> None:
    class BrokenSource(FakeAudioSource):
        def read(self, *, timeout_seconds: float) -> AudioChunk | None:
            if self.remaining == 0:
                raise AudioError("dispositivo sumiu")
            return super().read(timeout_seconds=timeout_seconds)

    source = BrokenSource(stream([("loud", 0.2)]))
    harness = Harness(source=source)

    session = harness.loop.run_session(stop=lambda: False)

    assert session is not None
    assert session.ended_reason == "audio_error"


# --- interrupção -------------------------------------------------------------


def test_speaking_over_the_answer_interrupts_it() -> None:
    settings = VoiceSettings(
        vad=VadSettings(silence_ms=500),
        session=SessionSettings(follow_up_seconds=1.0),
        barge_in=True,
        barge_in_rms=0.01,
    )
    harness = Harness(replies=[reply()], sink=RecordingAudioSink(cancel_after=1), settings=settings)

    harness.run_session()

    assert harness.sink.results[0].interrupted is True


def test_with_barge_in_off_the_microphone_is_not_read_during_playback() -> None:
    harness = Harness(replies=[reply()], sink=RecordingAudioSink(cancel_after=None))
    before = harness.source.remaining

    harness.run_session()

    # Sem barge-in, `cancelled` nunca consulta o dispositivo: o que sobrou de
    # áudio continua lá para o próximo enunciado.
    assert harness.source.remaining <= before


# --- confirmação -------------------------------------------------------------


def test_saying_yes_answers_the_pending_confirmation() -> None:
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE],
        transcripts=["apague o relatório", "sim"],
        replies=[
            reply("Isso apaga relatorio.txt. Confirma?", awaiting_confirmation="exec-7"),
            reply("Feito."),
        ],
    )

    harness.run_session()

    assert harness.agent.confirmations == [("exec-7", True)]


def test_saying_no_denies_it() -> None:
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE],
        transcripts=["apague tudo", "cancela"],
        replies=[reply("Confirma?", awaiting_confirmation="exec-9"), reply("Ok.")],
    )

    harness.run_session()

    assert harness.agent.confirmations == [("exec-9", False)]


def test_an_ambiguous_answer_is_not_a_confirmation() -> None:
    # Errar para o lado de não executar é o desfecho seguro.
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE],
        transcripts=["apague tudo", "talvez mais tarde"],
        replies=[reply("Confirma?", awaiting_confirmation="exec-9"), reply("Certo.")],
    )

    harness.run_session()

    assert harness.agent.confirmations == []
    assert harness.agent.heard == ["apague tudo", "talvez mais tarde"]


# --- fim de sessão -----------------------------------------------------------


def test_a_conversation_stops_at_the_turn_ceiling() -> None:
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE, *UTTERANCE],
        transcripts=["um", "dois", "tres"],
        replies=[reply("a"), reply("b"), reply("c")],
        settings=VoiceSettings(
            vad=VadSettings(silence_ms=500),
            session=SessionSettings(follow_up_seconds=1.0, max_turns=2),
            barge_in=False,
        ),
    )

    session = harness.run_session()

    assert session is not None
    assert session.ended_reason == "max_turns"
    assert session.turn_count == 2


def test_silence_after_the_follow_up_window_closes_the_session() -> None:
    harness = Harness(replies=[reply()])

    session = harness.loop.run_session(stop=lambda: False)

    assert session is not None
    assert session.ended_reason == "timeout"


def test_run_keeps_opening_sessions_until_told_to_stop() -> None:
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE],
        transcripts=["um", "dois"],
        replies=[reply("a"), reply("b")],
    )

    harness.loop.run(stop=harness.stop)

    assert harness.source.started == 1
    assert harness.source.stopped == 1
    assert harness.states[-1] is VoiceState.IDLE


# --- persistência ------------------------------------------------------------


def test_the_session_is_saved_with_its_turns() -> None:
    sessions = InMemoryVoiceSessions()
    harness = Harness(replies=[reply()], sessions=sessions)

    session = harness.run_session()

    assert session is not None
    stored = sessions.get(session.session_id)
    assert stored is not None
    assert stored.turn_count == 2
    assert stored.ended_at is not None


def test_without_a_repository_the_loop_still_works() -> None:
    # Persistir é opcional: `jarvis voice say` e os testes não precisam de banco.
    assert Harness(replies=[reply()]).run_session() is not None


@pytest.mark.parametrize("answer", ["sim", "Sim!", "SIM, pode", "confirmo"])
def test_affirmatives_are_recognized_regardless_of_case_and_punctuation(answer: str) -> None:
    harness = Harness(
        pattern=[*UTTERANCE, *UTTERANCE],
        transcripts=["apague", answer],
        replies=[reply("Confirma?", awaiting_confirmation="exec-1"), reply("Ok.")],
    )

    harness.run_session()

    assert harness.agent.confirmations == [("exec-1", True)]
