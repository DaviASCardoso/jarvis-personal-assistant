import pytest

from jarvis import __version__
from jarvis.cli import main


def test_without_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: jarvis" in capsys.readouterr().out


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_info_reports_effective_settings(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JARVIS_ENV", "test")

    assert main(["info"]) == 0

    out = capsys.readouterr().out
    assert __version__ in out
    assert "test" in out
