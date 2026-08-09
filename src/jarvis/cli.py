"""Ponto de entrada da linha de comando e composition root.

Este é o único módulo autorizado a conhecer Core, Infrastructure e Interfaces ao
mesmo tempo (ADR-0001): ele carrega a configuração, instancia os adapters concretos
(`SqliteEventStore`, `LoggingEventConsumer`) e os injeta nos serviços do Core
(`EventBus`, `EventPublisher`). Nenhum módulo do Core importa `jarvis.events.adapters`.
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

EXIT_OK = 0
EXIT_INFRASTRUCTURE_ERROR = 1
EXIT_INVALID_INPUT = 2

DEFAULT_LIST_LIMIT = 20


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

    with SqliteEventStore.open(event_store_path(settings)) as store:
        bus = EventBus()
        bus.subscribe(LoggingEventConsumer())
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
    print(f"env         {settings.env}")
    print(f"log_level   {settings.log_level}")
    print(f"data_dir    {settings.data_dir}")
    print(f"event_store {event_store_path(settings)}")
    return EXIT_OK


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

    if args.events_command is None:
        args.events_parser.print_help()
        return EXIT_OK

    try:
        if args.events_command == "emit":
            return _emit(args, settings)
        return _list(args, settings)
    except InvalidEventError as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except EventStoreError as error:
        print(f"erro: {error}", file=sys.stderr)
        return EXIT_INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
