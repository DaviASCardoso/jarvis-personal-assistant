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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jarvis import __version__
from jarvis.agent import (
    ActionResultSummary,
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
from jarvis.context.adapters.sqlite_snapshots import SqliteContextSnapshotRepository
from jarvis.context.adapters.time_provider import SystemTimeProvider
from jarvis.context.consumer import CONTEXT_EVENT_TYPES
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
from jarvis.skills import SkillError, SkillRegistry
from jarvis.skills.builtin import register_builtin_skills
from jarvis.tools import (
    ToolError,
    ToolInvalidInputError,
    ToolNotFoundError,
    ToolNotPermittedError,
    ToolRegistry,
    ToolRetryPolicy,
    ToolRouter,
)
from jarvis.tools.adapters.local_backend import LocalToolBackend
from jarvis.tools.adapters.mcp_client import McpToolBackend
from jarvis.tools.adapters.mcp_config import load_mcp_config
from jarvis.tools.errors import ToolConfigurationError

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


def build_context_engine(snapshots: SqliteContextSnapshotRepository) -> ContextEngine:
    """Monta o Context Engine com os providers que têm dado local de verdade.

    Activity, Calendar e Location não entram: exigiriam integração externa que
    esta fase não implementa, e um provider de valor declarado aqui pareceria
    funcionalidade pronta sem ser.
    """
    aggregator = ContextAggregator(providers=[SystemTimeProvider(), LocalDeviceProvider()])
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
    """Backend local sempre; MCP Servers só se houver `mcp.json`.

    A descoberta acontece aqui, na borda. Um servidor indisponível não derruba o
    processo — vira um backend degradado, visível em `jarvis tools list`, e as
    Skills que dependiam dele passam a ser negadas pelo Policy Engine com
    `required_tool_unavailable` em vez de falhar no meio da execução.
    """
    registry = ToolRegistry()
    registry.register_backend(LocalToolBackend(root=settings.file_skill_root))
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
    store: SqliteEventStore, *, confirmations: ActionEventConsumer | None = None
) -> EventPublisher:
    bus = EventBus()
    bus.subscribe(LoggingEventConsumer())
    if confirmations is not None:
        bus.subscribe(confirmations, event_types=CONFIRMATION_EVENT_TYPES)
    return EventPublisher(store=store, bus=bus)


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

    chat = agent_actions.add_parser(
        "chat", help="Conversa multi-turno lendo uma mensagem por linha da entrada padrão."
    )
    chat.add_argument("--conversation-id")

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
        bus.subscribe(build_context_engine(snapshots).consumer, event_types=CONTEXT_EVENT_TYPES)
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
    print(f"workspace     {settings.file_skill_root}")
    print(f"mcp_config    {settings.mcp_config_path or ABSENT}")
    # A política efetiva não deve ser adivinhada: ela é a diferença entre uma
    # ação permitida e uma negada, e vive em variáveis de ambiente.
    print(f"policy        {build_policy_rules(settings).describe()}")
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
        engine = build_context_engine(snapshots)
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
                engine = build_context_engine(snapshots)
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
    store: SqliteEventStore, snapshots: SqliteContextSnapshotRepository
) -> ContextEngine:
    """A projeção é derivada: um processo novo a reconstrói antes de raciocinar
    sobre ela. Quem reconstrói é o composition root — o Agent Runtime recebe
    contexto pronto e nunca conhece o Event Store (contracts §3.4)."""
    engine = build_context_engine(snapshots)
    engine.rebuild_from(store)
    engine.refresh()
    return engine


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


def _explain_outcome(
    runtime: AgentRuntime,
    outcome: ExecutionOutcome,
    *,
    conversation_id: str,
    recent: tuple[EventSummary, ...],
) -> None:
    """Segundo turno de raciocínio — só quando a execução **não** deu certo.

    Em `act_and_notify` bem-sucedido a mensagem do agente já existe, e pagar uma
    chamada extra ao modelo para reformular o que já foi dito é desperdício de
    quota. Já uma negação ou uma falha merecem uma frase em linguagem natural, e
    é aí que o "observe result" do loop se fecha.
    """
    if outcome.status is ExecutionStatus.COMPLETED:
        return
    print()
    follow_up = runtime.handle(
        UserMessage(
            text="Explique ao usuário, em uma frase, o desfecho da ação que acabou de ser tentada.",
            at=datetime.now(UTC),
            conversation_id=conversation_id,
        ),
        recent_events=recent,
        last_action_result=ActionResultSummary(
            skill=outcome.skill,
            status=outcome.status.value,
            execution_id=outcome.execution_id,
            summary=outcome.summary,
            reason=outcome.reason,
        ),
    )
    if follow_up.decision.message is not None:
        print(f"agente      {follow_up.decision.message}")


def _agent_ask(args: argparse.Namespace, settings: Settings) -> int:
    conversation_id = args.conversation_id or new_event_id()
    skills = build_skill_registry()
    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        runtime = build_agent_runtime(
            settings, context=_prepared_context(store, snapshots), memories=memories
        )
        recent = _recent_events(store)
        turn = runtime.handle(
            UserMessage(text=args.text, at=datetime.now(UTC), conversation_id=conversation_id),
            recent_events=recent,
            capabilities=capabilities_from(skills),
        )
        write = _persist_memory_proposal(
            turn, build_memory_manager(memories), provenance=USER_ASSERTION
        )
        submitting = args.execute and turn.decision.proposes_action
        _print_turn(turn, write=write, submitting=submitting)

        if submitting:
            outcome = _submit_proposal(
                settings, turn=turn, store=store, skills=skills, actor=Actor.USER
            )
            if outcome is not None:
                print()
                _print_outcome(outcome)
                _explain_outcome(runtime, outcome, conversation_id=conversation_id, recent=recent)
    return EXIT_OK


def _agent_chat(args: argparse.Namespace, settings: Settings) -> int:
    """Multi-turno lendo a entrada padrão, uma mensagem por linha.

    Sem `input()` interativo de propósito: assim a conversa funciona tanto no
    terminal quanto com entrada redirecionada, e o teste alimenta stdin em vez
    de simular um terminal.
    """
    conversation = Conversation(conversation_id=args.conversation_id or new_event_id())

    with (
        SqliteEventStore.open(event_store_path(settings)) as store,
        SqliteContextSnapshotRepository.open(context_store_path(settings)) as snapshots,
        SqliteMemoryRepository.open(memory_store_path(settings)) as memories,
    ):
        runtime = build_agent_runtime(
            settings, context=_prepared_context(store, snapshots), memories=memories
        )
        recent = _recent_events(store)
        manager = build_memory_manager(memories)

        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            now = datetime.now(UTC)
            turn = runtime.handle(
                UserMessage(text=text, at=now, conversation_id=conversation.conversation_id),
                conversation=conversation,
                recent_events=recent,
            )
            write = _persist_memory_proposal(turn, manager, provenance=USER_ASSERTION)
            _print_turn(turn, write=write)
            print()
            conversation = conversation.append(ConversationTurn(role=Role.USER, text=text, at=now))
            reply = _reply(turn.decision, write)
            if reply is not None:
                conversation = conversation.append(
                    ConversationTurn(role=Role.ASSISTANT, text=reply, at=now)
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
        runtime = build_agent_runtime(
            settings, context=_prepared_context(store, snapshots), memories=memories
        )
        turn = runtime.handle(
            EventTrigger.from_recorded(recorded),
            recent_events=_recent_events(store),
            capabilities=capabilities_from(skills),
        )
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


def _agent(args: argparse.Namespace, settings: Settings) -> int:
    if args.agent_command is None:
        args.agent_parser.print_help()
        return EXIT_OK
    if args.agent_command == "ask":
        return _agent_ask(args, settings)
    if args.agent_command == "chat":
        return _agent_chat(args, settings)
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
    ) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
