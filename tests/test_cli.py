import io
import json
import sqlite3
from pathlib import Path

import pytest

from jarvis import __version__, cli
from jarvis.cli import REMEMBER_SAVED_MESSAGE, main
from tests.agent_doubles import StubLLMProvider, decision_json


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Mantém o event store dos testes fora do `data/` do desenvolvedor."""
    data_dir = tmp_path / "data"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "CRITICAL")
    return data_dir


def emit(*args: str) -> int:
    return main(
        [
            "events",
            "emit",
            "--type",
            "email.received",
            "--source",
            "gmail-watcher",
            "--payload",
            '{"subject": "oi"}',
            *args,
        ]
    )


def count_rows(data_dir: Path) -> int:
    with sqlite3.connect(data_dir / "events.db") as connection:
        return int(connection.execute("SELECT count(*) FROM events").fetchone()[0])


def memory_rows(data_dir: Path) -> list[tuple[str, str, str, str | None]]:
    """O que foi gravado, lido do banco e não do que o CLI imprimiu — imprimir
    é o que estava certo antes de a gravação existir."""
    with sqlite3.connect(data_dir / "memory.db") as connection:
        rows = connection.execute(
            "SELECT content, type, origin, subject FROM memories ORDER BY sequence"
        ).fetchall()
    return [(content, type_, origin, subject) for content, type_, origin, subject in rows]


class TestBasics:
    def test_without_arguments_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main([]) == 0
        assert "usage: jarvis" in capsys.readouterr().out

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])

        assert exc_info.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_info_reports_effective_settings(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JARVIS_ENV", "test")

        assert main(["info"]) == 0

        out = capsys.readouterr().out
        assert __version__ in out
        assert "test" in out
        assert "events.db" in out
        assert "context.db" in out
        assert "memory.db" in out

    def test_events_without_action_prints_its_help(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["events"]) == 0

        out = capsys.readouterr().out
        assert "emit" in out
        assert "list" in out


class TestEmit:
    def test_records_an_event(
        self, capsys: pytest.CaptureFixture[str], isolated_data_dir: Path
    ) -> None:
        assert emit() == 0

        out = capsys.readouterr().out
        assert "status         recorded" in out
        assert count_rows(isolated_data_dir) == 1

    def test_natural_key_makes_re_emission_a_no_op(
        self, capsys: pytest.CaptureFixture[str], isolated_data_dir: Path
    ) -> None:
        assert emit("--key", "msg-1") == 0
        first = capsys.readouterr().out

        assert emit("--key", "msg-1") == 0
        second = capsys.readouterr().out

        assert "status         recorded" in first
        assert "status         duplicate" in second
        assert count_rows(isolated_data_dir) == 1

    def test_without_natural_key_each_emission_is_a_new_event(
        self, isolated_data_dir: Path
    ) -> None:
        emit()
        emit()

        assert count_rows(isolated_data_dir) == 2

    def test_accepts_a_causal_chain(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert emit("--key", "root") == 0
        root_id = capsys.readouterr().out.splitlines()[0].split()[-1]

        assert emit("--correlation-id", root_id, "--causation-id", root_id) == 0
        capsys.readouterr()

        assert main(["events", "list", "--correlation-id", root_id]) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 2

    def test_explicit_occurred_at_is_used(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert emit("--occurred-at", "2026-08-09T14:00:00+00:00") == 0

        assert (
            main(
                [
                    "events",
                    "list",
                    "--since",
                    "2026-08-09T13:00:00+00:00",
                    "--until",
                    "2026-08-09T15:00:00+00:00",
                ]
            )
            == 0
        )
        assert "email.received" in capsys.readouterr().out


class TestEmitErrors:
    def test_malformed_payload_exits_with_invalid_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            ["events", "emit", "--type", "a.b", "--source", "cli", "--payload", "{quebrado"]
        )

        assert code == 2
        captured = capsys.readouterr()
        assert "--payload" in captured.err
        assert "Traceback" not in captured.err

    def test_payload_must_be_an_object(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["events", "emit", "--type", "a.b", "--source", "cli", "--payload", "[1]"]) == 2
        assert "objeto JSON" in capsys.readouterr().err

    def test_invalid_event_type_exits_with_invalid_input(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(["events", "emit", "--type", "recebido", "--source", "cli", "--payload", "{}"])
            == 2
        )
        assert "event_type" in capsys.readouterr().err

    def test_naive_occurred_at_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert emit("--occurred-at", "2026-08-09T14:00:00") == 2
        assert "occurred_at" in capsys.readouterr().err

    def test_unparseable_occurred_at_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert emit("--occurred-at", "ontem") == 2
        assert "--occurred-at" in capsys.readouterr().err


class TestList:
    def test_reports_when_there_is_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["events", "list"]) == 0
        assert "nenhum evento" in capsys.readouterr().out

    def test_shows_recorded_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        emit("--key", "a")
        capsys.readouterr()

        assert main(["events", "list"]) == 0

        out = capsys.readouterr().out
        assert "email.received" in out
        assert "gmail-watcher" in out

    def test_filters_by_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        emit("--key", "a")
        capsys.readouterr()

        assert main(["events", "list", "--type", "calendar.meeting_starting"]) == 0
        assert "nenhum evento" in capsys.readouterr().out

    def test_honours_limit(self, capsys: pytest.CaptureFixture[str]) -> None:
        for key in ("a", "b", "c"):
            emit("--key", key)
        capsys.readouterr()

        assert main(["events", "list", "--limit", "2"]) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 2

    def test_combined_filters_are_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["events", "list", "--type", "a.b", "--correlation-id", "x"]) == 2
        assert "apenas um filtro" in capsys.readouterr().err

    def test_incomplete_window_is_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["events", "list", "--since", "2026-08-09T00:00:00+00:00"]) == 2
        assert "juntos" in capsys.readouterr().err


class TestContext:
    def test_without_action_prints_its_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["context"]) == 0

        out = capsys.readouterr().out
        assert "show" in out
        assert "snapshot" in out

    def test_show_reports_absence_without_inventing_values(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["context", "show"]) == 0

        out = capsys.readouterr().out
        rows = dict(line.split(maxsplit=1) for line in out.splitlines())

        assert "as_of" in rows
        # O Time Provider responde de verdade; o que ninguém observou fica ausente.
        assert rows["utc_offset"].split()[0].startswith(("+", "-"))
        assert rows["availability"] == "-"
        assert rows["conversation"] == "-"
        assert rows["task"] == "-"

    def test_show_distinguishes_observed_absence_from_no_data(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for event_type, payload in (
            ("user.activity_started", '{"activity": "working"}'),
            ("user.activity_ended", "{}"),
        ):
            assert (
                main(
                    [
                        "events",
                        "emit",
                        "--type",
                        event_type,
                        "--source",
                        "manual-cli",
                        "--payload",
                        payload,
                        "--key",
                        event_type,
                    ]
                )
                == 0
            )
        capsys.readouterr()

        assert main(["context", "show"]) == 0

        rows = dict(line.split(maxsplit=1) for line in capsys.readouterr().out.splitlines())
        assert rows["activity"].startswith("(nenhum)")
        assert "event:user.activity_ended" in rows["activity"]
        assert rows["conversation"] == "-"

    def test_show_reflects_events_recorded_by_another_process(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(
                [
                    "events",
                    "emit",
                    "--type",
                    "user.activity_started",
                    "--source",
                    "manual-cli",
                    "--payload",
                    '{"activity": "working"}',
                    "--key",
                    "act-1",
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert main(["context", "show"]) == 0

        out = capsys.readouterr().out
        assert "working" in out
        assert "event:user.activity_started" in out
        assert "fresh" in out

    def test_snapshot_captures_once_and_then_reports_unchanged(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["context", "snapshot"]) == 0
        first = capsys.readouterr().out

        assert main(["context", "snapshot"]) == 0
        second = capsys.readouterr().out

        assert "captured " in first
        assert "unchanged" in second

    def test_snapshot_stores_the_capture(self, isolated_data_dir: Path) -> None:
        assert main(["context", "snapshot"]) == 0

        with sqlite3.connect(isolated_data_dir / "context.db") as connection:
            rows = connection.execute("SELECT count(*) FROM context_snapshots").fetchone()[0]

        assert rows == 1

    def test_a_malformed_context_event_does_not_break_the_emit(
        self, capsys: pytest.CaptureFixture[str], isolated_data_dir: Path
    ) -> None:
        """O consumer recusa o payload; o fato continua registrado (dead-letter)."""
        code = main(
            [
                "events",
                "emit",
                "--type",
                "user.activity_started",
                "--source",
                "manual-cli",
                "--payload",
                '{"activity": "Muito Ocupado"}',
            ]
        )

        assert code == 0
        assert "status         recorded" in capsys.readouterr().out
        assert count_rows(isolated_data_dir) == 1


def add_memory(*args: str) -> int:
    return main(
        [
            "memory",
            "add",
            "--type",
            "episodic",
            "--content",
            "prefere Python para scripts",
            *args,
        ]
    )


class TestMemory:
    def test_without_action_prints_its_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["memory"]) == 0

        out = capsys.readouterr().out
        assert "add" in out
        assert "search" in out

    def test_add_creates_a_memory(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert add_memory() == 0

        out = capsys.readouterr().out
        assert "memory_id" in out
        assert "prefere Python para scripts" in out

    def test_add_stores_the_memory(self, isolated_data_dir: Path) -> None:
        assert add_memory() == 0

        with sqlite3.connect(isolated_data_dir / "memory.db") as connection:
            rows = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        assert rows == 1

    def test_get_returns_the_memory_and_records_access(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        add_memory()
        memory_id = capsys.readouterr().out.splitlines()[0].split()[-1]

        assert main(["memory", "get", memory_id]) == 0

        out = capsys.readouterr().out
        assert memory_id in out
        assert "access      1" in out

    def test_get_missing_id_is_an_infrastructure_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["memory", "get", "does-not-exist"]) == 1
        assert "não encontrada" in capsys.readouterr().err

    def test_list_shows_the_created_memory(self, capsys: pytest.CaptureFixture[str]) -> None:
        add_memory()
        capsys.readouterr()

        assert main(["memory", "list"]) == 0

        assert "prefere Python" in capsys.readouterr().out

    def test_list_reports_when_there_is_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["memory", "list"]) == 0
        assert "nenhuma memória" in capsys.readouterr().out

    def test_list_filters_by_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        add_memory()
        capsys.readouterr()

        assert main(["memory", "list", "--type", "semantic"]) == 0
        assert "nenhuma memória" in capsys.readouterr().out

    def test_search_structured_without_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        add_memory()
        capsys.readouterr()

        assert main(["memory", "search"]) == 0
        assert "prefere Python" in capsys.readouterr().out

    def test_search_semantic_with_explain(self, capsys: pytest.CaptureFixture[str]) -> None:
        add_memory()
        capsys.readouterr()

        assert main(["memory", "search", "usa para programar", "--explain"]) == 0

        out = capsys.readouterr().out
        assert "prefere Python" in out
        assert "score=" in out
        assert "semantic=" in out

    def test_forget_invalidates_without_erasing(
        self, capsys: pytest.CaptureFixture[str], isolated_data_dir: Path
    ) -> None:
        add_memory()
        memory_id = capsys.readouterr().out.splitlines()[0].split()[-1]

        assert main(["memory", "forget", memory_id, "--reason", "teste"]) == 0
        capsys.readouterr()

        assert main(["memory", "list"]) == 0
        assert "nenhuma memória" in capsys.readouterr().out

        with sqlite3.connect(isolated_data_dir / "memory.db") as connection:
            rows = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        assert rows == 1

    def test_forget_purge_removes_physically(
        self, capsys: pytest.CaptureFixture[str], isolated_data_dir: Path
    ) -> None:
        add_memory()
        memory_id = capsys.readouterr().out.splitlines()[0].split()[-1]

        assert main(["memory", "forget", memory_id, "--reason", "teste", "--purge"]) == 0

        with sqlite3.connect(isolated_data_dir / "memory.db") as connection:
            rows = connection.execute("SELECT count(*) FROM memories").fetchone()[0]
        assert rows == 0

    def test_reindex_reports_zero_when_nothing_is_incompatible(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        add_memory()
        capsys.readouterr()

        assert main(["memory", "reindex"]) == 0
        assert "reindexed 0" in capsys.readouterr().out

    def test_add_rejects_invalid_type(self, capsys: pytest.CaptureFixture[str]) -> None:
        # `choices` do argparse recusa antes mesmo de chegar ao domínio — sai
        # via SystemExit, como `--version` (test_version_flag).
        with pytest.raises(SystemExit) as exc_info:
            main(["memory", "add", "--type", "not-a-type", "--content", "x"])
        assert exc_info.value.code == 2

    def test_add_no_embedding_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert add_memory("--no-embedding") == 0
        assert "embedding   no" in capsys.readouterr().out

    def test_an_event_driven_memory_appears_in_search(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "events",
                "emit",
                "--type",
                "user.stated_preference",
                "--source",
                "manual-cli",
                "--payload",
                '{"subject": "preference.coffee", "content": "prefere café sem açúcar"}',
            ]
        )
        assert code == 0
        capsys.readouterr()

        assert main(["memory", "list", "--subject", "preference.coffee"]) == 0
        assert "prefere café" in capsys.readouterr().out


class TestAgent:
    """O composition root do agente.

    O provider é substituído por um stub em todos os testes: nenhum deles pode
    depender de credencial, rede ou quota. O caminho sem credencial é testado
    justamente **sem** a substituição.
    """

    @pytest.fixture(autouse=True)
    def stub_provider(self, monkeypatch: pytest.MonkeyPatch) -> StubLLMProvider:
        provider = StubLLMProvider([decision_json(type="notify", message="tudo em ordem")])
        monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "chave-de-teste")
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        return provider

    def test_without_action_prints_its_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["agent"]) == 0
        assert "usage: jarvis agent" in capsys.readouterr().out

    def test_ask_prints_the_decision(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["agent", "ask", "o que houve?"]) == 0

        out = capsys.readouterr().out
        assert "decision    notify" in out
        assert "tudo em ordem" in out

    def test_ask_persists_a_memory_proposal_and_confirms(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        isolated_data_dir: Path,
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={
                        "type": "semantic",
                        "content": "Davi tem 15 anos.",
                        "subject": "profile.davi.age",
                    },
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "lembre que tenho 15 anos"]) == 0

        out = capsys.readouterr().out
        assert REMEMBER_SAVED_MESSAGE in out
        assert "gravada como" in out
        assert memory_rows(isolated_data_dir) == [
            ("Davi tem 15 anos.", "semantic", "user", "profile.davi.age")
        ]

    def test_ask_saves_the_memory_carried_by_any_decision(
        self, monkeypatch: pytest.MonkeyPatch, isolated_data_dir: Path
    ) -> None:
        """A matriz de `decision.py` só proíbe `memory` em `ignore`: um `notify`
        pode trazer proposta junto, e descartá-la perderia a memória."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="notify",
                    message="anotei e respondo",
                    memory={
                        "type": "preference",
                        "content": "Davi prefere respostas curtas.",
                        "subject": "preference.answer.length",
                    },
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "seja breve comigo"]) == 0

        assert memory_rows(isolated_data_dir) == [
            (
                "Davi prefere respostas curtas.",
                "preference",
                "user",
                "preference.answer.length",
            )
        ]

    def test_ask_rejects_an_impossible_proposal_without_losing_the_turn(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        isolated_data_dir: Path,
    ) -> None:
        """`MemoryProposal` é mais permissivo que `Memory`: uma preferência sem
        `subject` passa na decisão e é recusada pelo domínio. A recusa é da
        proposta — a mensagem do agente continua valendo."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="notify",
                    message="entendi",
                    memory={"type": "preference", "content": "Davi prefere respostas curtas."},
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "seja breve comigo"]) == 0

        out = capsys.readouterr().out
        assert "proposta recusada: preference memory precisa de subject" in out
        assert "message     entendi" in out
        assert memory_rows(isolated_data_dir) == []

    def test_ask_reinforces_instead_of_duplicating(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        isolated_data_dir: Path,
    ) -> None:
        """Dizer a mesma coisa duas vezes reforça uma memória; não cria duas."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={"type": "semantic", "content": "Davi mora em Recife."},
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "moro em Recife"]) == 0
        capsys.readouterr()
        assert main(["agent", "ask", "moro em Recife"]) == 0

        assert "reforçada como" in capsys.readouterr().out
        assert len(memory_rows(isolated_data_dir)) == 1

    def test_chat_keeps_memory_confirmation_in_the_conversation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Sem a confirmação, um `remember` puro deixaria a conversa sem turno
        do assistente — e o próximo prompt sugeriria que o agente não respondeu."""
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={"type": "semantic", "content": "Davi prefere Python."},
                ),
                decision_json(type="notify", message="continuando"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setattr("sys.stdin", io.StringIO("lembre isto\ncontinue\n"))

        assert main(["agent", "chat", "--conversation-id", "c-memory"]) == 0

        assert REMEMBER_SAVED_MESSAGE in capsys.readouterr().out
        second = json.loads(provider.requests[1].messages[0].content)
        assert [turn["text"] for turn in second["conversation"]] == [
            "lembre isto",
            REMEMBER_SAVED_MESSAGE,
        ]

    def test_react_records_the_event_as_the_origin_of_the_memory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        isolated_data_dir: Path,
    ) -> None:
        """Nada disto veio do usuário: a proveniência aponta para o evento, que
        é a única referência resolvível depois."""
        monkeypatch.setenv("JARVIS_AGENT_IMPORTANCE_THRESHOLD", "0.0")
        provider = StubLLMProvider(
            [
                decision_json(
                    type="remember",
                    message=None,
                    memory={"type": "episodic", "content": "Chegou um email sobre a reunião."},
                )
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        emit("--key", "para-lembrar")
        event_id = capsys.readouterr().out.splitlines()[0].split()[1]

        assert main(["agent", "react", "--event-id", event_id]) == 0

        assert memory_rows(isolated_data_dir) == [
            ("Chegou um email sobre a reunião.", "episodic", "event", None)
        ]
        with sqlite3.connect(isolated_data_dir / "memory.db") as connection:
            references = connection.execute("SELECT provenance_reference FROM memories").fetchall()
        assert references == [(event_id,)]

    def test_ask_correlates_by_the_given_conversation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["agent", "ask", "oi", "--conversation-id", "conv-42"])

        assert "correlation conv-42" in capsys.readouterr().out

    def test_ask_reaches_the_model_with_context_and_capabilities(
        self, stub_provider: StubLLMProvider
    ) -> None:
        """A partir da Fase 5 o envelope leva o catálogo real de Skills."""
        main(["agent", "ask", "oi"])

        envelope = json.loads(stub_provider.requests[0].messages[0].content)
        assert envelope["trigger"]["text"] == "oi"
        assert envelope["constraints"]["capabilities_available"] is True
        offered = {item["name"] for item in envelope["available_capabilities"]}
        assert offered == {
            "system.status",
            "file.read",
            "file.list",
            "file.write",
            "computer.list_processes",
            "computer.focus_window",
            "computer.open_app",
            "computer.close_app",
            "computer.run_command",
        }
        # O schema viaja junto: sem ele o modelo acerta o nome e erra os campos.
        by_name = {item["name"]: item for item in envelope["available_capabilities"]}
        assert "path" in by_name["file.read"]["parameters"]

    def test_an_action_proposal_is_printed_as_unexecuted_without_execute(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Sem `--execute`, propor continua sendo só propor."""
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)

        assert main(["agent", "ask", "como está o sistema"]) == 0
        out = capsys.readouterr().out
        assert "não executada" in out
        assert "status      completed" not in out

    def test_chat_keeps_the_conversation_across_lines(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider(
            [
                decision_json(type="notify", message="primeira"),
                decision_json(type="notify", message="segunda"),
            ]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setattr("sys.stdin", io.StringIO("oi\n\ntudo bem?\n"))

        assert main(["agent", "chat", "--conversation-id", "c-1"]) == 0

        out = capsys.readouterr().out
        assert "primeira" in out
        assert "segunda" in out
        # A linha em branco não vira turno.
        assert provider.calls == 2
        second = json.loads(provider.requests[1].messages[0].content)
        assert [turn["text"] for turn in second["conversation"]] == ["oi", "primeira"]

    def test_chat_without_execute_never_runs_actions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fase 10.2: `chat` ganhou `--execute`/`--max-steps`, mas continua
        sem executar nada por padrão — mesma regra de `ask`."""
        provider = StubLLMProvider(
            [decision_json(type="act", message=None, action={"skill": "system.status"})]
        )
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        monkeypatch.setattr("sys.stdin", io.StringIO("como está o sistema?\n"))

        assert main(["agent", "chat"]) == 0

        out = capsys.readouterr().out
        assert "não executada" in out
        assert "status      completed" not in out

    def test_chat_with_execute_and_max_steps_runs_more_than_one_action(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Uma linha digitada pode disparar mais de uma ação, como em
        `agent ask --max-steps`."""
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
        monkeypatch.setattr("sys.stdin", io.StringIO("veja o status e grave uma nota\n"))

        assert main(["agent", "chat", "--execute", "--max-steps", "3"]) == 0

        out = capsys.readouterr().out
        assert out.count("status      completed") == 2

    def test_react_evaluates_a_recorded_event(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubLLMProvider([decision_json(type="ignore", message=None, reason="rotina")])
        monkeypatch.setattr(cli, "build_llm_provider", lambda settings: provider)
        emit("--key", "para-reagir")
        event_id = capsys.readouterr().out.splitlines()[0].split()[1]

        assert main(["agent", "react", "--event-id", event_id]) == 0

        out = capsys.readouterr().out
        assert "decision    ignore" in out
        assert "importance" in out, "o caminho proativo sempre reporta a triagem"

    def test_react_on_an_unknown_event_is_an_input_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["agent", "react", "--event-id", "nao-existe"]) == 2
        assert "não encontrado" in capsys.readouterr().err


def test_the_agent_without_a_credential_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sem chave, `agent ask` falha explicando o quê — e todo o resto do sistema
    continua funcionando offline. Este é o único teste de agente que **não**
    substitui o provider."""
    monkeypatch.delenv("JARVIS_GEMINI_API_KEY", raising=False)

    assert main(["agent", "ask", "oi"]) == 1
    assert "JARVIS_GEMINI_API_KEY" in capsys.readouterr().err


def test_the_rest_of_the_cli_works_without_a_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("JARVIS_GEMINI_API_KEY", raising=False)

    assert emit() == 0
    capsys.readouterr()
    assert main(["context", "show"]) == 0
    assert main(["memory", "list"]) == 0


def test_payload_is_not_printed_by_list(capsys: pytest.CaptureFixture[str]) -> None:
    main(
        [
            "events",
            "emit",
            "--type",
            "email.received",
            "--source",
            "gmail-watcher",
            "--payload",
            json.dumps({"secret": "hunter2"}),
        ]
    )
    capsys.readouterr()

    main(["events", "list"])

    assert "hunter2" not in capsys.readouterr().out
