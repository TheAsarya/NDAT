"""Discovery and execution for NDAT's saved analysis library."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from ndat.analysis import (
    historical_threshold_events,
    positional_rank_curve,
    top_n_persistence,
)
from ndat.config import DataConfig


_MISSING = object()
_PARAMETER_TYPES = {"string", "integer", "float", "boolean", "string_list", "json_object"}


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    type: str
    description: str = ""
    default: Any = _MISSING

    @property
    def required(self) -> bool:
        return self.default is _MISSING


@dataclass(frozen=True)
class AnalysisDefinition:
    id: str
    title: str
    description: str
    tags: tuple[str, ...]
    execution: str
    parameters: tuple[ParameterDefinition, ...]
    source: Path | None = None
    callable: Callable[..., Any] | None = None


@dataclass(frozen=True)
class AnalysisExecution:
    definition: AnalysisDefinition
    parameters: Mapping[str, Any]
    tables: Mapping[str, pl.DataFrame]
    sql: str | None = None
    unsupported_components: tuple[str, ...] = ()


def _python_definitions() -> tuple[AnalysisDefinition, ...]:
    return (
        AnalysisDefinition(
            "fantasy.positional-rank-curve",
            "Positional fantasy rank curve",
            "Rank regular-season players at one or more positions with a scoring profile.",
            ("fantasy", "rank", "positional-value"),
            "python",
            (
                ParameterDefinition("season", "integer", "Season to rank"),
                ParameterDefinition("positions", "string_list", "Comma-separated positions"),
                ParameterDefinition("profile", "string", "Scoring profile", "LoB"),
            ),
            callable=positional_rank_curve,
        ),
        AnalysisDefinition(
            "persistence.top-n",
            "Top-N positional persistence",
            "Measure whether top-N players repeat after a configurable season horizon.",
            ("persistence", "fantasy", "rank"),
            "python",
            (
                ParameterDefinition("position", "string", "Canonical position"),
                ParameterDefinition("top_n", "integer", "Rank cutoff"),
                ParameterDefinition("start_season", "integer", "First source season"),
                ParameterDefinition("end_season", "integer", "Last target season"),
                ParameterDefinition("profile", "string", "Scoring profile", "LoB"),
                ParameterDefinition("horizon", "integer", "Seasons between comparisons", 1),
            ),
            callable=top_n_persistence,
        ),
        AnalysisDefinition(
            "historical.threshold-events",
            "Historical player-game threshold events",
            "Run the Stage 4 multi-predicate player-game threshold primitive.",
            ("historical", "threshold", "player-game"),
            "python",
            (
                ParameterDefinition("positions", "string_list", "Comma-separated positions"),
                ParameterDefinition("predicates", "json_object", "Numeric field-to-threshold JSON object"),
                ParameterDefinition("start_season", "integer", "First season"),
                ParameterDefinition("end_season", "integer", "Last season"),
            ),
            callable=historical_threshold_events,
        ),
    )


def _validate_definition(raw: Mapping[str, Any], metadata_path: Path) -> AnalysisDefinition:
    required = ("id", "title", "description", "execution", "source")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Malformed analysis metadata {metadata_path}: missing {', '.join(missing)}")
    if raw["execution"] != "sql":
        raise ValueError(f"Malformed analysis metadata {metadata_path}: execution must be 'sql'")
    parameters: list[ParameterDefinition] = []
    raw_parameters = raw.get("parameters", {})
    if not isinstance(raw_parameters, dict):
        raise ValueError(f"Malformed analysis metadata {metadata_path}: parameters must be a table")
    for name, details in raw_parameters.items():
        if not isinstance(details, dict) or details.get("type") not in _PARAMETER_TYPES:
            raise ValueError(f"Malformed parameter {name!r} in {metadata_path}")
        parameters.append(
            ParameterDefinition(
                name,
                details["type"],
                details.get("description", ""),
                details.get("default", _MISSING),
            )
        )
    source = (metadata_path.parent / raw["source"]).resolve()
    if not source.is_file() or source.suffix.lower() != ".sql":
        raise ValueError(f"Malformed analysis metadata {metadata_path}: SQL source not found: {source}")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"Malformed analysis metadata {metadata_path}: tags must be strings")
    return AnalysisDefinition(
        raw["id"], raw["title"], raw["description"], tuple(tags), "sql",
        tuple(parameters), source=source,
    )


def discover(config: DataConfig | None = None) -> dict[str, AnalysisDefinition]:
    """Discover tracked SQL metadata and registered Python analyses."""
    config = config or DataConfig.from_project()
    definitions = list(_python_definitions())
    query_root = config.project_root / "queries"
    for metadata_path in sorted(query_root.rglob("*.analysis.toml")) if query_root.exists() else ():
        try:
            raw = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"Malformed analysis metadata {metadata_path}: {error}") from error
        definitions.append(_validate_definition(raw, metadata_path))
    found: dict[str, AnalysisDefinition] = {}
    for definition in definitions:
        if definition.id in found:
            raise ValueError(f"Duplicate analysis ID: {definition.id}")
        found[definition.id] = definition
    return dict(sorted(found.items()))


def parse_parameters(
    definition: AnalysisDefinition, values: Mapping[str, str]
) -> dict[str, Any]:
    """Validate CLI values and convert them to declared parameter types."""
    declared = {parameter.name: parameter for parameter in definition.parameters}
    unknown = sorted(set(values) - set(declared))
    if unknown:
        raise ValueError(f"Unknown parameter(s): {', '.join(unknown)}")
    converted: dict[str, Any] = {}
    missing: list[str] = []
    for name, parameter in declared.items():
        if name not in values:
            if parameter.required:
                missing.append(name)
            else:
                converted[name] = parameter.default
            continue
        value = values[name]
        try:
            if parameter.type == "string":
                converted[name] = value
            elif parameter.type == "integer":
                converted[name] = int(value)
            elif parameter.type == "float":
                converted[name] = float(value)
            elif parameter.type == "boolean":
                normalized = value.lower()
                if normalized not in {"true", "false"}:
                    raise ValueError("expected true or false")
                converted[name] = normalized == "true"
            elif parameter.type == "string_list":
                converted[name] = [item.strip() for item in value.split(",") if item.strip()]
                if not converted[name]:
                    raise ValueError("expected a comma-separated non-empty list")
            else:
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError("expected a JSON object")
                converted[name] = parsed
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid value for {name!r} ({parameter.type}): {value!r}") from error
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")
    return converted


def _frame_from_cursor(connection: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    names = [description[0] for description in connection.description]
    return pl.DataFrame(connection.fetchall(), schema=names, orient="row")


def _adapt_python_result(result: Any) -> tuple[dict[str, pl.DataFrame], str | None, tuple[str, ...]]:
    if not is_dataclass(result):
        raise TypeError(f"Python analysis returned unsupported result type: {type(result).__name__}")
    tables = {
        field.name: value
        for field in fields(result)
        if isinstance((value := getattr(result, field.name)), pl.DataFrame)
    }
    if not tables:
        raise TypeError("Python analysis returned no tabular results")
    return tables, getattr(result, "sql", None), tuple(getattr(result, "unsupported_components", ()))


def run_analysis(
    definition: AnalysisDefinition,
    values: Mapping[str, str],
    connection: duckdb.DuckDBPyConnection,
) -> AnalysisExecution:
    """Execute a definition using an NDAT-owned connection."""
    parameters = parse_parameters(definition, values)
    if definition.execution == "sql":
        assert definition.source is not None
        sql = definition.source.read_text(encoding="utf-8")
        connection.execute(sql, parameters)
        tables = {"rows": _frame_from_cursor(connection)}
        unsupported: tuple[str, ...] = ()
    else:
        assert definition.callable is not None
        result = definition.callable(connection, **parameters)
        tables, sql, unsupported = _adapt_python_result(result)
    return AnalysisExecution(definition, parameters, tables, sql, unsupported)


def definition_for_sql_file(path: Path) -> AnalysisDefinition:
    """Build an ad-hoc definition for direct, non-parameterised SQL execution."""
    source = path.resolve()
    if not source.is_file() or source.suffix.lower() != ".sql":
        raise ValueError(f"SQL file not found: {path}")
    return AnalysisDefinition(
        f"file:{source.stem}", source.stem.replace("_", " ").title(),
        "Direct SQL file execution", (), "sql", (), source=source,
    )
