"""Configuração da aplicação, carregada de variáveis de ambiente e de `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LLMProviderName = Literal["gemini"]
SttProviderName = Literal["groq"]
TtsProviderName = Literal["google"]
WakeStrategy = Literal["push_to_talk", "transcription"]


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
    gemini_model: str = "gemini-3.6-flash"
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 1024
    llm_temperature: float = 0.2
    # Duas tentativas, não cinco: a quota gratuita é escassa, e insistir num
    # provider indisponível gasta o que resta dela sem melhorar a resposta.
    llm_max_attempts: int = 2
    agent_importance_threshold: float = 0.45

    # --- Fase 5: política, execução e tools -------------------------------
    # Listas chegam como texto separado por vírgula e são convertidas pelo
    # composition root. Os defaults são restritivos de propósito: uma allowlist
    # vazia negaria tudo, e "esqueci de configurar" precisa falhar fechado, não
    # aberto. As três capacidades abaixo cobrem exatamente as Skills embutidas.
    policy_granted_capabilities: str = "system:read,file:read,file:write"
    policy_denied_skills: str = ""
    policy_denied_effects: str = ""
    policy_confirm_effects: str = "destructive,physical,external_communication,spend"
    policy_confirm_risk: str = "high"
    policy_deny_risk: str = "critical"

    # Uma aprovação existe para atravessar uma execução, não para ser guardada;
    # uma confirmação espera por uma pessoa, e por isso vive muito mais.
    approval_ttl_seconds: float = 60.0
    confirmation_ttl_seconds: float = 900.0

    file_skill_root: Path = Path("data/workspace")
    tool_timeout_seconds: float = 20.0
    tool_max_attempts: int = 2

    # Ausente = nenhum MCP Server. Todo o resto do sistema funciona sem.
    mcp_config_path: Path | None = None

    # --- Fase 6: voz ------------------------------------------------------
    # Três credenciais agora, todas `SecretStr`, todas lidas só no composition
    # root. Sem elas os comandos de voz falham de forma explícita; todo o resto
    # do sistema continua funcionando.
    stt_provider: SttProviderName = "groq"
    groq_api_key: SecretStr | None = None
    stt_model: str = "whisper-large-v3-turbo"
    # Vazio = deixa o provider detectar o idioma.
    stt_language: str = "pt"
    stt_timeout_seconds: float = 30.0
    stt_max_attempts: int = 2
    # Teto de transcrições por minuto no modo de wake word por transcrição. É o
    # que impede uma TV ligada de consumir a quota inteira.
    stt_wake_budget_per_minute: int = 12

    tts_provider: TtsProviderName = "google"
    google_tts_api_key: SecretStr | None = None
    tts_voice: str = "pt-BR-Neural2-B"
    tts_language: str = "pt-BR"
    tts_speaking_rate: float = 1.0
    tts_sample_rate: int = 24_000
    tts_timeout_seconds: float = 15.0
    tts_max_chars: int = 1200

    # `push_to_talk` é o default: custo zero e nenhum áudio saindo do
    # dispositivo antes de o usuário pedir.
    wake_strategy: WakeStrategy = "push_to_talk"
    wake_phrases: str = "jarvis"
    wake_max_edit_distance: int = 1

    # Vazio = dispositivo padrão do sistema operacional.
    voice_input_device: str = ""
    voice_output_device: str = ""
    voice_sample_rate: int = 16_000
    voice_barge_in: bool = True
    # Mais alto que o limiar do VAD: sem fone, o alto-falante alimenta o microfone.
    voice_barge_in_rms: float = 0.06
    # 0 desliga o expurgo automático de transcrições.
    voice_retention_days: int = 7
    # Opt-in, como o `--execute` de `agent ask`: a voz não pode ser mais
    # permissiva que o terminal só porque é mais conveniente.
    voice_execute_actions: bool = False

    vad_rms_threshold: float = 0.02
    vad_min_speech_ms: int = 300
    vad_silence_ms: int = 800
    vad_max_utterance_seconds: float = 20.0

    voice_follow_up_seconds: float = 12.0
    voice_idle_timeout_seconds: float = 45.0
    voice_max_turns: int = 40

    # --- Fase 6: painel ---------------------------------------------------
    # Loopback fixo: expor o painel na rede exigiria autenticação, que é
    # multiusuário e está fora do escopo desta fase.
    panel_host: str = "127.0.0.1"
    panel_port: int = 8765
    panel_refresh_seconds: float = 2.0
    panel_timeline_limit: int = 50
    panel_memory_limit: int = 10
    panel_open_browser: bool = False

    # --- Fase 7: proatividade ----------------------------------------------
    # Três interruptores independentes, todos default-off: sem os três,
    # `jarvis run` se comporta exatamente como antes da Fase 7 (ver
    # ADR-0029). Uma allowlist vazia nunca casa nada, mesmo critério de
    # `policy_granted_capabilities`.
    proactivity_enabled: bool = False
    proactivity_trigger_event_types: str = ""
    proactivity_importance_threshold: float = 0.6
    proactivity_execute_actions: bool = False
    # `None` desliga a janela de silêncio.
    proactivity_quiet_hours_start: int | None = None
    proactivity_quiet_hours_end: int | None = None
    proactivity_notification_cooldown_seconds: float = 900.0
    # Ausente = nenhuma regra condicional. Todo o resto do sistema funciona sem.
    proactivity_rules_path: Path | None = None

    notify_silent_mode: bool = False

    tasks_max_attempts: int = 3
    tasks_retry_base_delay_seconds: float = 30.0

    # --- Fase 8: computador ------------------------------------------------
    # Vazio = nenhum processo é "relevante" (ausência, não zero — ver
    # `ProcessActivityProvider`). Lista separada por vírgula, sem
    # distinção de maiúsculas/minúsculas.
    computer_relevant_processes: str = ""
    # Nome→argv de comandos que `computer.run_command` pode executar. Nunca
    # texto de shell livre — ver ADR-0031.
    computer_command_allowlist_path: Path | None = None


def load_settings() -> Settings:
    """Carrega a configuração atual."""
    return Settings()
