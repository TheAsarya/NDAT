from __future__ import annotations

from io import StringIO
from pathlib import Path

import duckdb
import pytest

from ndat.config import DataConfig
from ndat.library import (
    AnalysisDefinition,
    ParameterDefinition,
    discover,
    parse_parameters,
    run_analysis,
)
from ndat.query import main
from ndat.scoring import PLAYER_STATS_MAPPINGS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def fixture_connection(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(path) if path else ":memory:")
    stat_fields = sorted(
        {field for mapping in PLAYER_STATS_MAPPINGS.values() for field in mapping.fields}
    )
    columns = [
        "season INTEGER", "week INTEGER", "game_id VARCHAR", "player_id VARCHAR",
        "player_display_name VARCHAR", "raw_position VARCHAR",
        "canonical_position VARCHAR", "team VARCHAR", "season_type VARCHAR",
        *(f'"{field}" DOUBLE' for field in stat_fields),
    ]
    connection.execute(f"CREATE TABLE player_game ({', '.join(columns)})")
    base_columns = [
        "season", "week", "game_id", "player_id", "player_display_name",
        "raw_position", "canonical_position", "team", "receiving_yards",
        "receiving_tds",
    ]
    rows = [
        (2020, 1, "g1", "te1", "Tight One", "TE", "TE", "A", 110, 2),
        (2020, 2, "g2", "te2", "Tight Two", "TE", "TE", "B", 20, 0),
        (2021, 1, "g3", "te1", "Tight One", "TE", "TE", "A", 120, 2),
        (2021, 1, "g4", "te3", "Tight Three", "TE", "TE", "C", 80, 1),
        (2020, 1, "g5", "wr1", "Wide One", "WR", "WR", "D", 130, 2),
        (2021, 1, "g6", "wr1", "Wide One", "WR", "WR", "D", 100, 1),
    ]
    for row in rows:
        values = dict(zip(base_columns, row, strict=True))
        values["season_type"] = "REG"
        for field in stat_fields:
            values.setdefault(field, 0)
        names = list(values)
        connection.execute(
            f"INSERT INTO player_game ({', '.join(f'\"{name}\"' for name in names)}) "
            f"VALUES ({', '.join('?' for _ in names)})",
            list(values.values()),
        )
    return connection


def config_for(tmp_path: Path, *, project_root: Path | None = None) -> DataConfig:
    return DataConfig.from_project(
        project_root=project_root or tmp_path,
        data_root=tmp_path / "data",
        catalogue_path=tmp_path / "data" / "fixture.duckdb",
    )


def write_sql_definition(root: Path, analysis_id: str, sql: str = "SELECT 1 AS value") -> None:
    query_dir = root / "queries" / "test"
    query_dir.mkdir(parents=True, exist_ok=True)
    (query_dir / "query.sql").write_text(sql, encoding="utf-8")
    (query_dir / "query.analysis.toml").write_text(
        f'''id = "{analysis_id}"
title = "Fixture query"
description = "A fixture"
execution = "sql"
source = "query.sql"
tags = ["test"]

[parameters.limit]
type = "integer"
description = "Fixture limit"
default = 5
''',
        encoding="utf-8",
    )


def test_discovery_combines_saved_sql_and_registered_python(tmp_path: Path) -> None:
    write_sql_definition(tmp_path, "test.fixture")

    definitions = discover(config_for(tmp_path))

    assert definitions["test.fixture"].execution == "sql"
    assert definitions["test.fixture"].source == (
        tmp_path / "queries" / "test" / "query.sql"
    ).resolve()
    assert definitions["test.fixture"].parameters[0].default == 5
    assert definitions["fantasy.positional-rank-curve"].execution == "python"
    assert definitions["persistence.top-n"].callable is not None


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    write_sql_definition(tmp_path, "persistence.top-n")
    with pytest.raises(ValueError, match="Duplicate analysis ID"):
        discover(config_for(tmp_path))


@pytest.mark.parametrize(
    "metadata",
    [
        "title = 'Missing fields'",
        "id='bad'\ntitle='Bad'\ndescription='Bad'\nexecution='python'\nsource='query.sql'",
        "id='bad'\ntitle='Bad'\ndescription='Bad'\nexecution='sql'\nsource='missing.sql'",
    ],
)
def test_malformed_definitions_are_rejected(tmp_path: Path, metadata: str) -> None:
    query_dir = tmp_path / "queries"
    query_dir.mkdir()
    (query_dir / "query.sql").write_text("SELECT 1", encoding="utf-8")
    (query_dir / "bad.analysis.toml").write_text(metadata, encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed analysis metadata"):
        discover(config_for(tmp_path))


def test_parameter_defaults_types_and_validation() -> None:
    definition = AnalysisDefinition(
        "test", "Test", "Test", (), "sql",
        (
            ParameterDefinition("count", "integer"),
            ParameterDefinition("enabled", "boolean", default=True),
            ParameterDefinition("positions", "string_list", default=["TE"]),
            ParameterDefinition("filters", "json_object", default={}),
        ),
    )
    assert parse_parameters(
        definition,
        {"count": "3", "enabled": "false", "positions": "TE, WR", "filters": '{"x": 1}'},
    ) == {"count": 3, "enabled": False, "positions": ["TE", "WR"], "filters": {"x": 1}}
    with pytest.raises(ValueError, match="Missing required"):
        parse_parameters(definition, {})
    with pytest.raises(ValueError, match="Unknown parameter"):
        parse_parameters(definition, {"count": "3", "other": "x"})
    with pytest.raises(ValueError, match="Invalid value"):
        parse_parameters(definition, {"count": "three"})


def test_sql_parameters_are_bound_not_interpolated(tmp_path: Path) -> None:
    source = tmp_path / "safe.sql"
    source.write_text("SELECT $value AS supplied", encoding="utf-8")
    definition = AnalysisDefinition(
        "safe", "Safe", "Safe", (), "sql",
        (ParameterDefinition("value", "string"),), source=source,
    )
    malicious = "TE' OR 1=1 --"

    result = run_analysis(definition, {"value": malicious}, duckdb.connect(":memory:"))

    assert result.tables["rows"].item() == malicious
    assert result.sql == "SELECT $value AS supplied"


def test_saved_historical_sql_includes_frequency_and_rows() -> None:
    definition = discover(DataConfig.from_project())["historical.receiving-threshold"]
    result = run_analysis(
        definition,
        {"position": "TE", "yards": "100", "touchdowns": "2", "start_season": "2020", "end_season": "2021"},
        fixture_connection(),
    )
    rows = result.tables["rows"]
    assert rows["player_id"].to_list() == ["te1", "te1"]
    assert rows["matches"].to_list() == [2, 2]
    assert rows["population"].to_list() == [4, 4]
    assert rows["pct"].to_list() == [50.0, 50.0]


def test_registered_python_analysis_and_multitable_persistence() -> None:
    definitions = discover(DataConfig.from_project())
    curve = run_analysis(
        definitions["fantasy.positional-rank-curve"],
        {"season": "2020", "positions": "TE,WR"},
        fixture_connection(),
    )
    assert set(curve.tables) == {"rows"}
    assert curve.sql and "row_number()" in curve.sql
    persistence = run_analysis(
        definitions["persistence.top-n"],
        {"position": "TE", "top_n": "2", "start_season": "2020", "end_season": "2021"},
        fixture_connection(),
    )
    assert set(persistence.tables) == {"summary", "players"}
    assert persistence.tables["summary"]["repeat_players"].to_list() == [1]


def test_cli_list_show_run_empty_and_missing(tmp_path: Path) -> None:
    config = config_for(tmp_path, project_root=PROJECT_ROOT)
    config.catalogue_path.parent.mkdir(parents=True)
    fixture_connection(config.catalogue_path).close()
    output = StringIO()
    assert main(["list"], config=config, output=output) == 0
    assert "historical.receiving-threshold | sql" in output.getvalue()
    output = StringIO()
    assert main(["show", "historical.receiving-threshold"], config=config, output=output) == 0
    assert "Source:" in output.getvalue()
    output = StringIO()
    assert main(
        ["run", "historical.receiving-threshold", "--param", "yards=1000"],
        config=config,
        output=output,
    ) == 0
    assert "shape: (2, 16)" in output.getvalue()
    assert "false" in output.getvalue()
    with pytest.raises(ValueError, match="Analysis not found"):
        main(["show", "missing.analysis"], config=config)
    with pytest.raises(ValueError, match="Analysis not found"):
        main(["run", "missing.analysis"], config=config)


def test_cli_uses_project_resolved_catalogue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogue = tmp_path / "resolved.duckdb"
    fixture_connection(catalogue).close()
    config = DataConfig.from_project(
        project_root=PROJECT_ROOT, data_root=tmp_path, catalogue_path=catalogue
    )
    monkeypatch.setattr("ndat.query.DataConfig.from_project", lambda: config)
    output = StringIO()
    assert main(
        ["run", "historical.receiving-threshold", "--param", "yards=1000"],
        output=output,
    ) == 0
    assert str(catalogue) not in output.getvalue()


def test_direct_sql_file_requires_no_metadata(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    config.catalogue_path.parent.mkdir(parents=True)
    fixture_connection(config.catalogue_path).close()
    sql_path = tmp_path / "personal.sql"
    sql_path.write_text("SELECT 42 AS answer", encoding="utf-8")
    output = StringIO()
    assert main(
        ["run", str(sql_path)], config=config, output=output
    ) == 0
    assert "answer" in output.getvalue()
    assert "42" in output.getvalue()
    assert all(ord(character) < 128 for character in output.getvalue())
    empty_path = tmp_path / "empty.sql"
    empty_path.write_text(
        "SELECT CAST(NULL AS INTEGER) AS answer WHERE false", encoding="utf-8"
    )
    output = StringIO()
    assert main(["run", str(empty_path)], config=config, output=output) == 0
    assert "No rows. Columns: answer" in output.getvalue()
