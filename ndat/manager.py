"""Acquisition and lifecycle operations for canonical local source data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from ndat.catalogue import update_catalogue
from ndat.config import DataConfig
from ndat.datasets import get_dataset
from ndat.manifest import read_manifest, write_manifest


class DataManager:
    """Manage explicit Parquet copies acquired through supported nflreadpy APIs."""

    def __init__(self, config: DataConfig | None = None) -> None:
        self.config = config or DataConfig.from_project()

    def partition_path(self, dataset: str, season: int) -> Path:
        get_dataset(dataset)
        return self.config.source_root / dataset / f"season={season}" / "data.parquet"

    def fetch(
        self, dataset: str, seasons: Iterable[int], *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Fetch absent partitions, or deliberately replace them when refreshing."""
        definition = get_dataset(dataset)
        requested = sorted(set(seasons))
        if not requested:
            raise ValueError("At least one season is required")
        if any(not isinstance(season, int) for season in requested):
            raise TypeError("Seasons must be integers")

        self.config.ensure_directories()
        manifest = read_manifest(self.config.manifest_path)
        results: list[dict[str, Any]] = []
        for season in requested:
            destination = self.partition_path(dataset, season)
            recorded_partitions = manifest["datasets"].get(dataset, {}).get(
                "partitions", {}
            )
            if destination.exists() and str(season) in recorded_partitions and not refresh:
                results.append({"dataset": dataset, "season": season, "action": "skipped"})
                continue

            frame = definition.loader(season)
            if not isinstance(frame, pl.DataFrame):
                frame = pl.DataFrame(frame)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".parquet.tmp")
            frame.write_parquet(temporary)
            temporary.replace(destination)

            entry = self._provenance(season, destination, frame)
            dataset_manifest = manifest["datasets"].setdefault(
                dataset,
                {
                    "description": definition.description,
                    "upstream": "NFLverse via nflreadpy",
                    "partitions": {},
                },
            )
            dataset_manifest["partitions"][str(season)] = entry
            action = "refreshed" if refresh else "fetched"
            results.append({"dataset": dataset, "season": season, "action": action})

        if dataset in manifest["datasets"]:
            dataset_manifest = manifest["datasets"][dataset]
            dataset_manifest["seasons"] = sorted(
                int(value) for value in dataset_manifest["partitions"]
            )
        write_manifest(self.config.manifest_path, manifest)
        update_catalogue(self.config)
        return results

    def refresh(self, dataset: str, seasons: Iterable[int]) -> list[dict[str, Any]]:
        return self.fetch(dataset, seasons, refresh=True)

    def status(self) -> dict[str, Any]:
        """Describe local data without consulting the network."""
        manifest = read_manifest(self.config.manifest_path)
        for dataset in manifest["datasets"].values():
            for partition in dataset["partitions"].values():
                partition["exists"] = (self.config.project_root / partition["path"]).exists()
        manifest["catalogue"] = self._display_path(self.config.catalogue_path)
        manifest["catalogue_exists"] = self.config.catalogue_path.exists()
        return manifest

    def _provenance(self, season: int, path: Path, frame: pl.DataFrame) -> dict[str, Any]:
        schema = [{"name": name, "type": str(dtype)} for name, dtype in frame.schema.items()]
        fingerprint = hashlib.sha256(
            json.dumps(schema, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "season": season,
            "path": self._display_path(path),
            "acquired_at": datetime.now(UTC).isoformat(),
            "row_count": frame.height,
            "columns": schema,
            "schema_sha256": fingerprint,
            "nflreadpy_version": importlib.metadata.version("nflreadpy"),
        }

    def _display_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.config.project_root).as_posix()
        except ValueError:
            return str(path)
