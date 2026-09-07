from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from ndat.config import DataConfig
from ndat.datasets import DATASETS, DatasetDefinition
from ndat.manager import DataManager


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataManager:
    def fixture_loader(season: int) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "season": [season, season],
                "week": [1, 2],
                "player_id": ["p1", "p1"],
                "attempts": [10, 12],
            }
        )

    monkeypatch.setitem(
        DATASETS,
        "player_stats",
        DatasetDefinition("player_stats", "player_stats", fixture_loader, "Fixture stats"),
    )
    config = DataConfig.from_project(project_root=tmp_path, data_root=tmp_path / "local-data")
    return DataManager(config)


def test_paths_are_deterministic_and_not_cwd_dependent(
    manager: DataManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = (
        tmp_path
        / "local-data"
        / "source"
        / "player_stats"
        / "season=2025"
        / "data.parquet"
    )
    monkeypatch.chdir(tmp_path.parent)
    assert manager.partition_path("player_stats", 2025) == expected


def test_relative_environment_data_root_is_project_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NDAT_DATA_ROOT", "large-local-data")
    monkeypatch.chdir(tmp_path.parent)

    config = DataConfig.from_project(project_root=tmp_path)

    assert config.data_root == tmp_path / "large-local-data"


def test_fetch_writes_standard_parquet_manifest_and_queryable_view(manager: DataManager) -> None:
    result = manager.fetch("player_stats", [2025])
    parquet = manager.partition_path("player_stats", 2025)

    assert result[0]["action"] == "fetched"
    assert pl.read_parquet(parquet).height == 2
    manifest = json.loads(manager.config.manifest_path.read_text(encoding="utf-8"))
    partition = manifest["datasets"]["player_stats"]["partitions"]["2025"]
    assert manifest["datasets"]["player_stats"]["seasons"] == [2025]
    assert partition["row_count"] == 2
    assert partition["path"] == "local-data/source/player_stats/season=2025/data.parquet"
    assert len(partition["schema_sha256"]) == 64
    assert {column["name"] for column in partition["columns"]} == {
        "season",
        "week",
        "player_id",
        "attempts",
    }

    with duckdb.connect(str(manager.config.catalogue_path), read_only=True) as connection:
        assert connection.execute(
            "SELECT sum(attempts) FROM player_stats WHERE season = 2025"
        ).fetchone() == (22,)


def test_repeated_fetch_skips_existing_partition_without_duplication(manager: DataManager) -> None:
    manager.fetch("player_stats", [2025])
    result = manager.fetch("player_stats", [2025, 2025])

    assert result == [{"dataset": "player_stats", "season": 2025, "action": "skipped"}]
    assert pl.read_parquet(manager.partition_path("player_stats", 2025)).height == 2
    with duckdb.connect(str(manager.config.catalogue_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM player_stats").fetchone() == (2,)


def test_refresh_replaces_partition_and_updates_status(
    manager: DataManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.fetch("player_stats", [2025])
    replacement = DatasetDefinition(
        "player_stats",
        "player_stats",
        lambda season: pl.DataFrame({"season": [season], "week": [3], "attempts": [99]}),
        "Fixture stats",
    )
    monkeypatch.setitem(DATASETS, "player_stats", replacement)

    result = manager.refresh("player_stats", [2025])
    status = manager.status()

    assert result[0]["action"] == "refreshed"
    assert pl.read_parquet(manager.partition_path("player_stats", 2025)).height == 1
    assert status["datasets"]["player_stats"]["partitions"]["2025"]["exists"] is True
    assert status["catalogue_exists"] is True


def test_status_does_not_require_existing_data(manager: DataManager) -> None:
    status = manager.status()
    assert status["datasets"] == {}
    assert status["catalogue_exists"] is False
