import json
import sqlite3
from pathlib import Path

import pytest

from jarvis import __version__
from jarvis.cli import main


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
