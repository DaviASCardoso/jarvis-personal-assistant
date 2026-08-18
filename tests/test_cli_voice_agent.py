"""`RuntimeConversationalAgent` (Fase 11.2) — raciocínio multi-passo por voz.

Primeira cobertura direta desta classe: até aqui só `voice_doubles.py`
testava o resto da pilha de voz com um `ConversationalAgent` falso. Aqui os
componentes são reais (SQLite em memória), só o LLM é `StubLLMProvider` —
mesmo espírito de `test_cli_session_reflection.py`.
"""

from datetime import UTC, datetime

import pytest

from jarvis import cli
from jarvis.cli import RuntimeConversationalAgent, build_agent_runtime, build_skill_registry
from jarvis.config import Settings
from jarvis.context.adapters.sqlite_snapshots import IN_MEMORY_DATABASE as CONTEXT_IN_MEMORY
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE as EVENTS_IN_MEMORY
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE as MEMORY_IN_MEMORY
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.voice.session import VoiceSession
from tests.agent_doubles import StubLLMProvider, decision_json

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _session() -> VoiceSession:
    return VoiceSession(session_id="voice-1", started_at=NOW)


class TestMultiStepVoiceReasoning:
    def test_two_silent_steps_produce_a_single_spoken_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "system.status"}),
                decision_json(type="notify", message="prontinho"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = cli.build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            agent = RuntimeConversationalAgent(
                settings,
                runtime=runtime,
                context=context,
                memories=memories,
                store=store,
                skills=build_skill_registry(),
                execute=True,
            )

            reply = agent.respond("deixe tudo pronto", session=_session())

        assert reply.text == "prontinho"
        assert len(provider.requests) == 2

    def test_a_single_notify_still_answers_in_one_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = StubLLMProvider([decision_json(type="notify", message="oi")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = cli.build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            agent = RuntimeConversationalAgent(
                settings,
                runtime=runtime,
                context=context,
                memories=memories,
                store=store,
                skills=build_skill_registry(),
                execute=True,
            )

            reply = agent.respond("oi", session=_session())

        assert reply.text == "oi"
        assert len(provider.requests) == 1

    def test_a_pending_confirmation_still_pauses_with_the_execution_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(
                    type="act",
                    message=None,
                    action={
                        "skill": "file.write",
                        "parameters": {"path": "nota.txt", "content": "oi"},
                    },
                ),
                decision_json(type="notify", message="preciso da sua confirmação"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setenv("JARVIS_POLICY_CONFIRM_RISK", "medium")
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = cli.build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            agent = RuntimeConversationalAgent(
                settings,
                runtime=runtime,
                context=context,
                memories=memories,
                store=store,
                skills=build_skill_registry(),
                execute=True,
            )

            reply = agent.respond("escreva uma nota", session=_session())

        assert reply.awaiting_confirmation is not None
        assert "preciso da sua confirmação" in (reply.text or "")

    def test_a_denial_is_spoken_as_natural_language_not_a_fixed_template(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fase 11.1/11.2: a fala reflete a explicação do modelo, não só o
        template fixo de `_spoken_outcome` (que continua entrando como prefixo)."""
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "not.a.real.skill"}),
                decision_json(type="notify", message="essa skill não existe no catálogo"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = cli.build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            agent = RuntimeConversationalAgent(
                settings,
                runtime=runtime,
                context=context,
                memories=memories,
                store=store,
                skills=build_skill_registry(),
                execute=True,
            )

            reply = agent.respond("faça algo impossível", session=_session())

        assert "essa skill não existe no catálogo" in (reply.text or "")

    def test_without_execute_never_submits_and_answers_in_one_step(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = cli.build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            agent = RuntimeConversationalAgent(
                settings,
                runtime=runtime,
                context=context,
                memories=memories,
                store=store,
                skills=build_skill_registry(),
                execute=False,
            )

            reply = agent.respond("qual o status?", session=_session())

        assert reply.text is None
        assert reply.awaiting_confirmation is None
        assert len(provider.requests) == 1
