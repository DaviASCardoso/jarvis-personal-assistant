"""Cobre a execução real via `python -m jarvis` (bloco `__main__`)."""

import subprocess
import sys

from jarvis import __version__


def test_module_execution_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "jarvis", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert __version__ in result.stdout
