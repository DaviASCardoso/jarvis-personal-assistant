"""`AgentLoopResult` (Fase 11.1) — o turno de reflexão vira o desfecho do loop.

Antes da 11.1, `_run_agent_loop` devolvia sempre o turno cru que propôs a
ação (via `_explain_outcome`, que só imprimia a reflexão sem devolvê-la).
Isso significa que `agent chat` guardava na `Conversation` a mensagem do
turno que **propôs** a ação negada/pendente — tipicamente `message=None` —
em vez da explicação em linguagem natural que o usuário efetivamente lê.
Este teste prova o oposto agora: a reflexão entra na `Conversation`, e por
isso aparece no envelope da próxima chamada ao LLM.
"""

import io
from pathlib import Path

import pytest

from jarvis import cli
from jarvis.cli import main
from tests.agent_doubles import StubLLMProvider, decision_json


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "CRITICAL")
    return data_dir


class TestAgentLoopResultCarriesTheReflectionTurn:
    def test_a_denied_action_s_reflection_reaches_the_next_turn_s_envelope(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "not.a.real.skill"}),
                decision_json(type="notify", message="essa skill não existe no catálogo"),
                decision_json(type="notify", message="oi de novo"),
                decision_json(type="notify", message="fim de sessão"),  # reflexão (10.3)
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setattr("sys.stdin", io.StringIO("faça algo impossível\nsegunda linha\n"))

        assert main(["agent", "chat", "--execute"]) == 0

        out = capsys.readouterr().out
        assert "status      denied" in out
        assert "essa skill não existe no catálogo" in out
        # A reflexão (não o turno cru que só propôs a ação negada) virou o
        # turno do assistente na `Conversation` — por isso ela reaparece no
        # envelope de texto enviado ao modelo no turno seguinte (a 4ª chamada
        # é a reflexão de fim de sessão da Fase 10.3, sem relação com este teste).
        assert len(provider.requests) == 4
        second_turn_envelope = provider.requests[2].messages[0].content
        assert "essa skill não existe no catálogo" in second_turn_envelope
