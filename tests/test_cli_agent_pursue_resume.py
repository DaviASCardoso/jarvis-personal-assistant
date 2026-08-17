"""`jarvis agent pursue --resume` — checkpoint/resume do Goal Pursuit Loop
(Fase 10.5).

Mesmas fixtures de `test_cli_agent_pursue.py`. Cada teste prova uma garantia
específica do checkpoint: id previsível na saída, erro claro para id
desconhecido ou pursuit já concluído, numeração de passo correta ao retomar,
e orientação extra chegando ao prompt do próximo turno.
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


def pursuit_id_from(out: str) -> str:
    line = next(line for line in out.splitlines() if line.startswith("pursuit "))
    return line.split()[1]


def execution_id_from(out: str) -> str:
    return next(line.split()[1] for line in out.splitlines() if line.startswith("execution "))


class TestResumeValidation:
    def test_resuming_an_unknown_pursuit_is_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["agent", "pursue", "--resume", "does-not-exist"]) == 2

        assert "não encontrado" in capsys.readouterr().err

    def test_resuming_a_completed_pursuit_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider([decision_json(type="notify", message="já terminei")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        assert main(["agent", "pursue", "verifique o status"]) == 0
        pursuit_id = pursuit_id_from(capsys.readouterr().out)

        assert main(["agent", "pursue", "--resume", pursuit_id]) == 2

        assert "já concluiu" in capsys.readouterr().err

    def test_a_max_steps_not_greater_than_the_checkpoint_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        assert main(["agent", "pursue", "veja o status", "--max-steps", "1"]) == 0
        pursuit_id = pursuit_id_from(capsys.readouterr().out)

        assert main(["agent", "pursue", "--resume", pursuit_id, "--max-steps", "1"]) == 2

        assert "precisa ser maior" in capsys.readouterr().err


class TestResumeContinuesTheLoop:
    def test_pauses_then_resumes_after_confirming(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
                decision_json(type="notify", message="pausado, aguardando"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        assert main(["agent", "pursue", "escreva uma nota"]) == 0
        out = capsys.readouterr().out
        pursuit_id = pursuit_id_from(out)
        execution_id = execution_id_from(out)
        assert "agente      pausado: confirme com" in out

        assert main(["action", "confirm", execution_id]) == 0
        capsys.readouterr()

        resume_provider = StubLLMProvider([decision_json(type="notify", message="retomado")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: resume_provider)

        assert main(["agent", "pursue", "--resume", pursuit_id]) == 0

        out = capsys.readouterr().out
        assert f"pursuit     {pursuit_id} (retomado do passo 1)" in out
        assert "retomado" in out

    def test_resuming_after_the_step_cap_continues_numbering(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        # Com --max-steps 1, "passo N/M"/"parado: N passos atingidos" ficam
        # suprimidos (paridade com `agent ask` de antes da 10.2) — mas o
        # checkpoint é gravado do mesmo jeito, e é isso que este teste prova.
        assert main(["agent", "pursue", "veja o status repetidamente", "--max-steps", "1"]) == 0
        pursuit_id = pursuit_id_from(capsys.readouterr().out)

        resume_provider = StubLLMProvider(
            [decision_json(type="notify", message="agora sim, parei")]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: resume_provider)

        assert main(["agent", "pursue", "--resume", pursuit_id, "--max-steps", "3"]) == 0

        out = capsys.readouterr().out
        assert "passo       2/3" in out
        assert "agora sim, parei" in out

    def test_extra_guidance_reaches_the_next_prompt(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        assert main(["agent", "pursue", "veja o status", "--max-steps", "1"]) == 0
        pursuit_id = pursuit_id_from(capsys.readouterr().out)

        resume_provider = StubLLMProvider([decision_json(type="notify", message="ok")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: resume_provider)

        assert (
            main(
                [
                    "agent",
                    "pursue",
                    "--resume",
                    pursuit_id,
                    "considere também a memória disponível",
                    "--max-steps",
                    "3",
                ]
            )
            == 0
        )

        envelope = resume_provider.requests[0].messages[0].content
        assert "considere também a memória disponível" in envelope
