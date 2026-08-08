"""Ponto de entrada da linha de comando.

Nesta fase o CLI serve apenas para verificar que o projeto está instalado e
configurado corretamente. Comandos reais serão adicionados junto das
funcionalidades correspondentes.
"""

import argparse
from collections.abc import Sequence

from jarvis import __version__
from jarvis.config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Agente pessoal de IA.")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("info", help="Mostra a configuração efetiva.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    settings = load_settings()
    print(f"jarvis {__version__}")
    print(f"env       {settings.env}")
    print(f"log_level {settings.log_level}")
    print(f"data_dir  {settings.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
