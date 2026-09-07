"""Portable configuration for NDAT's local data layer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DataConfig:
    """Resolved locations used by all data-management operations."""

    project_root: Path
    data_root: Path
    source_root: Path
    derived_root: Path
    manifest_path: Path
    catalogue_path: Path

    @classmethod
    def from_project(
        cls,
        project_root: Path | None = None,
        data_root: Path | None = None,
        catalogue_path: Path | None = None,
    ) -> DataConfig:
        """Build configuration independent of the process working directory.

        ``NDAT_DATA_ROOT`` may override the repository-local default. Explicit
        arguments take precedence and are useful to embedding applications and tests.
        """
        root = (project_root or PROJECT_ROOT).resolve()
        configured_data = Path(
            data_root or os.environ.get("NDAT_DATA_ROOT") or root / "data"
        ).expanduser()
        resolved_data = (
            configured_data if configured_data.is_absolute() else root / configured_data
        ).resolve()
        configured_catalogue = Path(
            catalogue_path or resolved_data / "ndat.duckdb"
        ).expanduser()
        resolved_catalogue = (
            configured_catalogue
            if configured_catalogue.is_absolute()
            else root / configured_catalogue
        ).resolve()
        return cls(
            project_root=root,
            data_root=resolved_data,
            source_root=resolved_data / "source",
            derived_root=resolved_data / "derived",
            manifest_path=resolved_data / "manifest.json",
            catalogue_path=resolved_catalogue,
        )

    def ensure_directories(self) -> None:
        self.source_root.mkdir(parents=True, exist_ok=True)
        self.derived_root.mkdir(parents=True, exist_ok=True)
        self.catalogue_path.parent.mkdir(parents=True, exist_ok=True)
