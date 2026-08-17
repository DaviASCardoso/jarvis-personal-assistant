"""`cli._reflect_on_session` (Fase 10.3) — memória de fim de sessão.

Componentes reais (SQLite em memória), só o LLM é `StubLLMProvider` — mesmo
espírito de `test_proactivity_integration.py`. Não passa por `main()`: testa
o helper diretamente, e separadamente a composição com `_conversation_of`
(o caminho de voz), sem precisar montar `_serve_voice` inteiro (áudio, STT,
TTS) só para provar o hook.
"""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.agent.conversation import Conversation, ConversationTurn
from jarvis.agent.messages import Role
from jarvis.cli import (
    _conversation_of,
    _reflect_on_session,
    build_agent_runtime,
    build_context_engine,
    build_memory_manager,
)
from jarvis.config import Settings
from jarvis.context.adapters.sqlite_snapshots import IN_MEMORY_DATABASE as CONTEXT_IN_MEMORY
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.events.adapters.sqlite_store import IN_MEMORY_DATABASE as EVENTS_IN_MEMORY
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.memory.adapters.sqlite_repository import IN_MEMORY_DATABASE as MEMORY_IN_MEMORY
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.memory.ports import MemoryCriteria
from jarvis.voice.session import TurnRole, VoiceSession, VoiceTurn
from tests.agent_doubles import StubLLMProvider, decision_json

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _conversation(*lines: str) -> Conversation:
    conversation = Conversation(conversation_id="c-1")
    for index, text in enumerate(lines):
        role = Role.USER if index % 2 == 0 else Role.ASSISTANT
        conversation = conversation.append(ConversationTurn(role=role, text=text, at=NOW))
    return conversation


class TestReflectOnSession:
    def test_a_proposed_memory_is_persisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={
                        "type": "preference",
                        "content": "prefere reuniões pela manhã",
                        "subject": "reuniao.horario",
                    },
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            manager = build_memory_manager(memories)

            _reflect_on_session(
                runtime,
                conversation=_conversation("prefiro reuniões pela manhã", "anotado"),
                conversation_id="c-1",
                memory_manager=manager,
                store=store,
                context=context,
            )

            assert len(memories.search(MemoryCriteria())) == 1
        assert provider.calls == 1

    def test_an_empty_conversation_never_calls_the_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = StubLLMProvider([decision_json()])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            manager = build_memory_manager(memories)

            _reflect_on_session(
                runtime,
                conversation=Conversation(conversation_id="c-empty"),
                conversation_id="c-empty",
                memory_manager=manager,
                store=store,
                context=context,
            )

        assert provider.calls == 0

    def test_composes_with_the_voice_session_translation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O mesmo caminho que `_serve_voice` usa ao fechar uma sessão:
        `VoiceSession` → `_conversation_of` → `_reflect_on_session`."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={
                        "type": "preference",
                        "content": "prefere café sem açúcar",
                        "subject": "cafe.acucar",
                    },
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        settings = Settings()
        session = VoiceSession(
            session_id="voice-1",
            started_at=NOW,
            turns=(
                VoiceTurn(role=TurnRole.USER, text="prefiro café sem açúcar", at=NOW),
                VoiceTurn(role=TurnRole.ASSISTANT, text="anotado", at=NOW),
            ),
        )

        with (
            SqliteEventStore.open(EVENTS_IN_MEMORY) as store,
            SqliteContextSnapshotRepository.open(CONTEXT_IN_MEMORY) as snapshots,
            SqliteMemoryRepository.open(MEMORY_IN_MEMORY) as memories,
        ):
            context = build_context_engine(settings, snapshots)
            runtime = build_agent_runtime(settings, context=context, memories=memories)
            manager = build_memory_manager(memories)

            _reflect_on_session(
                runtime,
                conversation=_conversation_of(session),
                conversation_id=session.session_id,
                memory_manager=manager,
                store=store,
                context=context,
            )

        assert provider.calls == 1
        envelope_conversation = provider.requests[0].messages[0].content
        assert "café sem açúcar" in envelope_conversation


class TestChatSessionReflectionToggle:
    """A partir de `main()`, ponta a ponta: `agent chat` fecha e reflete."""

    @pytest.fixture(autouse=True)
    def isolated_data_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        data_dir = tmp_path / "data"
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
        monkeypatch.setenv("JARVIS_LOG_LEVEL", "CRITICAL")
        return data_dir

    def test_enabled_by_default_reflects_at_eof(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:

        provider = StubLLMProvider(
            [
                decision_json(type="notify", message="oi"),
                decision_json(
                    type="remember",
                    message=None,
                    memory={
                        "type": "preference",
                        "content": "prefere Python",
                        "subject": "linguagem.preferida",
                    },
                ),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setattr("sys.stdin", io.StringIO("prefiro Python\n"))

        assert cli.main(["agent", "chat"]) == 0

        out = capsys.readouterr().out
        assert "sessão      memória gravada como" in out
        assert provider.calls == 2

    def test_disabled_via_config_skips_the_extra_call(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:

        provider = StubLLMProvider([decision_json(type="notify", message="oi")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setenv("JARVIS_AGENT_SESSION_REFLECTION_ENABLED", "false")
        monkeypatch.setattr("sys.stdin", io.StringIO("oi\n"))

        assert cli.main(["agent", "chat"]) == 0

        out = capsys.readouterr().out
        assert "sessão      memória" not in out
        assert provider.calls == 1
