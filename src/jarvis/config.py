"""Configuração da aplicação, carregada de variáveis de ambiente e de `.env`."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Configuração do Jarvis.

    Os valores vêm de variáveis de ambiente com o prefixo `JARVIS_`, com fallback
    para o arquivo `.env` na raiz do projeto. Veja `.env.example`.
    """

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = "development"
    log_level: LogLevel = "INFO"
    data_dir: Path = Path("data")


def load_settings() -> Settings:
    """Carrega a configuração atual."""
    return Settings()
