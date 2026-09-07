"""Command-line entry point for local data lifecycle operations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from ndat.catalogue import update_catalogue
from ndat.datasets import DATASETS
from ndat.manager import DataManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ndat.data")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("fetch", "refresh"):
        action = commands.add_parser(command, help=f"{command} managed source data")
        action.add_argument("dataset", choices=DATASETS)
        action.add_argument("--season", type=int, action="append", required=True)
    commands.add_parser("status", help="inspect local data without network access")
    commands.add_parser("catalogue", help="rebuild DuckDB views over present Parquet")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    manager = DataManager()
    if arguments.command == "status":
        result = manager.status()
    elif arguments.command == "catalogue":
        result = {"views": update_catalogue(manager.config)}
    elif arguments.command == "refresh":
        result = manager.refresh(arguments.dataset, arguments.season)
    else:
        result = manager.fetch(arguments.dataset, arguments.season)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
