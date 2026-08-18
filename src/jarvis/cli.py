"""Ponto de entrada da linha de comando e composition root.

Este é o único módulo autorizado a conhecer Core, Infrastructure e Interfaces ao
mesmo tempo (ADR-0001): ele carrega a configuração, instancia os adapters concretos
(`SqliteEventStore`, `LoggingEventConsumer`, os Context Providers, o repositório de
snapshots, o repositório de memórias, o `EmbeddingProvider`, o `GeminiLLMProvider`)
e os injeta nos serviços do Core (`EventBus`, `EventPublisher`, `ContextAggregator`,
`ContextEngine`, `MemoryManager`, `AgentRuntime`). Nenhum módulo do Core importa
`jarvis.events.adapters`, `jarvis.context.adapters`, `jarvis.memory.adapters` nem
`jarvis.agent.adapters`.

É também o único módulo que lê a credencial do LLM (`build_llm_provider`): o
Agent Runtime recebe um provider já construído e nunca vê `Settings`.
"""

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from jarvis import __version__
from jarvis.agent import (
    ActionResultSummary,
    AgentInput,
    AgentRuntime,
    AgentTurn,
    Capability,
    Conversation,
    ConversationTurn,
    Decision,
    EventSummary,
    EventTrigger,
    GenerationDefaults,
    InvalidDecisionError,
    InvalidLLMRequestError,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRetryPolicy,
    PromptTooLargeError,
    Role,
    UserMessage,
)
from jarvis.agent.adapters.gemini import GeminiLLMProvider
from jarvis.audit import AuditKind
from jarvis.config import LogLevel, Settings, load_settings
from jarvis.context import (
    ContextAggregator,
    ContextEngine,
    ContextSnapshotError,
    CurrentContext,
    InvalidContextError,
    iter_fields,
)
from jarvis.context.adapters.device_provider import LocalDeviceProvider
from jarvis.context.adapters.process_activity_provider import ProcessActivityProvider
from jarvis.context.adapters.resource_usage_provider import ResourceUsageProvider
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.adapters.time_provider import SystemTimeProvider
from jarvis.context.adapters.window_activity_provider import WindowActivityProvider
from jarvis.context.consumer import CONTEXT_EVENT_TYPES
from jarvis.decisions import (
    DECISION_RECORDED,
    DecisionLogError,
    DecisionRecord,
    decision_event,
    project_decisions,
)
from jarvis.events import (
    Event,
    EventBus,
    EventPublisher,
    EventStoreError,
    InvalidEventError,
    JsonValue,
    RecordedEvent,
    deterministic_event_id,
    new_event_id,
)
from jarvis.events.adapters.logging_consumer import LoggingEventConsumer
from jarvis.events.adapters.sqlite_store import SqliteEventStore
from jarvis.execution import (
    ActionEventConsumer,
    ActionExecutor,
    ActionRepositoryError,
    ActionRequest,
    Actor,
    ExecutionError,
    ExecutionOutcome,
    ExecutionStatus,
    PendingAction,
    confirmation_event,
)
from jarvis.execution.adapters.event_audit import EventAuditLog
from jarvis.execution.adapters.sqlite_actions import SqliteActionRepository
from jarvis.execution.events import CONFIRMATION_EVENT_TYPES
from jarvis.interface import (
    InterfaceError,
    LiveState,
    ObservabilityService,
    PanelSnapshot,
    TurnTrace,
    VoiceStatusView,
)
from jarvis.interface.adapters.http_panel import PanelServer, open_browser
from jarvis.memory import (
    InvalidMemoryError,
    MemoryCriteria,
    MemoryManager,
    MemoryOrigin,
    MemoryRepositoryError,
    MemoryType,
    Provenance,
    RetrievalQuery,
    StoredMemory,
)
from jarvis.memory.adapters.context_bridge import context_to_query
from jarvis.memory.adapters.event_consumer import MEMORY_EVENT_TYPES, MemoryEventConsumer
from jarvis.memory.adapters.hashing_embeddings import HashingEmbeddingProvider
from jarvis.memory.adapters.sqlite_repository import SqliteMemoryRepository
from jarvis.notify import Notification, NotificationManager, NotificationPriority, NotifyError
from jarvis.notify.adapters.console import ConsoleNotificationChannel
from jarvis.notify.adapters.voice import VoiceNotificationChannel
from jarvis.notify.ports import NotificationChannel
from jarvis.policy import (
    InvalidPolicyVocabularyError,
    PolicyEngine,
    PolicyError,
    PolicyRuleSet,
    parse_capabilities,
    parse_effects,
    parse_names,
    parse_risk,
)
from jarvis.proactivity import (
    ConditionalTriggerConsumer,
    ConditionEngine,
    InterruptionPolicy,
    InterruptionSettings,
    ProactivityError,
    TriggerEngine,
    TriggerEventConsumer,
    TriggerRule,
)
from jarvis.proactivity.adapters.memory_bridge import MemoryPresenceBridge
from jarvis.proactivity.adapters.rules_config import load_conditional_rules
from jarvis.pursuits import (
    PursuitError,
    PursuitRepositoryError,
    PursuitState,
    PursuitStatus,
    UnknownPursuitError,
    new_pursuit_id,
)
from jarvis.pursuits.adapters.sqlite_pursuits import SqlitePursuitRepository
from jarvis.skills import SkillError, SkillRegistry
from jarvis.skills.builtin import register_builtin_skills
from jarvis.tasks import BackgroundTask, TaskError, TaskManager, TaskRepositoryError, TaskStatus
from jarvis.tasks.adapters.sqlite_tasks import SqliteTaskRepository
from jarvis.tools import (
    ToolError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolNotPermittedError,
    ToolRegistry,
    ToolRetryPolicy,
    ToolRouter,
)
from jarvis.tools.adapters.computer_backend import ComputerToolBackend, load_command_allowlist
from jarvis.tools.adapters.local_backend import LocalToolBackend
from jarvis.tools.adapters.mcp_client import McpToolBackend
from jarvis.tools.adapters.mcp_config import load_mcp_config
from jarvis.tools.errors import ToolConfigurationError
from jarvis.voice import (
    AgentReply,
    AudioDeviceError,
    AudioError,
    AudioFormat,
    AudioSink,
    AudioSource,
    InvalidVoiceInputError,
    SpeechToText,
    SpeechToTextError,
    SttAuthenticationError,
    TextToSpeechError,
    TtsAuthenticationError,
    VoiceError,
    VoiceLoop,
    VoiceRepositoryError,
    VoiceSession,
    VoiceSettings,
    VoiceState,
    VoiceStatus,
    WakeWordDetector,
    parse_phrases,
)
from jarvis.voice.adapters.google_tts import GoogleCloudTextToSpeech
from jarvis.voice.adapters.groq_stt import GroqSpeechToText
from jarvis.voice.adapters.retry import RetryPolicy
from jarvis.voice.adapters.sqlite_sessions import SqliteVoiceSessionRepository
from jarvis.voice.adapters.wake_push_to_talk import PushToTalkWakeWord, StdinTrigger
from jarvis.voice.adapters.wake_transcription import TranscriptionWakeWord
from jarvis.voice.adapters.wave_io import decode_wav, encode_wav
from jarvis.voice.session import SessionSettings
from jarvis.voice.vad import VadSettings

EXIT_OK = 0
EXIT_INFRASTRUCTURE_ERROR = 1
EXIT_INVALID_INPUT = 2

DEFAULT_LIST_LIMIT = 20
DEFAULT_RECENT_EVENTS = 10

# Duas ausências distintas, e a distinção precisa aparecer: `-` é "nunca observado",
# `(nenhum)` é "alguém observou que não há".
ABSENT = "-"
OBSERVED_ABSENCE = "(nenhum)"

# Um `remember` puro não traz `message`: a decisão é "guardar isto", não "dizer
# algo". Sem uma frase de confirmação o usuário veria a proposta e nenhum sinal
# de que ela virou memória, e a conversa ficaria sem turno do assistente.
REMEMBER_SAVED_MESSAGE = "Anotado."

# Sem `reference` de propósito. Não há artefato durável para apontar: decisões
# só viram trilha consultável na 7.4 e conversas só são persistidas na 6.4, e um
# ponteiro que não resolve ainda custaria a consolidação — `find_duplicate` exige
# a mesma `reference`, então cada repetição da mesma afirmação viraria linha
# nova em vez de reforço. `USER` porque a afirmação é do usuário: o agente
# apenas a extraiu da mensagem.
USER_ASSERTION = Provenance(origin=MemoryOrigin.USER)

# Os dois únicos eventos que a voz produz, e nenhum deles carrega uma palavra do
# que foi dito. `source` é do composition root porque é ele quem publica — a
# camada de voz não conhece o Event System.
VOICE_SOURCE = "jarvis-voice"
VOICE_SESSION_STARTED = "voice.session_started"
VOICE_SESSION_ENDED = "voice.session_ended"
VOICE_EVENT_TYPES = frozenset({VOICE_SESSION_STARTED, VOICE_SESSION_ENDED})

# Fase 7.4: quem publica um `agent.decision_recorded` é sempre o composition
# root — `jarvis.decisions` recebe primitivos, nunca `Decision`/`AgentTurn`
# (ver docstring de `jarvis/decisions/events.py`).
DECISION_SOURCE = "jarvis-agent"


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    """O desfecho de aplicar a proposta de memória de um turno.

    Três estados, e os três precisam aparecer distintos na saída: nada proposto
    (ambos `None`), gravada/reforçada (`stored`), ou recusada pelo domínio
    (`rejected`) — "não gravei" e "não havia o que gravar" não são a mesma coisa.
    """

    stored: StoredMemory | None = None
    rejected: str | None = None


def configure_logging(level: LogLevel) -> None:
    """Configura o logging da aplicação uma única vez, aqui na borda.

    Os componentes só chamam `logging.getLogger(__name__)`; quem decide formato e
    destino é o entry point, não o Core.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )


def event_store_path(settings: Settings) -> Path:
    return settings.data_dir / "events.db"


def context_store_path(settings: Settings) -> Path:
    """Banco próprio: Context Engine e Event System versionam schema à parte."""
    return settings.data_dir / "context.db"


def build_context_engine(
    settings: Settings, snapshots: SqliteContextSnapshotRepository
) -> ContextEngine:
    """Monta o Context Engine com os providers que têm dado local de verdade.

    Activity, Calendar e Location não entram: exigiriam integração externa que
    esta fase não implementa, e um provider de valor declarado aqui pareceria
    funcionalidade pronta sem ser. Os três providers de computador (Fase 8.1)
    entram sempre — cada um degrada para ausência sozinho quando o sistema
    operacional não oferece o dado (ver `context/adapters/*_provider.py`).
    """
    aggregator = ContextAggregator(
        providers=[
            SystemTimeProvider(),
            LocalDeviceProvider(),
            WindowActivityProvider(),
            ResourceUsageProvider(),
            ProcessActivityProvider(
                relevant_process_names=frozenset(_parse_list(settings.computer_relevant_processes))
            ),
        ]
    )
    return ContextEngine(aggregator=aggregator, snapshots=snapshots)


def memory_store_path(settings: Settings) -> Path:
    """Banco próprio: três componentes, três bancos, cada um versionando
    schema à parte."""
    return settings.data_dir / "memory.db"


def build_memory_manager(memories: SqliteMemoryRepository) -> MemoryManager:
    """`HashingEmbeddingProvider`: local e determinístico, para que o Memory
    System funcione sem nenhum LLM configurado (`PHASE-3.md §17`).

    Continua local na Fase 4 de propósito: `EmbeddingProvider` é port separado
    de `LLMProvider` (ADR-0002), e trocá-lo por um serviço de nuvem tornaria
    `jarvis memory add` dependente de rede e quota, além de exigir reindexar
    tudo que já foi gravado. Um adapter de vendor entra quando houver
    necessidade medida de qualidade semântica."""
    return MemoryManager(repository=memories, embeddings=HashingEmbeddingProvider())


def build_llm_provider(settings: Settings) -> GeminiLLMProvider:
    """Único lugar que lê a credencial. O runtime recebe o provider já pronto e
    nunca vê `Settings` — é o que impede um secret de chegar ao prompt."""
    if settings.gemini_api_key is None:
        raise LLMAuthenticationError("JARVIS_GEMINI_API_KEY não configurada; veja .env.example")
    return GeminiLLMProvider(
        api_key=settings.gemini_api_key.get_secret_value(), model=settings.gemini_model
    )


def build_agent_runtime(
    settings: Settings,
    *,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
) -> AgentRuntime:
    return AgentRuntime(
        llm=build_llm_provider(settings),
        context_reader=context.current,
        memory=build_memory_manager(memories),
        importance_threshold=settings.agent_importance_threshold,
        retry=LLMRetryPolicy(max_attempts=settings.llm_max_attempts),
        generation=GenerationDefaults(
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    )


def action_store_path(settings: Settings) -> Path:
    """Quarto banco: estado operacional das execuções, separado dos outros três."""
    return settings.data_dir / "actions.db"


def build_skill_registry() -> SkillRegistry:
    """Registro explícito das Skills embutidas.

    Sem varredura de módulos: descobrir capacidades importando código arbitrário
    é superfície de ataque e efeito colateral em import (`PHASE-5.md §26`).
    """
    return register_builtin_skills(SkillRegistry())


def build_tool_registry(settings: Settings) -> ToolRegistry:
    """Backends locais (`file`/`system` e `computer`) sempre; MCP Servers só se
    houver `mcp.json`.

    A descoberta acontece aqui, na borda. Um servidor indisponível não derruba o
    processo — vira um backend degradado, visível em `jarvis tools list`, e as
    Skills que dependiam dele passam a ser negadas pelo Policy Engine com
    `required_tool_unavailable` em vez de falhar no meio da execução.
    """
    registry = ToolRegistry()
    registry.register_backend(LocalToolBackend(root=settings.file_skill_root))
    command_allowlist = (
        load_command_allowlist(settings.computer_command_allowlist_path)
        if settings.computer_command_allowlist_path is not None
        else {}
    )
    registry.register_backend(ComputerToolBackend(command_allowlist=command_allowlist))
    if settings.mcp_config_path is not None:
        for spec in load_mcp_config(settings.mcp_config_path):
            if spec.enabled:
                registry.register_backend(McpToolBackend(spec))
    registry.refresh()
    return registry


def build_policy_rules(settings: Settings) -> PolicyRuleSet:
    return PolicyRuleSet(
        granted_capabilities=parse_capabilities(settings.policy_granted_capabilities),
        denied_skills=parse_names(settings.policy_denied_skills),
        denied_effects=parse_effects(settings.policy_denied_effects),
        confirm_effects=parse_effects(settings.policy_confirm_effects),
        confirm_risk_at_or_above=parse_risk(settings.policy_confirm_risk),
        deny_risk_at_or_above=parse_risk(settings.policy_deny_risk),
    )


def build_policy_engine(settings: Settings) -> PolicyEngine:
    return PolicyEngine(
        rules=build_policy_rules(settings), approval_ttl_seconds=settings.approval_ttl_seconds
    )


def build_action_executor(
    settings: Settings,
    *,
    store: SqliteEventStore,
    actions: SqliteActionRepository,
    tools: ToolRegistry,
    skills: SkillRegistry,
) -> ActionExecutor:
    """Monta a cadeia de execução inteira. Único lugar que conhece os quatro pacotes."""
    audit = EventAuditLog(_build_publisher(store))
    return ActionExecutor(
        skills=skills,
        tools=tools,
        router=ToolRouter(
            registry=tools,
            audit=audit,
            default_timeout_seconds=settings.tool_timeout_seconds,
            retry=ToolRetryPolicy(max_attempts=settings.tool_max_attempts),
        ),
        policy=build_policy_engine(settings),
        repository=actions,
        audit=audit,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        tool_timeout_seconds=settings.tool_timeout_seconds,
    )


def _build_publisher(
    store: SqliteEventStore,
    *,
    bus: EventBus | None = None,
    confirmations: ActionEventConsumer | None = None,
) -> EventPublisher:
    """`bus=None` (o default de todo comando de tiro único) constrói um bus
    novo e descartável — comportamento inalterado desde a Fase 5.

    `bus` explícito é o que a Fase 7 usa em `jarvis run`: um único bus vive
    pelo processo inteiro, para que eventos de sessão, decisão e confirmação
    publicados durante a mesma execução alcancem o Trigger Engine e o
    Conditional Trigger (`_build_proactivity`), que se inscrevem nele uma
    única vez. Quando `bus` é passado, `confirmations` é ignorado: quem
    montou o bus compartilhado já assinou o que precisava.
    """
    if bus is not None:
        return EventPublisher(store=store, bus=bus)
    fresh = EventBus()
    fresh.subscribe(LoggingEventConsumer())
    if confirmations is not None:
        fresh.subscribe(confirmations, event_types=CONFIRMATION_EVENT_TYPES)
    return EventPublisher(store=store, bus=fresh)


def build_trigger_engine(settings: Settings) -> TriggerEngine:
    """Allowlist vazia (padrão) nunca casa nada — autonomia é opt-in."""
    event_types = _parse_list(settings.proactivity_trigger_event_types)
    if not event_types:
        return TriggerEngine()
    return TriggerEngine([TriggerRule(trigger_id="configured", event_types=frozenset(event_types))])


def build_interruption_policy(settings: Settings) -> InterruptionPolicy:
    return InterruptionPolicy(
        InterruptionSettings(
            importance_threshold=settings.proactivity_importance_threshold,
            quiet_hours_start=settings.proactivity_quiet_hours_start,
            quiet_hours_end=settings.proactivity_quiet_hours_end,
            cooldown_seconds=settings.proactivity_notification_cooldown_seconds,
        )
    )


def build_condition_engine(settings: Settings) -> ConditionEngine:
    """Ausência de `proactivity_rules_path` é "nenhuma regra", não erro."""
    if settings.proactivity_rules_path is None:
        return ConditionEngine()
    return ConditionEngine(load_conditional_rules(settings.proactivity_rules_path))


def build_task_manager(settings: Settings, *, repository: SqliteTaskRepository) -> TaskManager:
    return TaskManager(
        repository=repository,
        max_attempts=settings.tasks_max_attempts,
        retry_base_delay_seconds=settings.tasks_retry_base_delay_seconds,
    )


def build_notification_manager(
    settings: Settings, *, voice_channel: NotificationChannel | None = None
) -> NotificationManager:
    """Console sempre presente (funciona sem hardware de áudio); voz só quando
    o composition root souber que há um canal de voz utilizável agora."""
    channels: list[NotificationChannel] = []
    if voice_channel is not None:
        channels.append(voice_channel)
    channels.append(ConsoleNotificationChannel())
    return NotificationManager(
        channels=channels,
        interruption_policy=build_interruption_policy(settings),
        silent_mode=settings.notify_silent_mode,
    )


def capabilities_from(skills: SkillRegistry) -> tuple[Capability, ...]:
    """Traduz descritores de Skill em capacidades para o envelope do LLM.

    A tradução acontece **aqui**, e não no registry: é o que mantém
    `jarvis.skills` sem dependência de `jarvis.agent`, e o agente sem dependência
    de `jarvis.skills`.
    """
    return tuple(
        Capability(
            name=descriptor.name,
            summary=descriptor.summary,
            parameters=descriptor.parameters.describe(),
        )
        for descriptor in skills.list()
    )


def voice_store_path(settings: Settings) -> Path:
    """Quinto banco: transcrições de voz, estado operacional com retenção."""
    return settings.data_dir / "voice.db"


def task_store_path(settings: Settings) -> Path:
    """Sexto banco: tarefas em background, estado operacional próprio (Fase 7.5)."""
    return settings.data_dir / "tasks.db"


def pursuit_store_path(settings: Settings) -> Path:
    """Sétimo banco: checkpoints do Goal Pursuit Loop, estado operacional
    próprio, fora do Event Store (Fase 10.5, mesma cautela do ADR-0014)."""
    return settings.data_dir / "pursuits.db"


def build_stt(settings: Settings) -> GroqSpeechToText:
    """Único lugar que lê a credencial da Groq."""
    if settings.groq_api_key is None:
        raise SttAuthenticationError("JARVIS_GROQ_API_KEY não configurada; veja .env.example")
    return GroqSpeechToText(
        api_key=settings.groq_api_key.get_secret_value(),
        model=settings.stt_model,
        retry=RetryPolicy(max_attempts=settings.stt_max_attempts),
    )


def build_tts(settings: Settings) -> GoogleCloudTextToSpeech:
    """Único lugar que lê a credencial do Google Cloud TTS."""
    if settings.google_tts_api_key is None:
        raise TtsAuthenticationError("JARVIS_GOOGLE_TTS_API_KEY não configurada; veja .env.example")
    return GoogleCloudTextToSpeech(
        api_key=settings.google_tts_api_key.get_secret_value(),
        voice=settings.tts_voice,
        language=settings.tts_language,
        speaking_rate=settings.tts_speaking_rate,
        sample_rate=settings.tts_sample_rate,
        max_chars=settings.tts_max_chars,
    )


def build_audio_io(settings: Settings) -> tuple[AudioSource, AudioSink]:
    """Microfone e alto-falante.

    O import é **tardio** de propósito: `sounddevice` vive no extra `voice`
    (ADR-0020), e quem só usa o CLI de texto não deve descobrir isso por
    `ImportError`. A mensagem traz a instrução de instalação.
    """
    try:
        from jarvis.voice.adapters.sounddevice_audio import (
            MicrophoneSource,
            SpeakerSink,
            resolve_device,
        )
    except ImportError as error:
        raise AudioDeviceError(
            "áudio indisponível: instale o extra com `uv sync --extra voice`"
        ) from error

    audio_format = AudioFormat(sample_rate=settings.voice_sample_rate)
    source = MicrophoneSource(
        audio_format=audio_format, device=resolve_device(settings.voice_input_device)
    )
    sink = SpeakerSink(
        audio_format=audio_format, device=resolve_device(settings.voice_output_device)
    )
    return source, sink


def build_wake_detector(
    settings: Settings, *, stt: SpeechToText
) -> tuple[WakeWordDetector, StdinTrigger | None]:
    """Push-to-talk por default: custo zero e nenhum áudio na nuvem sem pedido."""
    phrases = parse_phrases(
        settings.wake_phrases, max_edit_distance=settings.wake_max_edit_distance
    )
    if settings.wake_strategy == "transcription":
        return (
            TranscriptionWakeWord(
                stt=stt,
                phrases=phrases,
                vad=build_vad_settings(settings),
                language=settings.stt_language or None,
                timeout_seconds=settings.stt_timeout_seconds,
                budget_per_minute=settings.stt_wake_budget_per_minute,
                monotonic=time.monotonic,
            ),
            None,
        )

    trigger = StdinTrigger()
    trigger.start()
    return PushToTalkWakeWord(trigger=trigger.take, stop=trigger.stop), trigger


def build_vad_settings(settings: Settings) -> VadSettings:
    return VadSettings(
        rms_threshold=settings.vad_rms_threshold,
        min_speech_ms=settings.vad_min_speech_ms,
        silence_ms=settings.vad_silence_ms,
        max_utterance_seconds=settings.vad_max_utterance_seconds,
    )


def build_voice_settings(settings: Settings) -> VoiceSettings:
    return VoiceSettings(
        vad=build_vad_settings(settings),
        session=SessionSettings(
            follow_up_seconds=settings.voice_follow_up_seconds,
            idle_timeout_seconds=settings.voice_idle_timeout_seconds,
            max_turns=settings.voice_max_turns,
        ),
        language=settings.stt_language or None,
        stt_timeout_seconds=settings.stt_timeout_seconds,
        tts_timeout_seconds=settings.tts_timeout_seconds,
        barge_in=settings.voice_barge_in,
        barge_in_rms=settings.voice_barge_in_rms,
    )


def voice_session_event(session: VoiceSession, *, started: bool) -> Event:
    """A sessão de voz como fato, **sem uma palavra do que foi dito**.

    Os construtores vivem aqui e não em `jarvis.voice` porque aquele pacote não
    conhece o Event System — é o que mantém a camada de voz sem caminho até
    persistência. Quem publica é o composition root, como manda o plano da fase.

    O payload carrega identidade e contagem. Transcrição é estado operacional
    apagável em `voice.db`; um evento é para sempre
    ([ADR-0025](../../docs/adr/0025-voice-transcripts-as-operational-state.md)).
    """
    event_type = VOICE_SESSION_STARTED if started else VOICE_SESSION_ENDED
    payload: dict[str, JsonValue] = {"session_id": session.session_id}
    if not started:
        payload["turn_count"] = session.turn_count
        payload["reason"] = session.ended_reason
        if session.duration_ms is not None:
            payload["duration_ms"] = round(session.duration_ms, 1)

    return Event(
        event_id=deterministic_event_id(
            source=VOICE_SOURCE, natural_key=f"{session.session_id}:{event_type}"
        ),
        event_type=event_type,
        source=VOICE_SOURCE,
        occurred_at=session.ended_at
        if not started and session.ended_at is not None
        else session.started_at,
        payload=payload,
        correlation_id=session.correlation_id,
    )


class RuntimeConversationalAgent:
    """Implementa `jarvis.voice.ports.ConversationalAgent`.

    É a ponte inteira entre a voz e o resto do Jarvis, e o motivo de
    `jarvis.voice` não importar `jarvis.agent`, `jarvis.memory` nem
    `jarvis.execution`: tudo que essas camadas fazem acontece **aqui**, no
    composition root, exatamente como já acontecia em `agent ask`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        runtime: AgentRuntime,
        context: ContextEngine,
        memories: SqliteMemoryRepository,
        store: SqliteEventStore,
        skills: SkillRegistry,
        execute: bool = False,
        on_trace: Callable[[TurnTrace], None] = lambda trace: None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        bus: EventBus | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._context = context
        self._memories = memories
        self._store = store
        self._skills = skills
        self._execute = execute
        self._on_trace = on_trace
        self._clock = clock
        # Fase 7: quando o composition root monta um bus compartilhado para
        # `jarvis run` (`_build_proactivity`), sessão/decisão/confirmação
        # publicam nele, para que o Trigger Engine e o Conditional Trigger
        # (já inscritos uma única vez) os vejam. `None` preserva o
        # comportamento anterior à Fase 7 (um bus descartável por chamada).
        self._bus = bus

    def respond(self, text: str, *, session: VoiceSession) -> AgentReply:
        """Fase 11.2: passa pelo mesmo `_run_agent_loop` de `agent ask`/`chat`/
        `pursue` — o raciocínio multi-passo (até `voice_pursue_max_steps`) e a
        explicação em linguagem natural após negação/confirmação pendente
        (Fase 11.1) chegam à voz sem nenhum código específico de voz. Como o
        loop só **imprime** progresso intermediário (nunca fala), os passos
        que não são o último ficam naturalmente silenciosos: uma frase falada
        só, refletindo o desfecho final. `_run_agent_loop` já cuida de
        registrar a decisão e persistir a proposta de memória de cada passo —
        proveniência sem `reference` (Fase 7), mesmo motivo de sempre
        (ADR-0018): um ponteiro por sessão faria `find_duplicate` tratar cada
        conversa como um universo novo e trocaria reforço por linha nova.
        """
        now = self._clock()
        result = _run_agent_loop(
            self._settings,
            store=self._store,
            context=self._context,
            memory_manager=build_memory_manager(self._memories),
            skills=self._skills,
            runtime=self._runtime,
            recent=_recent_events(self._store),
            agent_input=UserMessage(text=text, at=now, conversation_id=session.session_id),
            conversation=_conversation_of(session),
            conversation_id=session.session_id,
            max_steps=self._settings.voice_pursue_max_steps,
            execute=self._execute,
        )
        turn, write, outcome = result.turn, result.write, result.outcome
        self._on_trace(_trace_of(turn, write=write, at=now))

        message = _reply(turn.decision, write)
        if outcome is None:
            return AgentReply(
                text=message,
                decision_type=turn.decision.type.value,
                correlation_id=turn.decision.correlation_id,
            )
        return AgentReply(
            text=_spoken_outcome(message, outcome),
            decision_type=turn.decision.type.value,
            correlation_id=turn.decision.correlation_id,
            awaiting_confirmation=outcome.execution_id
            if outcome.status is ExecutionStatus.AWAITING_CONFIRMATION
            else None,
            detail=outcome.reason,
        )

    def answer_confirmation(
        self, execution_id: str, *, granted: bool, session: VoiceSession
    ) -> AgentReply:
        """A confirmação falada percorre o mesmo caminho da digitada.

        Publica o evento e retoma num passo separado, que **reavalia a política
        do zero** (ADR-0013/0014). A voz não ganha atalho nenhum.
        """
        with SqliteActionRepository.open(action_store_path(self._settings)) as actions:
            pending = actions.get(execution_id)
            if pending is None:
                return AgentReply(text="Não encontrei essa ação.", decision_type="notify")

            publisher = _build_publisher(
                self._store, bus=self._bus, confirmations=ActionEventConsumer(actions)
            )
            publisher.publish(
                confirmation_event(
                    granted=granted,
                    execution_id=pending.execution_id,
                    parameters_fingerprint=pending.parameters_fingerprint,
                    correlation_id=pending.correlation_id,
                    occurred_at=self._clock(),
                    causation_id=pending.causation_id,
                    reason="" if granted else "rejected_by_voice",
                )
            )
            if not granted:
                return AgentReply(text="Cancelado.", decision_type="notify")

            tools = build_tool_registry(self._settings)
            try:
                executor = build_action_executor(
                    self._settings,
                    store=self._store,
                    actions=actions,
                    tools=tools,
                    skills=self._skills,
                )
                outcome = executor.resume(pending.execution_id)
            finally:
                tools.close()

        return AgentReply(
            text=_spoken_outcome(None, outcome),
            decision_type="act",
            correlation_id=outcome.correlation_id,
        )


def _conversation_of(session: VoiceSession) -> Conversation:
    """Traduz a sessão de voz na conversa que o agente entende.

    Uma história só, em dois formatos: `VoiceSession` é o que persiste e o que o
    painel mostra; `Conversation` é o que entra no prompt.
    """
    conversation = Conversation(conversation_id=session.session_id)
    for turn in session.turns:
        role = Role.USER if turn.role.value == "user" else Role.ASSISTANT
        conversation = conversation.append(ConversationTurn(role=role, text=turn.text, at=turn.at))
    return conversation


def _spoken_outcome(message: str | None, outcome: ExecutionOutcome) -> str:
    """O que o Jarvis diz sobre o desfecho de uma ação, em uma frase."""
    if outcome.status is ExecutionStatus.COMPLETED:
        return message or f"Pronto: {outcome.skill}."
    if outcome.status is ExecutionStatus.AWAITING_CONFIRMATION:
        return f"{message + ' ' if message else ''}Preciso da sua confirmação para {outcome.skill}."
    if outcome.status is ExecutionStatus.DENIED:
        return f"Não posso fazer isso: {outcome.reason or 'a política negou'}."
    return f"Não consegui concluir {outcome.skill}: {outcome.reason or 'falha na execução'}."


def _trace_of(turn: AgentTurn, *, write: MemoryWrite, at: datetime) -> TurnTrace:
    return TurnTrace(
        decision_type=turn.decision.type.value,
        decided_at=at,
        reason=turn.decision.reason,
        message=_reply(turn.decision, write) or "",
        correlation_id=turn.decision.correlation_id,
        consulted_llm=turn.consulted_llm,
        importance=turn.importance.total if turn.importance is not None else None,
    )


def build_observability_service(
    settings: Settings,
    *,
    store: SqliteEventStore,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
    actions: SqliteActionRepository,
) -> ObservabilityService:
    """Liga o painel às fontes de verdade.

    As quatro leituras são **funções**, e é isso que mantém `jarvis.interface`
    sem conhecer SQLite: ela recebe dados já lidos, não uma conexão.
    """

    def read_context() -> CurrentContext:
        context.refresh()
        return context.current()

    return ObservabilityService(
        read_events=lambda limit: store.read_latest(limit=limit),
        read_context=read_context,
        read_memories=lambda limit: memories.search(MemoryCriteria(limit=limit)),
        read_pending=lambda: actions.list_by_status(ExecutionStatus.AWAITING_CONFIRMATION),
        timeline_limit=settings.panel_timeline_limit,
        memory_limit=settings.panel_memory_limit,
    )


class PanelBridge:
    """Une o loop de voz ao painel, com as duas cadências do plano da fase.

    - **status**: toda transição de estado publica na hora, sem tocar banco;
    - **snapshot**: a cada `JARVIS_PANEL_REFRESH_SECONDS` e ao fim de cada turno,
      relê as quatro fontes.

    Tudo roda na thread principal. O servidor HTTP só lê o `LiveState`, que é o
    que torna a regra "nenhuma thread além da principal toca SQLite" verdadeira
    por construção (ADR-0023).
    """

    def __init__(
        self,
        *,
        live: LiveState,
        service: ObservabilityService,
        refresh_seconds: float = 2.0,
        monotonic: Callable[[], float] = time.monotonic,
        on_refresh: Callable[[], None] = lambda: None,
    ) -> None:
        self._live = live
        self._service = service
        self._refresh_seconds = refresh_seconds
        self._monotonic = monotonic
        self._due = 0.0
        self._session: VoiceSession | None = None
        self._voice: VoiceStatus | None = None
        self._trace: TurnTrace | None = None
        self._last: PanelSnapshot | None = None
        # Fase 7.5: ponto de tick do Background Task Manager. `refresh()` já
        # roda periodicamente em `jarvis run`, com ou sem voz — reaproveitá-lo
        # evita um timer novo (ADR-0027) sem custar um `ToolRegistry`/conexão
        # MCP por ciclo, porque quem chama já entrega um executor pronto.
        self._on_refresh = on_refresh

    @property
    def live(self) -> LiveState:
        return self._live

    def on_status(self, status: VoiceStatus) -> None:
        self._voice = status
        if self._last is None or self._monotonic() >= self._due:
            self.refresh()
            return
        self._publish(replace(self._last, voice=_voice_view_of(status)))

    def on_session(self, session: VoiceSession, started: bool) -> None:
        self._session = session
        self.refresh()

    def on_trace(self, trace: TurnTrace) -> None:
        self._trace = trace

    def refresh(self) -> None:
        self._on_refresh()
        snapshot = self._service.snapshot(
            voice=self._voice, session=self._session, trace=self._trace
        )
        self._due = self._monotonic() + self._refresh_seconds
        self._publish(snapshot)

    def _publish(self, snapshot: PanelSnapshot) -> None:
        self._last = snapshot
        self._live.publish(snapshot)


def _voice_view_of(status: VoiceStatus) -> VoiceStatusView:
    return VoiceStatusView(
        state=status.state.value,
        session_id=status.session_id,
        detail=status.detail,
        last_transcript=status.last_transcript,
        last_reply=status.last_reply,
        at=status.at,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Agente pessoal de IA.")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("info", help="Mostra a configuração efetiva.")

    events = subparsers.add_parser("events", help="Registra e consulta eventos.")
    events.set_defaults(events_parser=events)
    actions = events.add_subparsers(dest="events_command")

    emit = actions.add_parser("emit", help="Registra um novo evento.")
    emit.add_argument("--type", required=True, help="Tipo namespaced, ex. email.received.")
    emit.add_argument("--source", required=True, help="Origem do evento, ex. gmail-watcher.")
    emit.add_argument("--payload", required=True, help="Conteúdo do evento, como objeto JSON.")
    emit.add_argument(
        "--key",
        help="Chave natural da origem; deriva um event_id determinístico, "
        "de modo que reemitir o mesmo acontecimento seja no-op.",
    )
    emit.add_argument("--occurred-at", help="Quando o fato ocorreu (ISO-8601 com timezone).")
    emit.add_argument("--correlation-id", help="Cadeia causal à qual o evento pertence.")
    emit.add_argument("--causation-id", help="Evento que causou diretamente este.")
    emit.add_argument("--schema-version", type=int, default=1)
    emit.add_argument("--metadata", help="Metadados livres, como objeto JSON.")

    listing = actions.add_parser("list", help="Lista eventos registrados.")
    listing.add_argument("--type", help="Filtra por tipo exato.")
    listing.add_argument("--correlation-id", help="Mostra a cadeia causal inteira.")
    listing.add_argument("--since", help="Início da janela de occurred_at (ISO-8601, inclusivo).")
    listing.add_argument("--until", help="Fim da janela de occurred_at (ISO-8601, exclusivo).")
    listing.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)

    context = subparsers.add_parser("context", help="Inspeciona e captura o contexto atual.")
    context.set_defaults(context_parser=context)
    context_actions = context.add_subparsers(dest="context_command")
    context_actions.add_parser("show", help="Mostra a projeção atual, campo a campo.")
    context_actions.add_parser(
        "snapshot", help="Captura a projeção atual, se algo mudou desde a última."
    )

    memory = subparsers.add_parser("memory", help="Gerencia memórias persistentes.")
    memory.set_defaults(memory_parser=memory)
    memory_actions = memory.add_subparsers(dest="memory_command")

    memory_types = [item.value for item in MemoryType]
    memory_origins = [item.value for item in MemoryOrigin]

    add_memory = memory_actions.add_parser("add", help="Cria uma memória.")
    add_memory.add_argument("--type", required=True, choices=memory_types)
    add_memory.add_argument("--content", required=True)
    add_memory.add_argument("--origin", default="user", choices=memory_origins)
    add_memory.add_argument("--reference", help="Proveniência, ex. um event_id.")
    add_memory.add_argument("--importance", type=float, default=0.5)
    add_memory.add_argument("--confidence", type=float, default=0.8)
    add_memory.add_argument("--subject", help="Slug; chave de contradição.")
    add_memory.add_argument("--scope", help="task_id ou conversation_id.")
    add_memory.add_argument("--tags", help="Lista separada por vírgula.")
    add_memory.add_argument("--entities", help="Lista separada por vírgula.")
    add_memory.add_argument("--valid-until", help="ISO-8601 com timezone.")
    add_memory.add_argument(
        "--no-embedding", action="store_true", help="Não gera embedding para esta memória."
    )

    get_memory = memory_actions.add_parser(
        "get", help="Busca uma memória por id; registra o acesso."
    )
    get_memory.add_argument("memory_id")

    list_memory = memory_actions.add_parser("list", help="Lista memórias por filtro estruturado.")
    list_memory.add_argument("--type", choices=memory_types)
    list_memory.add_argument("--subject")
    list_memory.add_argument("--scope")
    list_memory.add_argument("--tag", action="append", default=[])
    list_memory.add_argument("--entity", action="append", default=[])
    list_memory.add_argument("--include-invalidated", action="store_true")
    list_memory.add_argument("--include-superseded", action="store_true")
    list_memory.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)

    search_memory = memory_actions.add_parser(
        "search", help="Busca semântica (ou estruturada, se o texto for omitido)."
    )
    search_memory.add_argument(
        "text", nargs="?", help="Consulta textual; omitida = lookup estruturado."
    )
    search_memory.add_argument("--type", choices=memory_types)
    search_memory.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)
    search_memory.add_argument(
        "--explain", action="store_true", help="Mostra o detalhamento do score."
    )
    search_memory.add_argument(
        "--from-context", action="store_true", help="Usa o contexto atual como filtro."
    )

    forget_memory = memory_actions.add_parser("forget", help="Invalida (ou apaga) uma memória.")
    forget_memory.add_argument("memory_id")
    forget_memory.add_argument("--reason", required=True)
    forget_memory.add_argument(
        "--purge", action="store_true", help="Remove fisicamente, de forma irreversível."
    )

    memory_actions.add_parser(
        "reindex", help="Regenera embeddings incompatíveis com o modelo atual."
    )

    agent = subparsers.add_parser("agent", help="Conversa com o agente e avalia eventos.")
    agent.set_defaults(agent_parser=agent)
    agent_actions = agent.add_subparsers(dest="agent_command")

    ask = agent_actions.add_parser("ask", help="Faz uma pergunta e imprime a decisão.")
    ask.add_argument("text", help="A mensagem para o agente.")
    ask.add_argument("--conversation-id", help="Correlaciona turnos da mesma conversa.")
    ask.add_argument(
        "--max-steps",
        type=int,
        default=1,
        help="Teto de passos para o mesmo pedido (Fase 10.2; default 1 — uma ação só).",
    )

    chat = agent_actions.add_parser(
        "chat", help="Conversa multi-turno lendo uma mensagem por linha da entrada padrão."
    )
    chat.add_argument("--conversation-id")
    chat.add_argument(
        "--execute",
        action="store_true",
        help="Submete a ação proposta ao Policy Engine (por padrão a decisão só é impressa).",
    )
    chat.add_argument(
        "--max-steps",
        type=int,
        default=1,
        help="Teto de passos por linha digitada (Fase 10.2; default 1 — uma ação só).",
    )

    react = agent_actions.add_parser("react", help="Avalia proativamente um evento já registrado.")
    react.add_argument("--event-id", required=True)
    react.add_argument(
        "--execute",
        action="store_true",
        help="Submete a ação proposta ao Policy Engine (por padrão a decisão só é impressa).",
    )
    ask.add_argument(
        "--execute",
        action="store_true",
        help="Submete a ação proposta ao Policy Engine (por padrão a decisão só é impressa).",
    )

    pursue = agent_actions.add_parser(
        "pursue", help="Persegue um objetivo em múltiplos passos, até parar ou pedir confirmação."
    )
    pursue.add_argument(
        "goal",
        nargs="?",
        default=None,
        help=(
            "O objetivo para o agente perseguir. Com --resume, é opcional — "
            "se dado, vira orientação adicional para o passo seguinte."
        ),
    )
    pursue.add_argument("--conversation-id")
    pursue.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Teto de passos (default: JARVIS_AGENT_PURSUE_MAX_STEPS; em --resume, o teto "
        "total contando os passos já dados).",
    )
    pursue.add_argument(
        "--resume",
        metavar="PURSUIT_ID",
        help="Retoma um agent pursue interrompido a partir do checkpoint salvo (Fase 10.5).",
    )

    skills = subparsers.add_parser("skills", help="Lista as capacidades registradas.")
    skills.set_defaults(skills_parser=skills)
    skills_actions = skills.add_subparsers(dest="skills_command")
    skills_actions.add_parser("list", help="Lista as skills e seus metadados de risco.")

    tools = subparsers.add_parser("tools", help="Inspeciona as ferramentas disponíveis.")
    tools.set_defaults(tools_parser=tools)
    tools_actions = tools.add_subparsers(dest="tools_command")
    tools_list = tools_actions.add_parser("list", help="Lista as tools descobertas por backend.")
    tools_list.add_argument(
        "--schemas", action="store_true", help="Mostra o schema de entrada de cada tool."
    )

    action = subparsers.add_parser("action", help="Executa e confirma ações.")
    action.set_defaults(action_parser=action)
    action_actions = action.add_subparsers(dest="action_command")

    run = action_actions.add_parser("run", help="Submete uma skill ao Policy Engine.")
    run.add_argument("--skill", required=True)
    run.add_argument("--parameters", help="Parâmetros da skill, como objeto JSON.")
    run.add_argument("--actor", default=Actor.USER.value, choices=[item.value for item in Actor])
    run.add_argument("--correlation-id", help="Cadeia causal à qual a execução pertence.")

    action_actions.add_parser("pending", help="Lista as ações aguardando confirmação.")

    show = action_actions.add_parser("show", help="Mostra o estado de uma execução.")
    show.add_argument("execution_id")

    confirm = action_actions.add_parser(
        "confirm", help="Confirma uma ação pendente e retoma a execução."
    )
    confirm.add_argument("execution_id")

    reject = action_actions.add_parser("reject", help="Recusa uma ação pendente.")
    reject.add_argument("execution_id")
    reject.add_argument("--reason", default="rejected_by_user")

    decisions = subparsers.add_parser("decisions", help="Consulta decisões do agente.")
    decisions.set_defaults(decisions_parser=decisions)
    decisions_actions = decisions.add_subparsers(dest="decisions_command")
    decisions_list = decisions_actions.add_parser("list", help="Lista decisões registradas.")
    decisions_list.add_argument("--correlation-id", help="Mostra a cadeia causal inteira.")
    decisions_list.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)

    audit = subparsers.add_parser("audit", help="Consulta a trilha de auditoria (Fase 8.4).")
    audit.set_defaults(audit_parser=audit)
    audit_actions = audit.add_subparsers(dest="audit_command")
    audit_show = audit_actions.add_parser(
        "show", help="Mostra decisão(ões) e trilha de ação de uma correlação."
    )
    audit_show.add_argument("correlation_id")

    tasks_parser = subparsers.add_parser("tasks", help="Tarefas em background (Fase 7.5).")
    tasks_parser.set_defaults(tasks_parser=tasks_parser)
    tasks_actions = tasks_parser.add_subparsers(dest="tasks_command")
    tasks_actions.add_parser("list", help="Lista tarefas pendentes/em retry.")
    tasks_show = tasks_actions.add_parser("show", help="Mostra o estado de uma tarefa.")
    tasks_show.add_argument("task_id")
    tasks_cancel = tasks_actions.add_parser("cancel", help="Cancela uma tarefa não terminal.")
    tasks_cancel.add_argument("task_id")
    tasks_actions.add_parser(
        "run-due", help="Executa toda tarefa devida agora (mesmo tick de `jarvis run`)."
    )

    voice = subparsers.add_parser("voice", help="Fala e escuta.")
    voice.set_defaults(voice_parser=voice)
    voice_actions = voice.add_subparsers(dest="voice_command")

    voice_actions.add_parser("devices", help="Lista os dispositivos de áudio disponíveis.")

    say = voice_actions.add_parser("say", help="Sintetiza uma frase.")
    say.add_argument("text")
    say.add_argument("--out", help="Grava um WAV em vez de tocar no alto-falante.")

    transcribe = voice_actions.add_parser("transcribe", help="Transcreve um arquivo WAV.")
    transcribe.add_argument("path")

    listen = voice_actions.add_parser("listen", help="Conversa por voz, sem painel.")
    listen.add_argument(
        "--execute",
        action="store_true",
        help="Submete ações propostas ao Policy Engine (por padrão elas só são faladas).",
    )
    # `listen` e `serve` são o mesmo processo residente com peças diferentes.
    listen.set_defaults(no_panel=True, no_voice=False)

    sessions = voice_actions.add_parser("sessions", help="Consulta e apaga sessões de voz.")
    sessions_actions = sessions.add_subparsers(dest="sessions_command")
    sessions_list = sessions_actions.add_parser("list", help="Lista as sessões recentes.")
    sessions_list.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT)
    sessions_show = sessions_actions.add_parser("show", help="Mostra os turnos de uma sessão.")
    sessions_show.add_argument("session_id")
    sessions_purge = sessions_actions.add_parser("purge", help="Apaga sessões e suas transcrições.")
    sessions_purge.add_argument("session_id", nargs="?")
    sessions_purge.add_argument("--all", action="store_true", help="Apaga todas as sessões.")

    panel = subparsers.add_parser("panel", help="Painel de observabilidade local.")
    panel.set_defaults(panel_parser=panel)
    panel_actions = panel.add_subparsers(dest="panel_command")
    serve = panel_actions.add_parser("serve", help="Serve o painel em 127.0.0.1.")
    serve.add_argument("--once", action="store_true", help="Publica um snapshot e sai.")
    serve.set_defaults(no_panel=False, no_voice=True)

    run = subparsers.add_parser("run", help="Voz e painel no mesmo processo.")
    run.add_argument(
        "--execute",
        action="store_true",
        help="Submete ações propostas ao Policy Engine (por padrão elas só são faladas).",
    )
    run.add_argument("--no-panel", action="store_true", help="Sobe só a voz.")
    run.add_argument("--no-voice", action="store_true", help="Sobe só o painel.")

    return parser


def _parse_json_object(raw: str, *, field_name: str) -> dict[str, JsonValue]:
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as error:
        raise InvalidEventError(f"{field_name} não é JSON válido: {error.msg}") from error
    if not isinstance(decoded, dict):
        raise InvalidEventError(f"{field_name} precisa ser um objeto JSON")
    return decoded


def _parse_timestamp(raw: str, *, field_name: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError as error:
        raise InvalidEventError(f"{field_name} não é uma data ISO-8601 válida: {raw!r}") from error


def _build_event(args: argparse.Namespace) -> Event:
    event_id = (
        deterministic_event_id(source=args.source, natural_key=args.key)
        if args.key
        else new_event_id()
    )
    occurred_at = (
        _parse_timestamp(args.occurred_at, field_name="--occurred-at")
        if args.occurred_at
        else datetime.now(UTC)
    )
    return Event(
        event_id=event_id,
        event_type=args.type,
        source=args.source,
        occurred_at=occurred_at,
        payload=_parse_json_object(args.payload, field_name="--payload"),
        schema_version=args.schema_version,
        correlation_id=args.correlation_id,
        causation_id=args.causation_id,
        metadata=_parse_json_object(args.metadata, field_name="--metadata")
        if args.metadata
        else {},
    )


def _emit(args: argparse.Namespace, settings: Settings) -> int:
    event = _build_event(args)

    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        bus = EventBus()
        bus.subscribe(LoggingEventConsumer())
        # Filtro explícito: cada consumer só recebe o que sabe projetar. Sem
        # retry — payload malformado é falha permanente, e o bus manda para
        # dead-letter sem desfazer o evento já gravado.
        bus.subscribe(
            build_context_engine(settings, snapshots).consumer, event_types=CONTEXT_EVENT_TYPES
        )
        bus.subscribe(
            MemoryEventConsumer(build_memory_manager(memories)), event_types=MEMORY_EVENT_TYPES
        )
        result = EventPublisher(store=store, bus=bus).publish(event)

    print(f"event_id       {result.event.event.event_id}")
    print(f"correlation_id {result.event.event.correlation_id}")
    print(f"recorded_at    {result.event.recorded_at.isoformat()}")
    print(f"status         {'duplicate' if result.is_duplicate else 'recorded'}")
    return EXIT_OK


def _read(args: argparse.Namespace, store: SqliteEventStore) -> Sequence[RecordedEvent]:
    window = bool(args.since or args.until)
    if sum([bool(args.type), bool(args.correlation_id), window]) > 1:
        raise InvalidEventError("use apenas um filtro: --type, --correlation-id ou --since/--until")

    if args.correlation_id:
        return store.read_by_correlation(args.correlation_id)
    if window:
        if not (args.since and args.until):
            raise InvalidEventError("--since e --until precisam ser usados juntos")
        return store.read_occurred_between(
            _parse_timestamp(args.since, field_name="--since"),
            _parse_timestamp(args.until, field_name="--until"),
            limit=args.limit,
        )
    if args.type:
        return store.read_by_type(args.type, limit=args.limit)
    return store.read_latest(limit=args.limit)


def _list(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteEventStore.open(event_store_path(settings)) as store:
        events = _read(args, store)

    if not events:
        print("nenhum evento encontrado")
        return EXIT_OK

    for recorded in events:
        event = recorded.event
        print(
            f"{recorded.recorded_at.isoformat()}  {event.event_type:<28}  "
            f"{event.source:<16}  {event.event_id}  correlation={event.correlation_id}"
        )
    return EXIT_OK


def _info(settings: Settings) -> int:
    print(f"jarvis {__version__}")
    print(f"env           {settings.env}")
    print(f"log_level     {settings.log_level}")
    print(f"data_dir      {settings.data_dir}")
    print(f"event_store   {event_store_path(settings)}")
    print(f"context_store {context_store_path(settings)}")
    print(f"memory_store  {memory_store_path(settings)}")
    print(f"action_store  {action_store_path(settings)}")
    print(f"voice_store   {voice_store_path(settings)}")
    print(f"task_store    {task_store_path(settings)}")
    print(f"pursuit_store {pursuit_store_path(settings)}")
    print(
        f"voice         wake={settings.wake_strategy} stt={settings.stt_provider} "
        f"tts={settings.tts_provider} voz={settings.tts_voice}"
    )
    print(f"panel         http://{settings.panel_host}:{settings.panel_port}")
    print(f"workspace     {settings.file_skill_root}")
    print(f"mcp_config    {settings.mcp_config_path or ABSENT}")
    # A política efetiva não deve ser adivinhada: ela é a diferença entre uma
    # ação permitida e uma negada, e vive em variáveis de ambiente.
    print(f"policy        {build_policy_rules(settings).describe()}")
    triggers = _parse_list(settings.proactivity_trigger_event_types)
    execute_label = "sim" if settings.proactivity_execute_actions else "não"
    print(
        f"proactivity   enabled={'sim' if settings.proactivity_enabled else 'não'} "
        f"triggers={len(triggers)} execute={execute_label} "
        f"rules={settings.proactivity_rules_path or ABSENT}"
    )
    print(f"notify        silent={'sim' if settings.notify_silent_mode else 'não'}")
    return EXIT_OK


def _render_value(value: object) -> str:
    if value is None:
        return OBSERVED_ABSENCE
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _print_context(context: CurrentContext) -> None:
    print(f"as_of {context.as_of.isoformat()}")
    for field, observation in iter_fields(context):
        if observation is None:
            # Ausência é ausência: o Context Engine nunca preenche o que não sabe.
            print(f"{field.value:<14} {ABSENT}")
            continue
        print(
            f"{field.value:<14} {_render_value(observation.value):<32} "
            f"{observation.source:<34} {observation.observed_at.isoformat()}  "
            f"{observation.freshness(context.as_of).value}"
        )


def _run_context_command(settings: Settings, action: str) -> int:
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
    ):
        engine = build_context_engine(settings, snapshots)
        # A projeção é derivada: um processo novo a reconstrói do Event Store
        # antes de perguntar aos providers.
        engine.rebuild_from(store)
        engine.refresh()

        if action == "show":
            _print_context(engine.current())
            return EXIT_OK

        captured = engine.capture_snapshot()

    if captured is None:
        print("unchanged")
        return EXIT_OK
    print(f"captured {captured.snapshot_id}")
    print(f"captured_at {captured.captured_at.isoformat()}")
    return EXIT_OK


def _context(args: argparse.Namespace, settings: Settings) -> int:
    if args.context_command is None:
        args.context_parser.print_help()
        return EXIT_OK
    return _run_context_command(settings, args.context_command)


def _parse_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _print_memory(stored: StoredMemory) -> None:
    memory = stored.memory
    print(f"memory_id   {memory.memory_id}")
    print(f"type        {memory.type.value}")
    print(f"content     {memory.content}")
    print(f"subject     {memory.subject or ABSENT}")
    print(f"scope       {memory.scope or ABSENT}")
    print(f"importance  {memory.importance}")
    print(f"confidence  {stored.confidence}")
    print(f"origin      {memory.provenance.origin.value}")
    print(f"reference   {memory.provenance.reference or ABSENT}")
    print(f"created_at  {memory.created_at.isoformat()}")
    print(f"valid_from  {memory.valid_from.isoformat() if memory.valid_from else ABSENT}")
    print(f"valid_until {memory.valid_until.isoformat() if memory.valid_until else ABSENT}")
    print(f"embedding   {'yes' if memory.embedding is not None else 'no'}")
    print(f"access      {stored.access_count}")
    print(f"reinforced  {stored.reinforced_count}")


def _print_memory_row(stored: StoredMemory) -> None:
    memory = stored.memory
    summary = memory.content if len(memory.content) <= 60 else f"{memory.content[:57]}..."
    print(
        f"{memory.memory_id}  {memory.type.value:<11} {(memory.subject or ABSENT):<28} "
        f"imp={memory.importance:.2f} conf={stored.confidence:.2f}  {summary}"
    )


def _memory_add(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        stored = build_memory_manager(memories).remember(
            type=MemoryType(args.type),
            content=args.content,
            provenance=Provenance(origin=MemoryOrigin(args.origin), reference=args.reference),
            importance=args.importance,
            confidence=args.confidence,
            subject=args.subject,
            scope=args.scope,
            tags=_parse_list(args.tags),
            entities=_parse_list(args.entities),
            valid_until=_parse_timestamp(args.valid_until, field_name="--valid-until")
            if args.valid_until
            else None,
            embed=False if args.no_embedding else None,
        )
    _print_memory(stored)
    return EXIT_OK


def _memory_get(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        stored = build_memory_manager(memories).record_access(args.memory_id)
    _print_memory(stored)
    return EXIT_OK


def _memory_list(args: argparse.Namespace, settings: Settings) -> int:
    criteria = MemoryCriteria(
        types=frozenset({MemoryType(args.type)}) if args.type else None,
        subject=args.subject,
        scope=args.scope,
        tags=frozenset(args.tag) if args.tag else None,
        entities=frozenset(args.entity) if args.entity else None,
        include_invalidated=args.include_invalidated,
        include_superseded=args.include_superseded,
        limit=args.limit,
    )
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        found = memories.search(criteria)

    if not found:
        print("nenhuma memória encontrada")
        return EXIT_OK
    for stored in found:
        _print_memory_row(stored)
    return EXIT_OK


def _memory_search(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        manager = build_memory_manager(memories)

        if args.from_context:
            with (
                SqliteEventStore.open(event_store_path(settings)) as store,
                SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
            ):
                engine = build_context_engine(settings, snapshots)
                engine.rebuild_from(store)
                engine.refresh()
                query = context_to_query(engine.current(), text=args.text, limit=args.limit)
        else:
            criteria = MemoryCriteria(
                types=frozenset({MemoryType(args.type)}) if args.type else None
            )
            query = RetrievalQuery(text=args.text, criteria=criteria, limit=args.limit)

        outcome = manager.retrieve(query)

    if outcome.skipped_incompatible:
        print(
            f"aviso: {outcome.skipped_incompatible} memória(s) fora do modelo de embedding "
            "atual; rode `jarvis memory reindex`",
            file=sys.stderr,
        )
    if not outcome.results:
        print("nenhuma memória encontrada")
        return EXIT_OK
    for result in outcome.results:
        _print_memory_row(result.memory)
        if args.explain:
            score = result.score
            semantic = "n/a" if score.semantic is None else f"{score.semantic:.3f}"
            print(
                f"    score={score.total:.3f} semantic={semantic} "
                f"recency={score.recency:.3f} importance={score.importance:.3f} "
                f"confidence={score.confidence:.3f}"
            )
    return EXIT_OK


def _memory_forget(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        manager = build_memory_manager(memories)
        if args.purge:
            removed = manager.purge(args.memory_id)
            print(f"purged {args.memory_id}" if removed else "nenhuma memória encontrada")
            return EXIT_OK
        stored = manager.forget(args.memory_id, reason=args.reason)
    print(f"forgotten   {stored.memory.memory_id}")
    print(f"reason      {stored.invalidation_reason}")
    return EXIT_OK


def _memory_reindex(settings: Settings) -> int:
    with SqliteMemoryRepository.open(memory_store_path(settings)) as memories:
        updated = build_memory_manager(memories).reembed()
    print(f"reindexed {updated}")
    return EXIT_OK


def _memory(args: argparse.Namespace, settings: Settings) -> int:
    if args.memory_command is None:
        args.memory_parser.print_help()
        return EXIT_OK
    if args.memory_command == "add":
        return _memory_add(args, settings)
    if args.memory_command == "get":
        return _memory_get(args, settings)
    if args.memory_command == "list":
        return _memory_list(args, settings)
    if args.memory_command == "search":
        return _memory_search(args, settings)
    if args.memory_command == "forget":
        return _memory_forget(args, settings)
    return _memory_reindex(settings)


def _reply(decision: Decision, write: MemoryWrite) -> str | None:
    """O que o agente tem a dizer ao usuário neste turno.

    Um `remember` puro não traz `message`: sem a confirmação da gravação, o
    turno ficaria mudo e a conversa, sem turno do assistente.
    """
    if decision.message is not None:
        return decision.message
    return REMEMBER_SAVED_MESSAGE if write.stored is not None else None


def _print_turn(turn: AgentTurn, *, write: MemoryWrite, submitting: bool = False) -> None:
    decision = turn.decision
    print(f"decision    {decision.type.value}")
    print(f"reason      {decision.reason}")
    if decision.reasoning is not None:
        print(f"raciocínio  {decision.reasoning}")
    message = _reply(decision, write)
    if message is not None:
        print(f"message     {message}")
    if decision.memory is not None:
        proposal = decision.memory
        print(f"memory      {proposal.type.value}: {proposal.content}")
    if write.stored is not None:
        # Reforço e criação são desfechos diferentes de `remember` (dedup por
        # fingerprint); dizer "gravada" nos dois casos mentiria sobre qual id
        # o usuário encontraria em `jarvis memory get`.
        verb = "reforçada" if write.stored.reinforced_count else "gravada"
        print(f"            {verb} como {write.stored.memory.memory_id}")
    if write.rejected is not None:
        print(f"            proposta recusada: {write.rejected}")
    if decision.action is not None:
        print(f"action      {decision.action.skill} {json.dumps(dict(decision.action.parameters))}")
        if not submitting:
            print("            proposta não executada: use --execute para submetê-la à política")
    if turn.importance is not None:
        assessment = turn.importance
        print(
            f"importance  {assessment.total:.3f} "
            f"(urgency={assessment.urgency:.2f} relevance={assessment.personal_relevance:.2f} "
            f"temporal={assessment.temporal_relevance:.2f} "
            f"interruption={assessment.interruption_cost:.2f})"
        )
        print(f"reasons     {', '.join(assessment.reasons) or ABSENT}")
    print(f"llm         {'consultado' if turn.consulted_llm else 'não consultado'}")
    print(f"memories    {len(turn.used_memory_ids)}")
    print(f"correlation {decision.correlation_id}")


def _persist_memory_proposal(
    turn: AgentTurn, manager: MemoryManager, *, provenance: Provenance
) -> MemoryWrite:
    """Aplica a proposta de memória de um turno, se houver.

    O Agent Runtime continua sem efeitos: quem lê a `Decision` e escreve é o
    composition root, o mesmo desenho de `_submit_proposal`. A diferença é que
    aqui não há `--execute`: gravar uma afirmação não é executar uma capacidade,
    não toca nada fora do processo e é desfeita por supersessão — o Policy
    Engine é autoridade sobre ações, não sobre o que o agente aprende
    (ADR-0018).

    Vale para qualquer decisão que carregue `memory`, não só `remember`: a
    matriz de `decision.py` permite `notify` com proposta junto, e ignorá-la ali
    perderia a memória sem motivo.

    `MemoryProposal` é mais permissivo que `Memory` — não tem `scope` nem
    `valid_until`, então uma proposta `task`, `working` ou `preference` sem
    `subject` é sintaticamente válida e mesmo assim recusada pelo domínio. Isso
    é recusa da proposta, não falha do turno: a mensagem e a ação da decisão
    continuam valendo, e derrubar o comando por causa de um deslize do modelo
    perderia as duas.
    """
    proposal = turn.decision.memory
    if proposal is None:
        return MemoryWrite()

    try:
        stored = manager.remember(
            type=proposal.type,
            content=proposal.content,
            provenance=provenance,
            importance=proposal.importance,
            confidence=proposal.confidence,
            subject=proposal.subject,
        )
    except InvalidMemoryError as error:
        return MemoryWrite(rejected=str(error))
    return MemoryWrite(stored=stored)


def _prepared_context(
    settings: Settings, store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> ContextEngine:
    """A projeção é derivada: um processo novo a reconstrói antes de raciocinar
    sobre ela. Quem reconstrói é o composition root — o Agent Runtime recebe
    contexto pronto e nunca conhece o Event Store (contracts §3.4)."""
    engine = build_context_engine(settings, snapshots)
    engine.rebuild_from(store)
    engine.refresh()
    return engine


def _record_decision(
    turn: AgentTurn,
    *,
    context_as_of: datetime | None,
    store: SqliteEventStore,
    bus: EventBus | None = None,
) -> None:
    """Publica a decisão do turno como evento — Fase 7.4.

    Extrai primitivos de `AgentTurn`/`Decision` aqui, no composition root: é
    isso que mantém `jarvis.decisions` sem depender de `jarvis.agent`.
    """
    decision = turn.decision
    event = decision_event(
        decision_id=decision.decision_id,
        decision_type=decision.type.value,
        reason=decision.reason,
        message=decision.message,
        decided_at=decision.decided_at,
        correlation_id=decision.correlation_id,
        causation_id=decision.causation_id,
        consulted_llm=turn.consulted_llm,
        importance=turn.importance.total if turn.importance is not None else None,
        used_memory_ids=turn.used_memory_ids,
        context_as_of=context_as_of,
        action_skill=decision.action.skill if decision.action is not None else None,
        reasoning=decision.reasoning,
        source=DECISION_SOURCE,
    )
    _build_publisher(store, bus=bus).publish(event)


def _recent_events(store: SqliteEventStore) -> tuple[EventSummary, ...]:
    return tuple(
        EventSummary.from_recorded(recorded)
        for recorded in store.read_latest(limit=DEFAULT_RECENT_EVENTS)
    )


def _submit_proposal(
    settings: Settings,
    *,
    turn: AgentTurn,
    store: SqliteEventStore,
    skills: SkillRegistry,
    actor: Actor,
) -> ExecutionOutcome | None:
    """Entrega a proposta do agente ao Policy Engine.

    O agente não chega até aqui: quem lê a `Decision` e submete é o composition
    root. É o mesmo motivo de `--execute` ser opt-in — executar precisa ser
    escolha de quem chamou, não consequência automática de raciocinar.
    """
    proposal = turn.decision.action
    if proposal is None:
        return None

    with SqliteActionRepository.open(action_store_path(settings)) as actions:
        tools = build_tool_registry(settings)
        try:
            executor = build_action_executor(
                settings, store=store, actions=actions, tools=tools, skills=skills
            )
            return executor.submit(
                ActionRequest(
                    skill=proposal.skill,
                    parameters=dict(proposal.parameters),
                    correlation_id=turn.decision.correlation_id,
                    actor=actor,
                    decision_id=turn.decision.decision_id,
                    causation_id=turn.decision.causation_id,
                )
            )
        finally:
            tools.close()


def _result_summary(outcome: ExecutionOutcome) -> ActionResultSummary:
    return ActionResultSummary(
        skill=outcome.skill,
        status=outcome.status.value,
        execution_id=outcome.execution_id,
        summary=outcome.summary,
        reason=outcome.reason,
    )


_DEFAULT_REFLECTION_PROMPT: Final = (
    "Explique, em uma frase, o desfecho da ação que acabou de ser tentada."
)


def _reflect_on_outcome(
    runtime: AgentRuntime,
    outcome: ExecutionOutcome,
    *,
    conversation_id: str,
    recent: tuple[EventSummary, ...],
    prompt: str = _DEFAULT_REFLECTION_PROMPT,
) -> AgentTurn | None:
    """Segundo turno de raciocínio — só quando a execução **não** deu certo.

    Em `act_and_notify` bem-sucedido a mensagem do agente já existe, e pagar uma
    chamada extra ao modelo para reformular o que já foi dito é desperdício de
    quota. Já uma negação ou uma falha merecem uma frase em linguagem natural, e
    é aí que o "observe result" do loop se fecha (Fase 9.1) — reaproveitado
    tanto pelo caminho síncrono (`agent ask --execute`) quanto pelos
    assíncronos (Background Task Manager, Trigger Engine).

    Devolve `None` em sucesso — quem chama decide o que fazer com `None`
    (normalmente: nada). Nunca submete uma nova ação a partir do turno de
    reflexão: encadear ações automaticamente é escopo do Goal Pursuit Loop
    (9.2), com suas próprias salvaguardas de teto e confirmação.
    """
    if outcome.status is ExecutionStatus.COMPLETED:
        return None
    return runtime.handle(
        UserMessage(text=prompt, at=datetime.now(UTC), conversation_id=conversation_id),
        recent_events=recent,
        last_action_result=_result_summary(outcome),
    )


_SESSION_REFLECTION_PROMPT: Final = (
    "A conversa está encerrando. Considerando tudo que foi dito, há algum fato ou "
    "preferência que vale registrar como memória? Se não houver nada além do que já "
    "foi tratado turno a turno, decida ignore."
)


def _reflect_on_session(
    runtime: AgentRuntime,
    *,
    conversation: Conversation,
    conversation_id: str,
    memory_manager: MemoryManager,
    store: SqliteEventStore,
    context: ContextEngine,
) -> None:
    """Fase 10.3: ao encerrar uma sessão (EOF de `agent chat`, fim de uma
    sessão de voz), um turno a mais pergunta ao histórico inteiro o que vale
    consolidar — em vez de depender só do que cada turno individual propôs
    no calor da hora. Reaproveita `_persist_memory_proposal`, o mesmo
    mecanismo turno a turno; nenhuma persistência nova.

    Sem conversa, não há o que refletir — chamar o LLM à toa não é grátis.
    """
    if not conversation.turns:
        return
    turn = runtime.handle(
        UserMessage(
            text=_SESSION_REFLECTION_PROMPT, at=datetime.now(UTC), conversation_id=conversation_id
        ),
        conversation=conversation,
    )
    _record_decision(turn, context_as_of=context.current().as_of, store=store)
    write = _persist_memory_proposal(turn, memory_manager, provenance=USER_ASSERTION)
    if write.stored is not None:
        verb = "reforçada" if write.stored.reinforced_count else "gravada"
        print(f"sessão      memória {verb} como {write.stored.memory.memory_id}")


PursuitProposal = tuple[str, Mapping[str, JsonValue]]
PursuitStepCallback = Callable[
    [int, PursuitStatus, "ActionResultSummary | None", "PursuitProposal | None"], None
]


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentLoopResult:
    """O que `_run_agent_loop` devolve a quem chama (Fase 11.1) — o
    suficiente para falar ou imprimir o desfecho, sem reabrir a `Decision`.

    `turn` é o turno mais recente que vale comunicar: o que agiu, quando deu
    certo, ou o turno de reflexão (`_reflect_on_outcome`), quando não deu —
    nunca o turno bruto que só propôs uma ação negada/pendente sem explicar
    por quê. `outcome` é o `ExecutionOutcome` do último passo submetido, se
    algum passo chegou a submeter.
    """

    turn: AgentTurn
    write: MemoryWrite
    outcome: ExecutionOutcome | None = None


def _run_agent_loop(
    settings: Settings,
    *,
    store: SqliteEventStore,
    context: ContextEngine,
    memory_manager: MemoryManager,
    skills: SkillRegistry,
    runtime: AgentRuntime,
    recent: tuple[EventSummary, ...],
    agent_input: AgentInput,
    conversation: Conversation | None,
    conversation_id: str,
    max_steps: int,
    execute: bool,
    start_step: int = 1,
    last_result: ActionResultSummary | None = None,
    previous_proposal: PursuitProposal | None = None,
    on_step: PursuitStepCallback | None = None,
) -> AgentLoopResult:
    """Miolo comum de `agent ask`/`agent chat`/`agent pursue` (Fase 10.2).

    `Decision` continua atômica (ADR-0003 intacto): cada passo é uma proposta
    isolada, submetida à Policy Engine individualmente. Com `max_steps=1`
    (default de `ask`/`chat`) o comportamento é byte a byte o de antes da
    Fase 10.2 — inclusive a ausência de `passo N/M`/`parado: N passos
    atingidos`, impressos só quando `max_steps > 1`.

    `start_step`/`last_result`/`previous_proposal` existem para o
    `--resume` da Fase 10.5 — retomar no meio de um `agent pursue`
    interrompido, sem re-perguntar ao usuário. `on_step`, se dado, é
    chamado a cada parada/continuação com o suficiente para persistir um
    checkpoint (`jarvis.pursuits`) — `_run_agent_loop` não sabe o que quem
    chama faz com isso, só entrega o fato.

    Devolve o último `AgentTurn`/`MemoryWrite` processados, para quem chama
    (tipicamente `agent chat`) atualizar sua própria `Conversation`.
    """
    multi_step = max_steps > 1
    last_turn: AgentTurn | None = None
    last_write = MemoryWrite()
    last_outcome: ExecutionOutcome | None = None

    for step in range(start_step, max_steps + 1):
        if multi_step:
            print(f"passo       {step}/{max_steps}")
        turn = runtime.handle(
            agent_input,
            conversation=conversation,
            recent_events=recent,
            capabilities=capabilities_from(skills),
            last_action_result=last_result,
        )
        _record_decision(turn, context_as_of=context.current().as_of, store=store)
        write = _persist_memory_proposal(turn, memory_manager, provenance=USER_ASSERTION)
        submitting = execute and turn.decision.proposes_action
        _print_turn(turn, write=write, submitting=submitting)
        last_turn, last_write = turn, write

        if not turn.decision.proposes_action:
            if multi_step:
                print("agente      concluído: nada mais a propor")
            if on_step is not None:
                on_step(step, PursuitStatus.COMPLETED, last_result, previous_proposal)
            break
        if not execute:
            break

        proposal = turn.decision.action
        assert proposal is not None  # garantido por `proposes_action`
        current = (proposal.skill, proposal.parameters)
        if current == previous_proposal:
            print("agente      parado: repetiria a mesma ação")
            if on_step is not None:
                on_step(
                    step, PursuitStatus.STOPPED_REPEATED_PROPOSAL, last_result, previous_proposal
                )
            break

        outcome = _submit_proposal(
            settings, turn=turn, store=store, skills=skills, actor=Actor.USER
        )
        if outcome is None:
            break
        last_outcome = outcome
        print()
        _print_outcome(outcome)
        this_result = _result_summary(outcome)

        # Fase 11.1: o turno de reflexão (quando existe) vira `last_turn` —
        # é ele que carrega a explicação em linguagem natural, não o turno
        # cru que só propôs a ação. Mesma disciplina de persistência dos
        # demais turnos do loop; mesmo print de sempre (antes emitido pela
        # extinta `_explain_outcome`, agora inline para poder devolver o turno).
        follow_up = _reflect_on_outcome(
            runtime, outcome, conversation_id=conversation_id, recent=recent
        )
        if follow_up is not None:
            follow_up_write = _persist_memory_proposal(
                follow_up, memory_manager, provenance=USER_ASSERTION
            )
            print()
            if follow_up.decision.message is not None:
                print(f"agente      {follow_up.decision.message}")
            last_turn, last_write = follow_up, follow_up_write

        if outcome.status is ExecutionStatus.AWAITING_CONFIRMATION:
            print(
                f"agente      pausado: confirme com `jarvis action confirm {outcome.execution_id}`"
            )
            if on_step is not None:
                on_step(step, PursuitStatus.AWAITING_CONFIRMATION, this_result, current)
            break
        if outcome.status in (ExecutionStatus.DENIED, ExecutionStatus.REJECTED):
            print("agente      parado: ação negada, não insistindo")
            if on_step is not None:
                on_step(step, PursuitStatus.DENIED, this_result, current)
            break

        previous_proposal = current
        last_result = this_result
        if on_step is not None:
            on_step(step, PursuitStatus.RUNNING, last_result, previous_proposal)
        agent_input = UserMessage(
            text="Continue perseguindo o objetivo original considerando o resultado da ação.",
            at=datetime.now(UTC),
            conversation_id=conversation_id,
        )
        print()
    else:
        if multi_step:
            print(f"agente      parado: {max_steps} passos atingidos")
        if on_step is not None:
            on_step(max_steps, PursuitStatus.STOPPED_MAX_STEPS, last_result, previous_proposal)

    assert last_turn is not None  # o range roda ao menos uma vez (start_step <= max_steps)
    return AgentLoopResult(turn=last_turn, write=last_write, outcome=last_outcome)


def _agent_ask(args: argparse.Namespace, settings: Settings) -> int:
    conversation_id = args.conversation_id or new_event_id()
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        context = _prepared_context(settings, store, snapshots)
        runtime = build_agent_runtime(settings, context=context, memories=memories)
        _run_agent_loop(
            settings,
            store=store,
            context=context,
            memory_manager=build_memory_manager(memories),
            skills=skills,
            runtime=runtime,
            recent=_recent_events(store),
            agent_input=UserMessage(
                text=args.text, at=datetime.now(UTC), conversation_id=conversation_id
            ),
            conversation=None,
            conversation_id=conversation_id,
            max_steps=args.max_steps,
            execute=args.execute,
        )
    return EXIT_OK


def _agent_chat(args: argparse.Namespace, settings: Settings) -> int:
    """Multi-turno lendo a entrada padrão, uma mensagem por linha.

    Sem `input()` interativo de propósito: assim a conversa funciona tanto no
    terminal quanto com entrada redirecionada, e o teste alimenta stdin em vez
    de simular um terminal. Cada linha pode, desde a Fase 10.2, disparar até
    `--max-steps` ações antes de passar para a próxima linha.
    """
    conversation = Conversation(conversation_id=args.conversation_id or new_event_id())

    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        context = _prepared_context(settings, store, snapshots)
        runtime = build_agent_runtime(settings, context=context, memories=memories)
        recent = _recent_events(store)
        manager = build_memory_manager(memories)
        skills = build_skill_registry()

        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            now = datetime.now(UTC)
            result = _run_agent_loop(
                settings,
                store=store,
                context=context,
                memory_manager=manager,
                skills=skills,
                runtime=runtime,
                recent=recent,
                agent_input=UserMessage(
                    text=text, at=now, conversation_id=conversation.conversation_id
                ),
                conversation=conversation,
                conversation_id=conversation.conversation_id,
                max_steps=args.max_steps,
                execute=args.execute,
            )
            print()
            conversation = conversation.append(ConversationTurn(role=Role.USER, text=text, at=now))
            reply = _reply(result.turn.decision, result.write)
            if reply is not None:
                conversation = conversation.append(
                    ConversationTurn(role=Role.ASSISTANT, text=reply, at=now)
                )

        if settings.agent_session_reflection_enabled:
            _reflect_on_session(
                runtime,
                conversation=conversation,
                conversation_id=conversation.conversation_id,
                memory_manager=manager,
                store=store,
                context=context,
            )
    return EXIT_OK


def _agent_react(args: argparse.Namespace, settings: Settings) -> int:
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        recorded = store.get(args.event_id)
        if recorded is None:
            raise InvalidEventError(f"evento {args.event_id} não encontrado")
        context = _prepared_context(settings, store, snapshots)
        runtime = build_agent_runtime(settings, context=context, memories=memories)
        turn = runtime.handle(
            EventTrigger.from_recorded(recorded),
            recent_events=_recent_events(store),
            capabilities=capabilities_from(skills),
        )
        _record_decision(turn, context_as_of=context.current().as_of, store=store)
        # A afirmação não veio do usuário: veio do evento que disparou o turno.
        # `event_id` é referência resolvível no Event Store — a mesma
        # proveniência que o `MemoryEventConsumer` já grava.
        write = _persist_memory_proposal(
            turn,
            build_memory_manager(memories),
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference=recorded.event.event_id),
        )
        submitting = args.execute and turn.decision.proposes_action
        _print_turn(turn, write=write, submitting=submitting)

        if submitting:
            # `Actor.EVENT`: ninguém pediu isto. É o que faz uma skill
            # `conditional` exigir confirmação em vez de executar direto.
            outcome = _submit_proposal(
                settings, turn=turn, store=store, skills=skills, actor=Actor.EVENT
            )
            if outcome is not None:
                print()
                _print_outcome(outcome)
    return EXIT_OK


def _dump_action_result(result: ActionResultSummary | None) -> Mapping[str, JsonValue] | None:
    if result is None:
        return None
    return {
        "skill": result.skill,
        "status": result.status,
        "execution_id": result.execution_id,
        "summary": result.summary,
        "reason": result.reason,
    }


def _load_action_result(data: Mapping[str, JsonValue] | None) -> ActionResultSummary | None:
    if data is None:
        return None
    return ActionResultSummary(
        skill=str(data.get("skill", "")),
        status=str(data.get("status", "")),
        execution_id=str(data.get("execution_id", "")),
        summary=str(data.get("summary", "")),
        reason=str(data.get("reason", "")),
    )


def _dump_proposal(proposal: PursuitProposal | None) -> Mapping[str, JsonValue] | None:
    if proposal is None:
        return None
    skill, parameters = proposal
    return {"skill": skill, "parameters": dict(parameters)}


def _load_proposal(data: Mapping[str, JsonValue] | None) -> PursuitProposal | None:
    if data is None:
        return None
    skill, parameters = data.get("skill"), data.get("parameters")
    if not isinstance(skill, str) or not isinstance(parameters, Mapping):
        return None
    return (skill, parameters)


def _make_pursuit_checkpoint(
    repository: SqlitePursuitRepository, *, pursuit_id: str
) -> PursuitStepCallback:
    def on_step(
        step: int,
        status: PursuitStatus,
        last_result: ActionResultSummary | None,
        previous_proposal: PursuitProposal | None,
    ) -> None:
        repository.advance(
            pursuit_id,
            step=step,
            status=status,
            last_action_result=_dump_action_result(last_result),
            previous_proposal=_dump_proposal(previous_proposal),
            moment=datetime.now(UTC),
        )

    return on_step


def _agent_pursue(args: argparse.Namespace, settings: Settings) -> int:
    """Fase 9.2 — Goal Pursuit Loop; Fase 10.5 — checkpoint/resume.

    `Decision` continua atômica (ADR-0003 intacto): cada passo é uma proposta
    isolada, submetida à Policy Engine individualmente, como em `agent ask
    --execute`. "Planejar" aqui não é um novo tipo de decisão com uma lista de
    passos — é o composition root reinvocando `AgentRuntime.handle` com o
    `last_action_result` do passo anterior, até um dos cinco critérios de
    parada abaixo. O loop nunca insiste sozinho: confirmação pendente e
    negação de política sempre pausam, nunca são contornadas.

    A cada passo, o progresso é gravado em `PursuitState` — se o processo
    morrer no meio ou parar numa confirmação pendente, `--resume
    <pursuit_id>` retoma de onde parou (10.5), sem re-perguntar ao usuário.
    `--resume` não reconcilia o que aconteceu fora do processo enquanto ele
    esteve parado (ex. uma confirmação dada via `jarvis action confirm`) —
    retoma exatamente do último checkpoint salvo, não de um estado
    re-verificado.
    """
    if not args.resume and not args.goal:
        raise PursuitError("informe um objetivo, ou use --resume <pursuit_id>")
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
        SqlitePursuitRepository.open(pursuit_store_path(settings)) as pursuits,
    ):
        state = None
        if args.resume:
            state = pursuits.get(args.resume)
            if state is None:
                raise UnknownPursuitError(f"pursuit não encontrado: {args.resume}")
            if not state.status.is_resumable:
                raise PursuitError(
                    f"pursuit {args.resume} já concluiu ({state.status.value}); nada a retomar"
                )
            if args.max_steps is not None and args.max_steps <= state.step:
                raise PursuitError(
                    f"--max-steps ({args.max_steps}) precisa ser maior que o passo já "
                    f"atingido ({state.step})"
                )

        context = _prepared_context(settings, store, snapshots)
        runtime = build_agent_runtime(settings, context=context, memories=memories)

        if state is not None:
            pursuit_id = state.pursuit_id
            conversation_id = state.conversation_id
            max_steps = (
                args.max_steps
                if args.max_steps is not None
                else state.step + settings.agent_pursue_max_steps
            )
            start_step = state.step + 1
            last_result = _load_action_result(state.last_action_result)
            previous_proposal = _load_proposal(state.previous_proposal)
            if args.goal:
                resume_text = (
                    f"Continuando o objetivo original ('{state.goal}'), considere também "
                    f"esta orientação adicional: {args.goal}"
                )
            else:
                resume_text = (
                    f"Continuando o objetivo original ('{state.goal}'), considerando o "
                    "resultado da última ação."
                )
            agent_input: AgentInput = UserMessage(
                text=resume_text, at=datetime.now(UTC), conversation_id=conversation_id
            )
            print(f"pursuit     {pursuit_id} (retomado do passo {state.step})")
        else:
            pursuit_id = new_pursuit_id()
            conversation_id = args.conversation_id or new_event_id()
            max_steps = (
                args.max_steps if args.max_steps is not None else settings.agent_pursue_max_steps
            )
            start_step = 1
            last_result = None
            previous_proposal = None
            now = datetime.now(UTC)
            pursuits.put(
                PursuitState(
                    pursuit_id=pursuit_id,
                    goal=args.goal,
                    conversation_id=conversation_id,
                    max_steps=max_steps,
                    step=0,
                    status=PursuitStatus.RUNNING,
                    last_action_result=None,
                    previous_proposal=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            agent_input = UserMessage(text=args.goal, at=now, conversation_id=conversation_id)
            print(f"pursuit     {pursuit_id}")

        _run_agent_loop(
            settings,
            store=store,
            context=context,
            memory_manager=build_memory_manager(memories),
            skills=skills,
            runtime=runtime,
            recent=_recent_events(store),
            agent_input=agent_input,
            conversation=None,
            conversation_id=conversation_id,
            max_steps=max_steps,
            execute=True,
            start_step=start_step,
            last_result=last_result,
            previous_proposal=previous_proposal,
            on_step=_make_pursuit_checkpoint(pursuits, pursuit_id=pursuit_id),
        )
    return EXIT_OK


def _agent(args: argparse.Namespace, settings: Settings) -> int:
    if args.agent_command is None:
        args.agent_parser.print_help()
        return EXIT_OK
    if args.agent_command == "ask":
        return _agent_ask(args, settings)
    if args.agent_command == "chat":
        return _agent_chat(args, settings)
    if args.agent_command == "pursue":
        return _agent_pursue(args, settings)
    return _agent_react(args, settings)


def _print_outcome(outcome: ExecutionOutcome) -> None:
    print(f"execution   {outcome.execution_id}")
    print(f"status      {outcome.status.value}")
    print(f"skill       {outcome.skill}")
    print(f"reason      {outcome.reason or ABSENT}")
    if outcome.detail:
        print(f"detail      {outcome.detail}")
    if outcome.summary:
        print(f"summary     {outcome.summary}")
    if outcome.verdict is not None:
        verdict = outcome.verdict
        print(
            f"policy      {verdict.decision.value} via {verdict.rule_id} "
            f"(v{verdict.policy_version})"
        )
    if outcome.tools_used:
        print(f"tools       {', '.join(outcome.tools_used)}")
    if outcome.duration_ms is not None:
        print(f"duration    {outcome.duration_ms:.1f} ms")
    if outcome.expires_at is not None and outcome.status is ExecutionStatus.AWAITING_CONFIRMATION:
        print(f"expires_at  {outcome.expires_at.isoformat()}")
    if outcome.data:
        print(f"data        {json.dumps(dict(outcome.data), ensure_ascii=False)}")
    print(f"correlation {outcome.correlation_id}")


def _print_pending_row(pending: PendingAction) -> None:
    expires = pending.expires_at.isoformat() if pending.expires_at else ABSENT
    confirmed = "sim" if pending.is_confirmed else "não"
    print(
        f"{pending.execution_id}  {pending.skill:<16} {pending.actor.value:<7} "
        f"confirmada={confirmed:<4} expira={expires}"
    )


def _skills(args: argparse.Namespace, settings: Settings) -> int:
    if args.skills_command is None:
        args.skills_parser.print_help()
        return EXIT_OK

    for descriptor in build_skill_registry().list():
        print(f"{descriptor.name}")
        print(f"    {descriptor.summary}")
        print(
            f"    risco={descriptor.risk.value} "
            f"efeitos={','.join(sorted(descriptor.effects)) or ABSENT} "
            f"confirmação={descriptor.confirmation_requirement.value} "
            f"idempotência={descriptor.idempotency.value}"
        )
        print(f"    capacidades={','.join(sorted(descriptor.capabilities)) or ABSENT}")
        print(f"    tools={','.join(descriptor.required_tools) or ABSENT}")
        print(f"    parâmetros={descriptor.parameters.describe() or ABSENT}")
    return EXIT_OK


def _tools(args: argparse.Namespace, settings: Settings) -> int:
    if args.tools_command is None:
        args.tools_parser.print_help()
        return EXIT_OK

    registry = build_tool_registry(settings)
    try:
        for status in registry.statuses():
            state = "ok" if status.available else f"indisponível ({status.detail})"
            print(f"backend {status.backend_id:<16} {state}  tools={status.tool_count}")
        for descriptor in registry.list():
            print(f"{descriptor.tool_id:<32} {descriptor.summary}")
            if args.schemas:
                print(f"    parâmetros={descriptor.parameters.describe() or ABSENT}")
                if descriptor.parameters.ignored_keywords:
                    # Honestidade sobre o que não foi validado: o schema do
                    # servidor pode usar construções que não traduzimos.
                    print(f"    não validado: {', '.join(descriptor.parameters.ignored_keywords)}")
    finally:
        registry.close()
    return EXIT_OK


def _action_run(args: argparse.Namespace, settings: Settings) -> int:
    parameters = (
        _parse_json_object(args.parameters, field_name="--parameters") if args.parameters else {}
    )
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteActionRepository.open(action_store_path(settings)) as actions,
    ):
        tools = build_tool_registry(settings)
        try:
            executor = build_action_executor(
                settings, store=store, actions=actions, tools=tools, skills=skills
            )
            outcome = executor.submit(
                ActionRequest(
                    skill=args.skill,
                    parameters=parameters,
                    correlation_id=args.correlation_id or new_event_id(),
                    actor=Actor(args.actor),
                )
            )
        finally:
            tools.close()
    _print_outcome(outcome)
    return EXIT_OK


def _action_pending(settings: Settings) -> int:
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteActionRepository.open(action_store_path(settings)) as actions,
    ):
        # Registry vazio de propósito: listar pendências não executa nada, e não
        # há por que subir um MCP Server para responder "o que está esperando?".
        executor = build_action_executor(
            settings, store=store, actions=actions, tools=ToolRegistry(), skills=skills
        )
        expired = executor.expire()
        found = executor.pending()

    if expired:
        print(f"{expired} pendência(s) expiraram", file=sys.stderr)
    if not found:
        print("nenhuma ação aguardando confirmação")
        return EXIT_OK
    for pending in found:
        _print_pending_row(pending)
    return EXIT_OK


def _action_show(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteActionRepository.open(action_store_path(settings)) as actions:
        pending = actions.get(args.execution_id)

    if pending is None:
        print("execução não encontrada", file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(f"execution   {pending.execution_id}")
    print(f"skill       {pending.skill}")
    print(f"status      {pending.status.value}")
    print(f"actor       {pending.actor.value}")
    print(f"reason      {pending.reason or ABSENT}")
    print(f"requested   {pending.requested_at.isoformat()}")
    print(f"updated     {pending.updated_at.isoformat()}")
    print(f"expires_at  {pending.expires_at.isoformat() if pending.expires_at else ABSENT}")
    print(f"confirmed   {pending.confirmed_at.isoformat() if pending.confirmed_at else ABSENT}")
    print(f"correlation {pending.correlation_id}")
    print(f"decision    {pending.decision_id or ABSENT}")
    # O fingerprint, e não os parâmetros: é ele que amarra confirmação e
    # aprovação a esta execução, e é o que se compara.
    print(f"fingerprint {pending.parameters_fingerprint}")
    return EXIT_OK


def _action_answer(args: argparse.Namespace, settings: Settings, *, granted: bool) -> int:
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteActionRepository.open(action_store_path(settings)) as actions,
    ):
        pending = actions.get(args.execution_id)
        if pending is None:
            print("execução não encontrada", file=sys.stderr)
            return EXIT_INVALID_INPUT

        # A resposta do usuário entra no sistema como **evento**, e é o consumer
        # que a projeta no estado (contracts §10.2). O CLI não marca o registro
        # à mão e não executa nada aqui.
        publisher = _build_publisher(store, confirmations=ActionEventConsumer(actions))
        publisher.publish(
            confirmation_event(
                granted=granted,
                execution_id=pending.execution_id,
                parameters_fingerprint=pending.parameters_fingerprint,
                correlation_id=pending.correlation_id,
                occurred_at=datetime.now(UTC),
                causation_id=pending.causation_id,
                reason="" if granted else getattr(args, "reason", ""),
            )
        )

        if not granted:
            print(f"rejeitada   {pending.execution_id}")
            return EXIT_OK

        # Retomar é um passo separado, e ele reavalia a política do zero.
        tools = build_tool_registry(settings)
        try:
            executor = build_action_executor(
                settings, store=store, actions=actions, tools=tools, skills=skills
            )
            outcome = executor.resume(pending.execution_id)
        finally:
            tools.close()
    _print_outcome(outcome)
    return EXIT_OK


def _action(args: argparse.Namespace, settings: Settings) -> int:
    if args.action_command is None:
        args.action_parser.print_help()
        return EXIT_OK
    if args.action_command == "run":
        return _action_run(args, settings)
    if args.action_command == "pending":
        return _action_pending(settings)
    if args.action_command == "show":
        return _action_show(args, settings)
    if args.action_command == "confirm":
        return _action_answer(args, settings, granted=True)
    return _action_answer(args, settings, granted=False)


def _print_decision_row(record: DecisionRecord) -> None:
    print(
        f"{record.decided_at.isoformat()}  {record.decision_type:<14} "
        f"llm={'sim' if record.consulted_llm else 'não':<3} "
        f"correlation={record.correlation_id}  {record.reason}"
    )


def _decisions_list(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteEventStore.open(event_store_path(settings)) as store:
        events = (
            store.read_by_correlation(args.correlation_id)
            if args.correlation_id
            else store.read_by_type(DECISION_RECORDED, limit=args.limit)
        )
    records = project_decisions(events)
    if not records:
        print("nenhuma decisão encontrada")
        return EXIT_OK
    for record in records:
        _print_decision_row(record)
    return EXIT_OK


def _decisions(args: argparse.Namespace, settings: Settings) -> int:
    if args.decisions_command is None:
        args.decisions_parser.print_help()
        return EXIT_OK
    return _decisions_list(args, settings)


_AUDIT_EVENT_TYPES: Final = frozenset(item.value for item in AuditKind)
_AUDIT_DETAIL_KEYS: Final = (
    "execution_id",
    "skill",
    "actor",
    "reason",
    "rule_id",
    "decision",
    "tool_id",
    "backend_id",
)


def _audit_detail(event: Event) -> str:
    parts = [
        f"{key}={value}"
        for key in _AUDIT_DETAIL_KEYS
        if isinstance(value := event.payload.get(key), str) and value
    ]
    duration = event.payload.get("duration_ms")
    if isinstance(duration, int | float):
        parts.append(f"duration_ms={duration}")
    return " ".join(parts)


def _print_audit_row(recorded: RecordedEvent) -> None:
    print(
        f"{recorded.recorded_at.isoformat()}  {recorded.event.event_type:<32} "
        f"{_audit_detail(recorded.event)}"
    )


def _audit_show(args: argparse.Namespace, settings: Settings) -> int:
    """Lê o **mesmo** Event Store que `decisions list`/`events list` já leem —
    nenhum armazenamento novo, só uma projeção que junta decisão e trilha de
    ação numa timeline só, ordenada por `recorded_at` (ADR-0017).
    """
    with SqliteEventStore.open(event_store_path(settings)) as store:
        events = store.read_by_correlation(args.correlation_id)
    if not events:
        print("nenhum evento encontrado para essa correlação", file=sys.stderr)
        return EXIT_INVALID_INPUT

    decisions = project_decisions(events)
    if decisions:
        print("decisões")
        for record in decisions:
            _print_decision_row(record)
        print()

    print("trilha")
    audited = [recorded for recorded in events if recorded.event.event_type in _AUDIT_EVENT_TYPES]
    if not audited:
        print("nenhum marco de auditoria para essa correlação")
        return EXIT_OK
    for recorded in audited:
        _print_audit_row(recorded)
    return EXIT_OK


def _audit(args: argparse.Namespace, settings: Settings) -> int:
    if args.audit_command is None:
        args.audit_parser.print_help()
        return EXIT_OK
    return _audit_show(args, settings)


def _print_task_row(task: BackgroundTask) -> None:
    print(
        f"{task.task_id}  {task.request.skill:<16} {task.status.value:<10} "
        f"tentativas={task.attempts}/{task.max_attempts}  "
        f"próxima={task.next_attempt_at.isoformat()}"
    )


def _tasks_list(settings: Settings) -> int:
    with SqliteTaskRepository.open(task_store_path(settings)) as repository:
        found = [
            task
            for status in (TaskStatus.PENDING, TaskStatus.RETRYING, TaskStatus.RUNNING)
            for task in repository.list_by_status(status)
        ]
    if not found:
        print("nenhuma tarefa pendente")
        return EXIT_OK
    for task in found:
        _print_task_row(task)
    return EXIT_OK


def _tasks_show(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteTaskRepository.open(task_store_path(settings)) as repository:
        task = repository.get(args.task_id)
    if task is None:
        print("tarefa não encontrada", file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(f"task        {task.task_id}")
    print(f"skill       {task.request.skill}")
    print(f"status      {task.status.value}")
    print(f"tentativas  {task.attempts}/{task.max_attempts}")
    print(f"próxima     {task.next_attempt_at.isoformat()}")
    print(f"criada      {task.created_at.isoformat()}")
    print(f"atualizada  {task.updated_at.isoformat()}")
    print(f"erro        {task.last_error or ABSENT}")
    print(f"correlation {task.request.correlation_id}")
    return EXIT_OK


def _tasks_cancel(args: argparse.Namespace, settings: Settings) -> int:
    with SqliteTaskRepository.open(task_store_path(settings)) as repository:
        manager = build_task_manager(settings, repository=repository)
        cancelled = manager.cancel(args.task_id)
    print(f"cancelada   {cancelled.task_id}")
    return EXIT_OK


def _make_task_outcome_callback(
    settings: Settings,
    *,
    store: SqliteEventStore,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
    bus: EventBus | None = None,
) -> Callable[[BackgroundTask, ExecutionOutcome], None]:
    """Fase 9.1: fecha o loop `observe result` para o Background Task Manager.

    `task.request.correlation_id` dobra de `conversation_id` — mesma
    convenção de `VoiceSession` (Fase 6.4): a cadeia causal inteira de uma
    tarefa já é uma conversa de um só assunto.
    """
    prompt = (
        "Explique, em uma frase, o desfecho desta tarefa em background que acabou de ser tentada."
    )

    def on_outcome(task: BackgroundTask, outcome: ExecutionOutcome) -> None:
        runtime = build_agent_runtime(settings, context=context, memories=memories)
        follow_up = _reflect_on_outcome(
            runtime,
            outcome,
            conversation_id=task.request.correlation_id,
            recent=_recent_events(store),
            prompt=prompt,
        )
        if follow_up is None:
            return
        _record_decision(follow_up, context_as_of=context.current().as_of, store=store, bus=bus)

    return on_outcome


def _tasks_run_due(settings: Settings) -> int:
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
        SqliteActionRepository.open(action_store_path(settings)) as actions,
        SqliteTaskRepository.open(task_store_path(settings)) as repository,
    ):
        context = _prepared_context(settings, store, snapshots)
        on_outcome = _make_task_outcome_callback(
            settings, store=store, context=context, memories=memories
        )
        tools = build_tool_registry(settings)
        try:
            executor = build_action_executor(
                settings, store=store, actions=actions, tools=tools, skills=skills
            )
            manager = build_task_manager(settings, repository=repository)
            settled = manager.run_due(executor=executor, on_outcome=on_outcome)
        finally:
            tools.close()
    if not settled:
        print("nenhuma tarefa devida")
        return EXIT_OK
    for task in settled:
        _print_task_row(task)
    return EXIT_OK


def _tasks(args: argparse.Namespace, settings: Settings) -> int:
    if args.tasks_command is None:
        args.tasks_parser.print_help()
        return EXIT_OK
    if args.tasks_command == "list":
        return _tasks_list(settings)
    if args.tasks_command == "show":
        return _tasks_show(args, settings)
    if args.tasks_command == "cancel":
        return _tasks_cancel(args, settings)
    return _tasks_run_due(settings)


def _voice_devices() -> int:
    """Mesma tradução de `ImportError` de `build_audio_io`: sem o extra
    `voice` instalado, a mensagem precisa ser explícita, não um traceback de
    `ModuleNotFoundError` (achado da revisão de release da 8.10)."""
    try:
        from jarvis.voice.adapters.sounddevice_audio import list_devices
    except ImportError as error:
        raise AudioDeviceError(
            "áudio indisponível: instale o extra com `uv sync --extra voice`"
        ) from error

    devices = list_devices()
    if not devices:
        print("nenhum dispositivo de áudio encontrado")
        return EXIT_OK
    for device in devices:
        kind = []
        if device.max_input_channels:
            kind.append("entrada")
        if device.max_output_channels:
            kind.append("saída")
        print(
            f"{device.index:<4} {device.name:<44} {'/'.join(kind) or '-':<16} "
            f"{device.default_sample_rate:.0f} Hz"
        )
    return EXIT_OK


def _voice_say(args: argparse.Namespace, settings: Settings) -> int:
    clip = build_tts(settings).synthesize(args.text, timeout_seconds=settings.tts_timeout_seconds)
    if args.out:
        destination = Path(args.out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encode_wav(clip))
        print(f"gravado    {destination}")
        print(f"duração    {clip.duration_seconds:.2f}s")
        return EXIT_OK

    _, sink = build_audio_io(settings)
    try:
        result = sink.play(clip)
    finally:
        sink.close()
    print(f"falado     {result.played_seconds:.2f}s")
    return EXIT_OK


def _voice_transcribe(args: argparse.Namespace, settings: Settings) -> int:
    source = Path(args.path)
    if not source.is_file():
        raise InvalidVoiceInputError(f"arquivo não encontrado: {source}")

    clip = decode_wav(source.read_bytes())
    transcript = build_stt(settings).transcribe(
        clip,
        language=settings.stt_language or None,
        timeout_seconds=settings.stt_timeout_seconds,
    )
    print(f"duração    {clip.duration_seconds:.2f}s")
    print(f"texto      {transcript.text or '(silêncio)'}")
    return EXIT_OK


def _print_voice_session(session: VoiceSession) -> None:
    print(f"session_id  {session.session_id}")
    print(f"started_at  {session.started_at.isoformat()}")
    print(f"ended_at    {session.ended_at.isoformat() if session.ended_at else ABSENT}")
    print(f"reason      {session.ended_reason or ABSENT}")
    print(f"turns       {session.turn_count}")
    for turn in session.turns:
        speaker = "você  " if turn.role.value == "user" else "jarvis"
        print(f"  {turn.at.isoformat()}  {speaker}  {turn.text}")


def _voice_sessions(args: argparse.Namespace, settings: Settings) -> int:
    command = args.sessions_command or "list"
    with SqliteVoiceSessionRepository.open(voice_store_path(settings)) as sessions:
        if command == "show":
            found = sessions.get(args.session_id)
            if found is None:
                print("sessão não encontrada", file=sys.stderr)
                return EXIT_INVALID_INPUT
            _print_voice_session(found)
            return EXIT_OK

        if command == "purge":
            if args.all:
                # Retenção zero apaga tudo: o corte é "agora".
                print(f"apagadas {sessions.purge_before(datetime.now(UTC))} sessão(ões)")
                return EXIT_OK
            if not args.session_id:
                raise InvalidVoiceInputError("informe um session_id ou use --all")
            removed = sessions.purge(args.session_id)
            print(f"apagada {args.session_id}" if removed else "sessão não encontrada")
            return EXIT_OK

        found_all = sessions.list(
            limit=args.limit if hasattr(args, "limit") else DEFAULT_LIST_LIMIT
        )

    if not found_all:
        print("nenhuma sessão de voz registrada")
        return EXIT_OK
    for session in found_all:
        print(
            f"{session.session_id}  {session.started_at.isoformat()}  "
            f"turnos={session.turn_count:<3} {session.ended_reason or 'aberta'}"
        )
    return EXIT_OK


@dataclass(slots=True)
class ProactivityRuntime:
    """O que `jarvis run` monta uma vez e mantém pelo processo inteiro (Fase 7.7).

    `bus` é o EventBus compartilhado que faz sessão de voz, decisão e
    confirmação alcançarem o Trigger Engine (7.1) e o Conditional Trigger
    (7.6) — construído e assinado uma única vez em `_build_proactivity`,
    nunca recriado por chamada (ao contrário de `_build_publisher(store)`
    nos comandos de tiro único).
    """

    bus: EventBus
    notifications: NotificationManager
    task_manager: TaskManager


def _notification_from_turn(turn: AgentTurn, *, event: RecordedEvent) -> Notification | None:
    """Só decisões com mensagem viram notificação — `ignore`/`remember`/`act`
    puro não têm nada a dizer ao usuário. `subject` é o `event_type`: é o que
    a Interruption Policy usa para o cooldown (duas ocorrências do mesmo tipo
    de evento em sequência não repetem a interrupção)."""
    decision = turn.decision
    if decision.message is None:
        return None
    high_importance = turn.importance is not None and turn.importance.total >= 0.8
    return Notification(
        notification_id=decision.decision_id,
        subject=event.event.event_type,
        title="Jarvis",
        body=decision.message,
        priority=NotificationPriority.HIGH if high_importance else NotificationPriority.NORMAL,
        correlation_id=decision.correlation_id,
        created_at=decision.decided_at,
    )


def _make_trigger_callback(
    settings: Settings,
    *,
    store: SqliteEventStore,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
    skills: SkillRegistry,
    actions: SqliteActionRepository,
    proactivity: ProactivityRuntime,
) -> Callable[[RecordedEvent, TriggerRule], None]:
    """O caminho 7.1: evento casado → Agent Runtime → decisão → notificação e,
    se `proactivity_execute_actions`, submissão via `ActionExecutor`.

    Reproduz exatamente o corpo de `_agent_react`, com duas diferenças: nada
    vai para stdout (ninguém está olhando o terminal de um processo
    autônomo), e a decisão é entregue ao `NotificationManager` em vez de
    impressa.
    """

    def on_match(event: RecordedEvent, rule: TriggerRule) -> None:
        runtime = build_agent_runtime(settings, context=context, memories=memories)
        turn = runtime.handle(
            EventTrigger.from_recorded(event),
            recent_events=_recent_events(store),
            capabilities=capabilities_from(skills),
        )
        _record_decision(
            turn, context_as_of=context.current().as_of, store=store, bus=proactivity.bus
        )
        _persist_memory_proposal(
            turn,
            build_memory_manager(memories),
            provenance=Provenance(origin=MemoryOrigin.EVENT, reference=event.event.event_id),
        )

        notification = _notification_from_turn(turn, event=event)
        if notification is not None:
            proactivity.notifications.notify(
                notification,
                importance=turn.importance.total if turn.importance is not None else 1.0,
                context=context.current(),
            )

        if settings.proactivity_execute_actions and turn.decision.proposes_action:
            proposal = turn.decision.action
            assert proposal is not None  # garantido por `proposes_action`
            tools = build_tool_registry(settings)
            try:
                executor = build_action_executor(
                    settings, store=store, actions=actions, tools=tools, skills=skills
                )
                # `Actor.EVENT`: ninguém pediu isto — mesma convenção de `agent react`.
                outcome = executor.submit(
                    ActionRequest(
                        skill=proposal.skill,
                        parameters=dict(proposal.parameters),
                        correlation_id=turn.decision.correlation_id,
                        actor=Actor.EVENT,
                        decision_id=turn.decision.decision_id,
                        causation_id=turn.decision.causation_id,
                    )
                )
            finally:
                tools.close()

            # Fase 9.1: fecha o loop `observe result` também no caminho
            # proativo — uma negação/falha vira uma segunda decisão, que pode
            # gerar sua própria notificação, exatamente como o sucesso já faz.
            follow_up = _reflect_on_outcome(
                runtime,
                outcome,
                conversation_id=turn.decision.correlation_id,
                recent=_recent_events(store),
            )
            if follow_up is not None:
                _record_decision(
                    follow_up,
                    context_as_of=context.current().as_of,
                    store=store,
                    bus=proactivity.bus,
                )
                follow_up_notification = _notification_from_turn(follow_up, event=event)
                if follow_up_notification is not None:
                    proactivity.notifications.notify(
                        follow_up_notification,
                        importance=(
                            follow_up.importance.total if follow_up.importance is not None else 1.0
                        ),
                        context=context.current(),
                    )

    return on_match


def _make_condition_callback(
    settings: Settings,
    *,
    store: SqliteEventStore,
    actions: SqliteActionRepository,
    skills: SkillRegistry,
) -> Callable[[ActionRequest], None]:
    """O caminho 7.6: regra determinística casada → `ActionExecutor` direto,
    sem LLM. `ActionRequest.actor` já é `Actor.SYSTEM` (`ConditionEngine`)."""

    def on_action(request: ActionRequest) -> None:
        tools = build_tool_registry(settings)
        try:
            executor = build_action_executor(
                settings, store=store, actions=actions, tools=tools, skills=skills
            )
            executor.submit(request)
        finally:
            tools.close()

    return on_action


def _build_proactivity(
    settings: Settings,
    *,
    store: SqliteEventStore,
    actions: SqliteActionRepository,
    tasks: SqliteTaskRepository,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
    skills: SkillRegistry,
) -> ProactivityRuntime:
    """Monta o bus compartilhado de `jarvis run` e, só se
    `JARVIS_PROACTIVITY_ENABLED`, inscreve Trigger Engine e Conditional
    Trigger nele. Ver ADR-0029: autonomia real é opt-in em cada camada —
    sem o interruptor, o bus se comporta exatamente como o descartável de
    `_build_publisher(store)`, só que vive mais tempo.
    """
    bus = EventBus()
    bus.subscribe(LoggingEventConsumer())
    bus.subscribe(ActionEventConsumer(actions), event_types=CONFIRMATION_EVENT_TYPES)

    notifications = build_notification_manager(settings)
    task_manager = build_task_manager(settings, repository=tasks)
    proactivity = ProactivityRuntime(
        bus=bus, notifications=notifications, task_manager=task_manager
    )

    if not settings.proactivity_enabled:
        return proactivity

    trigger_engine = build_trigger_engine(settings)
    if trigger_engine.rules:
        on_match = _make_trigger_callback(
            settings,
            store=store,
            context=context,
            memories=memories,
            skills=skills,
            actions=actions,
            proactivity=proactivity,
        )
        bus.subscribe(TriggerEventConsumer(trigger_engine, on_match=on_match))

    # Regras condicionais executam de verdade (ADR-0016) — por isso exigem o
    # mesmo opt-in de execução que voz e CLI já exigem, não só o interruptor
    # geral. Ao contrário do Trigger Engine (que pode só notificar), uma
    # regra condicional não tem modo "só avisar".
    if settings.proactivity_execute_actions:
        condition_engine = build_condition_engine(settings)
        if condition_engine.rules:
            on_action = _make_condition_callback(
                settings, store=store, actions=actions, skills=skills
            )
            # Fase 9.3: bridge só criado aqui, no composition root — o Core
            # de `jarvis.proactivity` nunca importa `jarvis.memory` (ADR-0032).
            memory_presence = MemoryPresenceBridge(build_memory_manager(memories))
            bus.subscribe(
                ConditionalTriggerConsumer(
                    condition_engine,
                    context_reader=context.current,
                    on_action=on_action,
                    memory=memory_presence,
                )
            )

    return proactivity


def _apply_retention(settings: Settings, sessions: SqliteVoiceSessionRepository) -> None:
    """A retenção roda na inicialização, não num job: o processo residente é o
    único momento em que o Jarvis sabe que está vivo."""
    if settings.voice_retention_days <= 0:
        return
    cutoff = datetime.now(UTC) - timedelta(days=settings.voice_retention_days)
    purged = sessions.purge_before(cutoff)
    if purged:
        print(f"retenção: {purged} sessão(ões) antigas apagadas", file=sys.stderr)


def _run_resident(args: argparse.Namespace, settings: Settings) -> int:
    """`jarvis run`, `jarvis voice listen` e `jarvis panel serve` no mesmo corpo.

    O que muda entre os três é apenas quais peças sobem — e é por isso que eles
    compartilham o wiring em vez de duplicá-lo.
    """
    with_voice = not getattr(args, "no_voice", False)
    with_panel = not getattr(args, "no_panel", False)
    execute = getattr(args, "execute", False) or settings.voice_execute_actions
    skills = build_skill_registry()

    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
        SqliteActionRepository.open(action_store_path(settings)) as actions,
        SqliteVoiceSessionRepository.open(voice_store_path(settings)) as sessions,
        SqliteTaskRepository.open(task_store_path(settings)) as tasks,
    ):
        _apply_retention(settings, sessions)
        context = _prepared_context(settings, store, snapshots)
        proactivity = _build_proactivity(
            settings,
            store=store,
            actions=actions,
            tasks=tasks,
            context=context,
            memories=memories,
            skills=skills,
        )
        # Ferramentas/executor de tarefas vivem pelo processo inteiro: um
        # `ToolRegistry` novo por tick reabriria conexão MCP a cada
        # `panel_refresh_seconds` (ADR-0027 escolhe ticar, não escolhe pagar
        # esse custo).
        task_tools = build_tool_registry(settings)
        task_executor = build_action_executor(
            settings, store=store, actions=actions, tools=task_tools, skills=skills
        )
        task_outcome = _make_task_outcome_callback(
            settings, store=store, context=context, memories=memories, bus=proactivity.bus
        )

        def tick_tasks() -> None:
            proactivity.task_manager.run_due(executor=task_executor, on_outcome=task_outcome)

        tick_tasks()

        bridge = PanelBridge(
            live=LiveState(),
            service=build_observability_service(
                settings, store=store, context=context, memories=memories, actions=actions
            ),
            refresh_seconds=settings.panel_refresh_seconds,
            on_refresh=tick_tasks,
        )
        bridge.refresh()

        panel = (
            PanelServer(live=bridge.live, host=settings.panel_host, port=settings.panel_port)
            if with_panel
            else None
        )
        if panel is not None:
            panel.start()
            print(f"painel     {panel.url}")
            if settings.panel_open_browser:
                open_browser(panel.url)

        try:
            if with_voice:
                _serve_voice(
                    settings,
                    bridge=bridge,
                    store=store,
                    context=context,
                    memories=memories,
                    sessions=sessions,
                    skills=skills,
                    execute=execute,
                    proactivity=proactivity,
                )
            elif panel is not None:
                _serve_panel_only(settings, bridge=bridge, once=getattr(args, "once", False))
            else:
                print("nada a fazer: --no-voice e --no-panel juntos", file=sys.stderr)
                return EXIT_INVALID_INPUT
        except KeyboardInterrupt:
            print("\nencerrando", file=sys.stderr)
        finally:
            if panel is not None:
                panel.stop()
            task_tools.close()
    return EXIT_OK


def _serve_voice(
    settings: Settings,
    *,
    bridge: PanelBridge,
    store: SqliteEventStore,
    context: ContextEngine,
    memories: SqliteMemoryRepository,
    sessions: SqliteVoiceSessionRepository,
    skills: SkillRegistry,
    execute: bool,
    proactivity: ProactivityRuntime,
) -> None:
    stt = build_stt(settings)
    tts = build_tts(settings)
    source, sink = build_audio_io(settings)
    wake, trigger = build_wake_detector(settings, stt=stt)
    # Bus compartilhado (Fase 7.7): sessão de voz publica nele, não num bus
    # descartável — é o que faz o Trigger Engine/Conditional Trigger, já
    # inscritos em `_build_proactivity`, também verem eventos de voz.
    publisher = _build_publisher(store, bus=proactivity.bus)

    # O `NotificationManager` construído em `_build_proactivity` não tinha
    # `tts`/`sink` ainda — refeito aqui com o canal de voz, console como
    # fallback. `proactivity` é mutável de propósito: o callback do Trigger
    # Engine lê `proactivity.notifications` a cada evento, não uma vez só, e
    # por isso enxerga esta troca mesmo tendo sido montado antes dela.
    voice_state = [VoiceState.IDLE]
    proactivity.notifications = build_notification_manager(
        settings,
        voice_channel=VoiceNotificationChannel(
            tts=tts, sink=sink, can_speak_now=lambda: voice_state[0] is VoiceState.IDLE
        ),
    )

    def on_status(status: VoiceStatus) -> None:
        voice_state[0] = status.state
        bridge.on_status(status)

    voice_runtime = build_agent_runtime(settings, context=context, memories=memories)
    voice_memory_manager = build_memory_manager(memories)

    def on_session(session: VoiceSession, started: bool) -> None:
        # O fato vira evento aqui, no root: identidade e contagem, nunca conteúdo.
        publisher.publish(voice_session_event(session, started=started))
        # O evento acabou de mudar a projeção de conversa; o painel precisa vê-la.
        context.rebuild_from(store)
        bridge.on_session(session, started)
        # Fase 10.3: só ao encerrar (`started=False`), nunca ao abrir.
        if not started and settings.agent_session_reflection_enabled:
            _reflect_on_session(
                voice_runtime,
                conversation=_conversation_of(session),
                conversation_id=session.session_id,
                memory_manager=voice_memory_manager,
                store=store,
                context=context,
            )

    agent = RuntimeConversationalAgent(
        settings,
        runtime=voice_runtime,
        context=context,
        memories=memories,
        store=store,
        skills=skills,
        execute=execute,
        on_trace=bridge.on_trace,
        bus=proactivity.bus,
    )
    loop = VoiceLoop(
        source=source,
        sink=sink,
        stt=stt,
        tts=tts,
        wake=wake,
        agent=agent,
        sessions=sessions,
        settings=build_voice_settings(settings),
        on_status=on_status,
        on_session=on_session,
    )

    print(f"escutando  wake={settings.wake_strategy} execute={'sim' if execute else 'não'}")
    if settings.wake_strategy == "push_to_talk":
        print("           pressione Enter para falar; Ctrl-C encerra")
    try:
        loop.run()
    finally:
        source.close()
        sink.close()
        wake.close()
        if trigger is not None:
            trigger.stop()


def _serve_panel_only(settings: Settings, *, bridge: PanelBridge, once: bool) -> None:
    if once:
        bridge.refresh()
        return
    print("           Ctrl-C encerra")
    while True:
        bridge.refresh()
        time.sleep(settings.panel_refresh_seconds)


def _voice(args: argparse.Namespace, settings: Settings) -> int:
    if args.voice_command is None:
        args.voice_parser.print_help()
        return EXIT_OK
    if args.voice_command == "devices":
        return _voice_devices()
    if args.voice_command == "say":
        return _voice_say(args, settings)
    if args.voice_command == "transcribe":
        return _voice_transcribe(args, settings)
    if args.voice_command == "sessions":
        return _voice_sessions(args, settings)
    return _run_resident(args, settings)


def _panel(args: argparse.Namespace, settings: Settings) -> int:
    if args.panel_command is None:
        args.panel_parser.print_help()
        return EXIT_OK
    return _run_resident(args, settings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    settings = load_settings()
    configure_logging(settings.log_level)

    if args.command == "info":
        return _info(settings)

    try:
        if args.command == "context":
            return _context(args, settings)
        if args.command == "memory":
            return _memory(args, settings)
        if args.command == "agent":
            return _agent(args, settings)
        if args.command == "skills":
            return _skills(args, settings)
        if args.command == "tools":
            return _tools(args, settings)
        if args.command == "action":
            return _action(args, settings)
        if args.command == "decisions":
            return _decisions(args, settings)
        if args.command == "audit":
            return _audit(args, settings)
        if args.command == "tasks":
            return _tasks(args, settings)
        if args.command == "voice":
            return _voice(args, settings)
        if args.command == "panel":
            return _panel(args, settings)
        if args.command == "run":
            return _run_resident(args, settings)

        if args.events_command is None:
            args.events_parser.print_help()
            return EXIT_OK
        if args.events_command == "emit":
            return _emit(args, settings)
        return _list(args, settings)
    except (
        InvalidEventError,
        InvalidContextError,
        InvalidMemoryError,
        InvalidDecisionError,
        InvalidLLMRequestError,
        PromptTooLargeError,
        # `PolicyError` e `SkillError` são de domínio: entrada ou autorização,
        # nunca falha de infraestrutura. Negação normal não passa por aqui — ela
        # volta como `ExecutionOutcome` e é impressa com sucesso.
        PolicyError,
        SkillError,
        ExecutionError,
        InvalidPolicyVocabularyError,
        # Os `ToolError` de domínio precisam vir antes do bloco de
        # infraestrutura: `except` casa na primeira cláusula, e um schema
        # violado é entrada inválida (código 2), não indisponibilidade (código 1).
        ToolConfigurationError,
        ToolInvalidInputError,
        ToolNotFoundError,
        ToolNotPermittedError,
        # Voz e painel: entrada inválida e configuração impossível são de
        # domínio; falta de dispositivo e falha de provider são infraestrutura,
        # logo abaixo.
        VoiceError,
        InterfaceError,
        # Fase 7: proatividade, notificação, decision log e tarefas seguem a
        # mesma regra — erro de domínio é entrada/estado inválido, nunca
        # indisponibilidade.
        ProactivityError,
        NotifyError,
        DecisionLogError,
        TaskError,
        PursuitError,
    ) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except (
        EventStoreError,
        ContextSnapshotError,
        MemoryRepositoryError,
        LLMProviderError,
        ActionRepositoryError,
        ToolError,
        AudioError,
        SpeechToTextError,
        TextToSpeechError,
        VoiceRepositoryError,
        TaskRepositoryError,
        PursuitRepositoryError,
    ) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
