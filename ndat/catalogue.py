"""DuckDB views over NDAT-managed Parquet source partitions."""

from __future__ import annotations

from pathlib import Path

import duckdb

from ndat.config import DataConfig
from ndat.datasets import DATASETS


def _sql_string(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def update_catalogue(config: DataConfig) -> list[str]:
    """Create or refresh stable views for locally present source datasets."""
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
    return available
