"""Small, explicit mapping from NDAT dataset names to nflreadpy loaders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import nflreadpy
import polars as pl


Loader = Callable[[int], pl.DataFrame]


@dataclass(frozen=True)
class DatasetDefinition:
    name: str
    view_name: str
    loader: Loader
    description: str


DATASETS: dict[str, DatasetDefinition] = {
    "player_stats": DatasetDefinition(
        "player_stats", "player_stats",
        lambda season: nflreadpy.load_player_stats(seasons=season, summary_level="week"),
        "Weekly player/game statistics",
    ),
    "play_by_play": DatasetDefinition(
        "play_by_play", "play_by_play", lambda season: nflreadpy.load_pbp(seasons=season),
        "Play-level play-by-play data",
    ),
    "snap_counts": DatasetDefinition(
        "snap_counts", "snap_counts", lambda season: nflreadpy.load_snap_counts(seasons=season),
        "Weekly player snap counts",
    ),
    "participation": DatasetDefinition(
        "participation", "participation", lambda season: nflreadpy.load_participation(seasons=season),
        "Play-level player participation",
    ),
    "rosters": DatasetDefinition(
        "rosters", "rosters", lambda season: nflreadpy.load_rosters(seasons=season),
        "Seasonal player identity and roster data",
    ),
    "schedules": DatasetDefinition(
        "schedules", "schedules", lambda season: nflreadpy.load_schedules(seasons=season),
        "Game and team identity data",
    ),
}


def get_dataset(name: str) -> DatasetDefinition:
    try:
        return DATASETS[name]
    except KeyError as error:
        choices = ", ".join(DATASETS)
        raise ValueError(f"Unknown dataset {name!r}; choose one of: {choices}") from error
