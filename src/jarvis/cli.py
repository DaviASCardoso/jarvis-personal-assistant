"""Ponto de entrada da linha de comando e composition root.

Este é o único módulo autorizado a conhecer Core, Infrastructure e Interfaces ao
mesmo tempo (ADR-0001): ele carrega a configuração, instancia os adapters concretos
(`SqliteEventStore`, `LoggingEventConsumer`, os Context Providers, o repositório de
snapshots, o repositório de memórias, o `EmbeddingProvider`) e os injeta nos
serviços do Core (`EventBus`, `EventPublisher`, `ContextAggregator`,
`ContextEngine`, `MemoryManager`). Nenhum módulo do Core importa
`jarvis.events.adapters`, `jarvis.context.adapters` nem `jarvis.memory.adapters`.
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from jarvis import __version__
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

EXIT_OK = 0
EXIT_INFRASTRUCTURE_ERROR = 1
EXIT_INVALID_INPUT = 2

DEFAULT_LIST_LIMIT = 20

# Duas ausências distintas, e a distinção precisa aparecer: `-` é "nunca observado",
# `(nenhum)` é "alguém observou que não há".
ABSENT = "-"
OBSERVED_ABSENCE = "(nenhum)"


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
    System funcione sem nenhum LLM configurado (`PHASE-3.md §17`). Um adapter
    de vendor real é escopo da Fase 4."""
    return MemoryManager(repository=memories, embeddings=HashingEmbeddingProvider())


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

        if args.events_command is None:
            args.events_parser.print_help()
            return EXIT_OK
        if args.events_command == "emit":
            return _emit(args, settings)
        return _list(args, settings)
    except (InvalidEventError, InvalidContextError, InvalidMemoryError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except (EventStoreError, ContextSnapshotError, MemoryRepositoryError) as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
