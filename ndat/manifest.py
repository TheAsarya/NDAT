"""Lightweight JSON provenance for project-managed source data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1


def empty_manifest() -> dict[str, Any]:
    return {"manifest_version": MANIFEST_VERSION, "datasets": {}}


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_manifest()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(f"Unsupported manifest version in {path}")
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
