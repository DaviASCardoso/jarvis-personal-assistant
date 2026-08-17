"""`jarvis agent pursue` — Goal Pursuit Loop (Fase 9.2).

`Decision` continua atômica: cada asserção aqui prova um dos cinco critérios
de parada do loop, nunca uma mudança de schema em `Decision`/`ActionProposal`.
Mesmas fixtures de `test_cli_action.py` — a cadeia inteira roda de verdade
(Policy Engine, Skill Registry, backend local), só o LLM é `StubLLMProvider`.
"""

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


class TestAgentPursue:
    def test_pursues_a_goal_across_multiple_real_steps(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "system.status"}),
                decision_json(
                    type="act",
                    message=None,
                    action={
                        "skill": "file.write",
                        "parameters": {"path": "nota.txt", "content": "oi"},
                    },
                ),
                decision_json(type="notify", message="pronto"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "deixe tudo pronto"]) == 0

        out = capsys.readouterr().out
        assert out.count("status      completed") == 2
        assert "agente      concluído: nada mais a propor" in out
        assert len(provider.requests) == 3

    def test_stops_at_the_step_cap(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """O teto vale mesmo quando a proposta muda a cada passo — não é o
        guard de repetição que está impedindo o quarto passo aqui."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="act",
                    message=None,
                    action={"skill": "file.write", "parameters": {"path": "a.txt", "content": "1"}},
                ),
                decision_json(
                    type="act",
                    message=None,
                    action={"skill": "file.write", "parameters": {"path": "b.txt", "content": "2"}},
                ),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "objetivo sem fim", "--max-steps", "2"]) == 0

        out = capsys.readouterr().out
        assert "agente      parado: 2 passos atingidos" in out
        assert len(provider.requests) == 2

    def test_stops_before_repeating_the_identical_proposal(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "objetivo repetitivo"]) == 0

        out = capsys.readouterr().out
        assert "agente      parado: repetiria a mesma ação" in out
        assert out.count("status      completed") == 1
        assert len(provider.requests) == 2

    def test_pauses_on_a_pending_confirmation_without_auto_confirming(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_CONFIRM_RISK", "medium")
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
                decision_json(type="notify", message="a ação está aguardando sua confirmação"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "escreva uma nota"]) == 0

        out = capsys.readouterr().out
        assert "status      awaiting_confirmation" in out
        assert "agente      pausado: confirme com" in out
        assert "a ação está aguardando sua confirmação" in out
        assert not (tmp_path / "data" / "workspace" / "nota.txt").exists()
        # Fase 10.2: parar por confirmação pendente também pede uma
        # explicação em linguagem natural (`_explain_outcome`), como já
        # acontecia em `agent ask --execute` — por isso duas chamadas, não uma.
        assert len(provider.requests) == 2

    def test_stops_when_policy_denies_the_action(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "not.a.real.skill"}),
                decision_json(type="notify", message="a política recusou essa ação"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "algo impossível"]) == 0

        out = capsys.readouterr().out
        assert "status      denied" in out
        assert "agente      parado: ação negada, não insistindo" in out
        assert "a política recusou essa ação" in out
        assert len(provider.requests) == 2

    def test_without_a_goal_argument_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit):
            main(["agent", "pursue"])

    def test_the_next_step_actually_sees_the_file_content(
        self, monkeypatch: pytest.MonkeyPatch, isolated_data_dir: Path
    ) -> None:
        """Fase 10.4: `file.read` deixou de esconder o conteúdo do próprio
        agente — o segundo passo precisa conseguir citar o que o primeiro
        leu, não só saber que "algo foi lido"."""
        workspace = isolated_data_dir / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "notas.txt").write_text("prefere reuniões pela manhã", encoding="utf-8")

        provider = StubLLMProvider(
            [
                decision_json(
                    type="act",
                    message=None,
                    action={"skill": "file.read", "parameters": {"path": "notas.txt"}},
                ),
                decision_json(type="notify", message="pronto"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "pursue", "leia notas.txt e resuma"]) == 0

        assert len(provider.requests) == 2
        second_envelope = provider.requests[1].messages[0].content
        assert "prefere reuniões pela manhã" in second_envelope
