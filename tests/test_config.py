from pathlib import Path

import pytest

from jarvis.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isola os testes do `.env` e das variáveis de ambiente do desenvolvedor.

    `Settings` procura o `.env` relativo ao diretório atual, então basta rodar em
    um diretório temporário para garantir um ambiente previsível.
    """
    monkeypatch.chdir(tmp_path)
    for name in ("JARVIS_ENV", "JARVIS_LOG_LEVEL", "JARVIS_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_no_environment_is_set() -> None:
    settings = Settings()

    assert settings.env == "development"
    assert settings.log_level == "INFO"
    assert settings.data_dir == Path("data")


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_ENV", "test")
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("JARVIS_DATA_DIR", "custom-data")

    settings = Settings()

    assert settings.env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_dir == Path("custom-data")


def test_env_file_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("JARVIS_LOG_LEVEL=WARNING\n", encoding="utf-8")

    assert Settings().log_level == "WARNING"


def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "LOUD")

    with pytest.raises(ValueError):
        Settings()
