"""Os comandos da Fase 5 no CLI: `skills`, `tools`, `action` e `agent --execute`.

Arquivo separado de `test_cli.py` por tamanho, não por natureza — as fixtures são
as mesmas e o alvo continua sendo o composition root. É aqui que a cadeia inteira
(registry → política → skill → router → backend local → eventos) roda de verdade,
contra o sistema de arquivos, sem nenhum double.
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


def workspace_file(tmp_path: Path, name: str) -> Path:
    return tmp_path / "data" / "workspace" / name


def execution_id_from(out: str) -> str:
    return next(line.split()[1] for line in out.splitlines() if line.startswith("execution "))


class TestSkillsCommand:
    def test_listing_shows_the_catalog_with_its_risk_metadata(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["skills", "list"]) == 0

        out = capsys.readouterr().out
        assert "file.write" in out
        assert "risco=medium" in out
        assert "capacidades=file:write" in out
        assert "tools=local:fs.write_text" in out

    def test_without_a_subcommand_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["skills"]) == 0
        assert "usage: jarvis skills" in capsys.readouterr().out


class TestToolsCommand:
    def test_listing_shows_the_local_backend_and_its_tools(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["tools", "list"]) == 0

        out = capsys.readouterr().out
        assert "backend local" in out
        assert "local:fs.read_text" in out

    def test_schemas_are_shown_on_demand(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["tools", "list", "--schemas"]) == 0

        assert "path: string (obrigatório)" in capsys.readouterr().out


class TestInfo:
    def test_it_reports_the_effective_policy(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Política efetiva não deve ser adivinhada."""
        assert main(["info"]) == 0

        out = capsys.readouterr().out
        assert "policy" in out
        assert "confirm_risk>=high" in out
        assert "action_store" in out


class TestActionRun:
    def test_an_allowed_action_runs_end_to_end(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["action", "run", "--skill", "system.status"]) == 0

        out = capsys.readouterr().out
        assert "status      completed" in out
        assert "tools       local:system.info" in out

    def test_writing_a_file_actually_writes_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "action",
                "run",
                "--skill",
                "file.write",
                "--parameters",
                '{"path": "nota.txt", "content": "ola"}',
            ]
        )

        assert code == 0
        assert "status      completed" in capsys.readouterr().out
        assert workspace_file(tmp_path, "nota.txt").read_text(encoding="utf-8") == "ola"

    def test_reading_back_returns_the_content(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(
            [
                "action",
                "run",
                "--skill",
                "file.write",
                "--parameters",
                '{"path": "nota.txt", "content": "ola"}',
            ]
        )
        capsys.readouterr()

        assert (
            main(["action", "run", "--skill", "file.read", "--parameters", '{"path": "nota.txt"}'])
            == 0
        )

        assert '"content": "ola"' in capsys.readouterr().out

    def test_a_denied_skill_is_reported_with_a_success_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Negar não é crash: o usuário precisa da explicação, não de um traceback."""
        monkeypatch.setenv("JARVIS_POLICY_DENIED_SKILLS", "system.status")

        assert main(["action", "run", "--skill", "system.status"]) == 0

        out = capsys.readouterr().out
        assert "status      denied" in out
        assert "skill_denylisted" in out

    def test_an_unknown_skill_is_denied(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["action", "run", "--skill", "inventada.pelo.modelo"]) == 0

        assert "skill_not_registered" in capsys.readouterr().out

    def test_bad_parameters_are_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["action", "run", "--skill", "file.read", "--parameters", "{}"]) == 0

        assert "invalid_parameters" in capsys.readouterr().out

    def test_a_path_outside_the_workspace_never_writes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "action",
                "run",
                "--skill",
                "file.write",
                "--parameters",
                '{"path": "../invadido.txt", "content": "x"}',
            ]
        )

        assert code == 0
        assert "status      failed" in capsys.readouterr().out
        assert not (tmp_path / "data" / "invadido.txt").exists()

    def test_a_bad_policy_configuration_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Configuração de segurança ignorada em silêncio é pior que ausente."""
        monkeypatch.setenv("JARVIS_POLICY_CONFIRM_RISK", "assustador")

        assert main(["action", "run", "--skill", "system.status"]) == 2

        assert "nível de risco desconhecido" in capsys.readouterr().err


class TestConfirmationFlow:
    @pytest.fixture(autouse=True)
    def confirm_medium_risk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_POLICY_CONFIRM_RISK", "medium")

    def write(self, content: str = "ola") -> int:
        return main(
            [
                "action",
                "run",
                "--skill",
                "file.write",
                "--parameters",
                '{"path": "nota.txt", "content": "' + content + '"}',
            ]
        )

    def test_the_action_waits_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self.write() == 0

        assert "status      awaiting_confirmation" in capsys.readouterr().out
        assert not workspace_file(tmp_path, "nota.txt").exists()

    def test_pending_lists_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        self.write()
        execution_id = execution_id_from(capsys.readouterr().out)

        assert main(["action", "pending"]) == 0

        assert execution_id in capsys.readouterr().out

    def test_confirming_releases_the_execution(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.write()
        execution_id = execution_id_from(capsys.readouterr().out)

        assert main(["action", "confirm", execution_id]) == 0

        assert "status      completed" in capsys.readouterr().out
        assert workspace_file(tmp_path, "nota.txt").read_text(encoding="utf-8") == "ola"

    def test_rejecting_never_executes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.write()
        execution_id = execution_id_from(capsys.readouterr().out)

        assert main(["action", "reject", execution_id, "--reason", "mudei de ideia"]) == 0
        assert "rejeitada" in capsys.readouterr().out
        assert not workspace_file(tmp_path, "nota.txt").exists()

        assert main(["action", "show", execution_id]) == 0
        assert "status      rejected" in capsys.readouterr().out

    def test_the_answer_is_recorded_as_an_event(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Contracts §10.2: a resposta do usuário chega ao sistema como evento."""
        self.write()
        execution_id = execution_id_from(capsys.readouterr().out)
        main(["action", "confirm", execution_id])
        capsys.readouterr()

        assert main(["events", "list", "--type", "action.confirmation_granted"]) == 0

        assert "action.confirmation_granted" in capsys.readouterr().out

    def test_both_policy_evaluations_survive_in_the_trail(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A que pediu confirmação e a que autorizou — a segunda é a que importa.

        Sem discriminador por decisão, os dois `policy.evaluated` colidiriam no
        mesmo `event_id` e a trilha guardaria só o primeiro.
        """
        main(
            [
                "action",
                "run",
                "--skill",
                "file.write",
                "--parameters",
                '{"path": "nota.txt", "content": "ola"}',
                "--correlation-id",
                "corr-conf",
            ]
        )
        execution_id = execution_id_from(capsys.readouterr().out)
        main(["action", "confirm", execution_id])
        capsys.readouterr()

        main(["events", "list", "--correlation-id", "corr-conf"])

        out = capsys.readouterr().out
        assert out.count("policy.evaluated") == 2
        assert "action.confirmation_requested" in out
        assert "action.completed" in out

    def test_show_reports_the_fingerprint_not_the_parameters(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.write(content="consulta-com-a-dra-marina")
        execution_id = execution_id_from(capsys.readouterr().out)

        assert main(["action", "show", execution_id]) == 0

        shown = capsys.readouterr().out
        assert "fingerprint" in shown
        assert "consulta-com-a-dra-marina" not in shown

    def test_an_unknown_execution_is_an_input_error(self) -> None:
        assert main(["action", "show", "nao-existe"]) == 2
        assert main(["action", "confirm", "nao-existe"]) == 2


class TestAuditTrail:
    def test_the_whole_chain_is_queryable_by_correlation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["action", "run", "--skill", "system.status", "--correlation-id", "corr-42"])
        capsys.readouterr()

        assert main(["events", "list", "--correlation-id", "corr-42"]) == 0

        out = capsys.readouterr().out
        for expected in (
            "action.requested",
            "policy.evaluated",
            "tool.execution_completed",
            "action.completed",
        ):
            assert expected in out

    def test_a_denial_is_audited_too(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_DENIED_SKILLS", "system.status")
        main(["action", "run", "--skill", "system.status", "--correlation-id", "corr-9"])
        capsys.readouterr()

        main(["events", "list", "--correlation-id", "corr-9"])

        out = capsys.readouterr().out
        assert "policy.evaluated" in out
        assert "action.failed" in out
        assert "tool.execution_completed" not in out


class TestAgentExecute:
    def test_execute_submits_the_proposal_to_the_policy_engine(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "como está o sistema", "--execute"]) == 0

        assert "status      completed" in capsys.readouterr().out

    def test_a_submitted_proposal_is_not_announced_as_unexecuted(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A dica de `--execute` é resquício da Fase 4: sai quando há submissão.

        Imprimi-la junto do desfecho diria, no mesmo bloco, que a ação não foi
        executada e que ela terminou — a saída contradiria a si mesma.
        """
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "como está o sistema", "--execute"]) == 0

        out = capsys.readouterr().out
        assert "não executada" not in out
        assert "status      completed" in out

    def test_without_execute_nothing_runs(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "como está o sistema"]) == 0

        out = capsys.readouterr().out
        assert "não executada" in out
        assert "status      completed" not in out

    def test_a_denied_proposal_gets_a_natural_language_explanation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("JARVIS_POLICY_DENIED_SKILLS", "system.status")
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "system.status"}),
                decision_json(type="notify", message="a política bloqueou essa ação"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "status", "--execute"]) == 0

        out = capsys.readouterr().out
        assert "status      denied" in out
        assert "a política bloqueou essa ação" in out
        assert len(provider.requests) == 2

    def test_a_successful_action_does_not_pay_for_a_second_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A quota é escassa; reformular o que já foi dito é desperdício."""
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        main(["agent", "ask", "status", "--execute"])

        assert len(provider.requests) == 1

    def test_an_invented_skill_is_denied_not_executed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Prompt injection continua possível; virar execução, não."""
        provider = StubLLMProvider(
            [
                decision_json(type="act", message=None, action={"skill": "apagar.tudo"}),
                decision_json(type="notify", message="não conheço essa capacidade"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "apague tudo", "--execute"]) == 0

        assert "skill_not_registered" in capsys.readouterr().out
