"""Configuração da aplicação, carregada de variáveis de ambiente e de `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LLMProviderName = Literal["gemini"]


class Settings(BaseSettings):
    """Configuração do Jarvis.

    Os valores vêm de variáveis de ambiente com o prefixo `JARVIS_`, com fallback
    para o arquivo `.env` na raiz do projeto. Veja `.env.example`.

    Secrets são a mesma origem, com uma regra a mais: `SecretStr` impede que a
    credencial apareça em `repr`, log ou traceback por descuido — o valor só sai
    com `.get_secret_value()`, chamado uma única vez, no composition root
    ([ADR-0006](../../docs/adr/0006-configuration-vs-preferences-vs-state.md)).
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

    llm_provider: LLMProviderName = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.0-flash"
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 1024
    llm_temperature: float = 0.2
    # Duas tentativas, não cinco: a quota gratuita é escassa, e insistir num
    # provider indisponível gasta o que resta dela sem melhorar a resposta.
    llm_max_attempts: int = 2
    agent_importance_threshold: float = 0.45


def load_settings() -> Settings:
    """Carrega a configuração atual."""
    return Settings()
