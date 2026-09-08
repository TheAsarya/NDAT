"""Command-line discovery and execution for saved NDAT analyses."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TextIO
import sys

import duckdb
import polars as pl

from ndat.config import DataConfig
from ndat.library import (
    AnalysisDefinition,
    AnalysisExecution,
    definition_for_sql_file,
    discover,
    run_analysis,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ndat.query")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List available analyses")
    show = subparsers.add_parser("show", help="Inspect one analysis")
    show.add_argument("analysis_id")
    run = subparsers.add_parser("run", help="Run an analysis by ID or SQL path")
    run.add_argument("target")
    run.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    return parser


def _values(items: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in items:
        if "=" not in item or not item.split("=", 1)[0]:
            raise ValueError(f"Invalid --param {item!r}; expected NAME=VALUE")
        name, value = item.split("=", 1)
        if name in values:
            raise ValueError(f"Duplicate parameter: {name}")
        values[name] = value
    return values


def _show(definition: AnalysisDefinition, output: TextIO) -> None:
    print(f"{definition.id} - {definition.title}", file=output)
    print(definition.description, file=output)
    print(f"Execution: {definition.execution}", file=output)
    print(f"Tags: {', '.join(definition.tags) or '-'}", file=output)
    if definition.source:
        print(f"Source: {definition.source}", file=output)
    print("Parameters:", file=output)
    if not definition.parameters:
        print("  (none)", file=output)
    for parameter in definition.parameters:
        default = "required" if parameter.required else f"default={parameter.default!r}"
        print(f"  {parameter.name} ({parameter.type}, {default}) - {parameter.description}", file=output)


def _print_frame(name: str, frame: pl.DataFrame, output: TextIO) -> None:
    print(f"\n[{name}]", file=output)
    if frame.is_empty():
        columns = ", ".join(frame.columns) or "no columns"
        print(f"No rows. Columns: {columns}", file=output)
    else:
        with pl.Config(
            tbl_rows=30,
            tbl_cols=20,
            tbl_width_chars=220,
            tbl_formatting="ASCII_FULL_CONDENSED",
        ):
            print(frame, file=output)


def _print_execution(execution: AnalysisExecution, output: TextIO) -> None:
    print(f"Analysis: {execution.definition.id}", file=output)
    print(f"Execution: {execution.definition.execution}", file=output)
    print(f"Parameters: {dict(execution.parameters)}", file=output)
    if execution.unsupported_components:
        print(f"Unsupported scoring components: {', '.join(execution.unsupported_components)}", file=output)
    for name, table in execution.tables.items():
        _print_frame(name, table, output)


def main(
    argv: list[str] | None = None,
    *,
    config: DataConfig | None = None,
    output: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    config = config or DataConfig.from_project()
    arguments = _parser().parse_args(argv)
    definitions = discover(config)
    if arguments.command == "list":
        print("ID | Type | Title", file=output)
        for definition in definitions.values():
            print(f"{definition.id} | {definition.execution} | {definition.title}", file=output)
        return 0
    if arguments.command == "show":
        if arguments.analysis_id not in definitions:
            raise ValueError(f"Analysis not found: {arguments.analysis_id}")
        _show(definitions[arguments.analysis_id], output)
        return 0
    target = arguments.target
    definition = definitions.get(target)
    if definition is None:
        path = Path(target)
        if path.suffix.lower() != ".sql":
            raise ValueError(f"Analysis not found: {target}")
        definition = definition_for_sql_file(path)
    if not config.catalogue_path.exists():
        raise ValueError(
            f"NDAT catalogue not found at {config.catalogue_path}; fetch data or run `python -m ndat.data catalogue`"
        )
    with duckdb.connect(str(config.catalogue_path), read_only=True) as connection:
        execution = run_analysis(definition, _values(arguments.param), connection)
    _print_execution(execution, output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, duckdb.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
