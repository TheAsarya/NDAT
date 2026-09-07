"""DuckDB views over NDAT-managed Parquet source partitions."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ndat.config import DataConfig
from ndat.datasets import DATASETS
from ndat.positions import position_sql


def _sql_string(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def update_catalogue(config: DataConfig) -> list[str]:
    """Create or refresh stable views for locally present source and derived data."""
    config.ensure_directories()
    available: list[str] = []
    with duckdb.connect(str(config.catalogue_path)) as connection:
        for definition in DATASETS.values():
            files = list((config.source_root / definition.name).glob("season=*/data.parquet"))
            connection.execute(f'DROP VIEW IF EXISTS "{definition.view_name}"')
            if not files:
                continue
            parquet_glob = _sql_string(
                config.source_root / definition.name / "season=*" / "data.parquet"
            )
            connection.execute(
                f'CREATE VIEW "{definition.view_name}" AS '
                f"SELECT * FROM read_parquet('{parquet_glob}', "
                "union_by_name = true, hive_partitioning = false)"
            )
            available.append(definition.view_name)
        connection.execute('DROP VIEW IF EXISTS "player_game"')
        player_columns = (
            {row[0] for row in connection.execute('DESCRIBE "player_stats"').fetchall()}
            if "player_stats" in available
            else set()
        )
        if "position" in player_columns:
            connection.execute(
                'CREATE VIEW "player_game" AS '
                "SELECT *, position AS raw_position, "
                f"{position_sql('position')} AS canonical_position "
                'FROM "player_stats"'
            )
            available.append("player_game")
        derived_name = "lb_weekly_role"
        derived_files = list(
            (config.derived_root / derived_name).glob(
                "season=*/threshold=*/data.parquet"
            )
        )
        connection.execute(f'DROP VIEW IF EXISTS "{derived_name}"')
        if derived_files:
            parquet_glob = _sql_string(
                config.derived_root
                / derived_name
                / "season=*"
                / "threshold=*"
                / "data.parquet"
            )
            connection.execute(
                f'CREATE VIEW "{derived_name}" AS '
                f"SELECT * FROM read_parquet('{parquet_glob}', "
                "union_by_name = true, hive_partitioning = false)"
            )
            available.append(derived_name)
    return available
