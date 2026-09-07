"""Stage 3 weekly linebacker snap-share role analysis."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ndat.catalogue import update_catalogue
from ndat.config import DataConfig
from ndat.manager import DataManager


DEFAULT_FULL_TIME_SNAP_THRESHOLD = 0.85
LINEBACKER_POSITION = "LB"
DERIVED_VIEW_NAME = "lb_weekly_role"
SOURCE_DATASETS = ("snap_counts", "rosters", "player_stats")


@dataclass(frozen=True)
class ScoringRule:
    points: float
    source_fields: tuple[str, ...]


# A deliberately small Stage 3 definition, not a general fantasy scoring engine.
IDP_SCORING: Mapping[str, ScoringRule] = {
    "sack": ScoringRule(4, ("def_sacks",)),
    "total_tackle": ScoringRule(
        1, ("def_tackles_solo", "def_tackles_with_assist")
    ),
    "blocked_kick": ScoringRule(
        5, ("def_punt_blocks", "def_pat_blocks", "def_fg_blocks")
    ),
    "interception": ScoringRule(5, ("def_interceptions",)),
    "fumble_recovery": ScoringRule(2, ("fumble_recovery_opp",)),
    "forced_fumble": ScoringRule(4, ("def_fumbles_forced",)),
    "safety": ScoringRule(8, ("def_safeties",)),
    # NFLverse has no run-specific "stuff" field. Stage 3 deliberately uses its
    # broader credited tackle-for-loss statistic as the closest available proxy.
    "stuff": ScoringRule(2, ("def_tackles_for_loss",)),
    "pass_defended": ScoringRule(1, ("def_pass_defended",)),
}


class MissingSourceDataError(RuntimeError):
    """Raised when a requested local source partition is absent."""


def normalize_threshold(value: float) -> float:
    """Accept a fraction (0.85) or percentage (85) and return a fraction."""
    threshold = float(value)
    if 1 < threshold <= 100:
        threshold /= 100
    if not 0 <= threshold <= 1:
        raise ValueError("Snap-share threshold must be between 0 and 1 (or 0 and 100)")
    return threshold


def scoring_support(columns: Sequence[str]) -> tuple[list[str], list[str]]:
    available = set(columns)
    supported: list[str] = []
    unsupported: list[str] = []
    for name, rule in IDP_SCORING.items():
        if rule.source_fields and all(field in available for field in rule.source_fields):
            supported.append(name)
        else:
            unsupported.append(name)
    return supported, unsupported


def _zero_filled(frame: pl.DataFrame, field: str) -> pl.Expr:
    if field not in frame.columns:
        return pl.lit(0.0)
    return pl.col(field).fill_null(0).cast(pl.Float64)


def score_player_stats(frame: pl.DataFrame) -> pl.DataFrame:
    """Add explicit Stage 3 scoring components and ``fantasy_points``."""
    component_expressions: list[pl.Expr] = []
    for name, rule in IDP_SCORING.items():
        raw = sum((_zero_filled(frame, field) for field in rule.source_fields), pl.lit(0.0))
        component_expressions.append((raw * rule.points).alias(f"points_{name}"))
    scored = frame.with_columns(component_expressions)
    point_columns = [f"points_{name}" for name in IDP_SCORING]
    return scored.with_columns(
        pl.sum_horizontal(point_columns).cast(pl.Float64).alias("fantasy_points")
    )


def _identity_bridge(rosters: pl.DataFrame) -> pl.DataFrame:
    required = {
        "season",
        "pfr_id",
        "gsis_id",
        "full_name",
        "first_name",
        "last_name",
        "position",
    }
    missing = required - set(rosters.columns)
    if missing:
        raise ValueError(f"rosters is missing required columns: {sorted(missing)}")
    ordering = "week" if "week" in rosters.columns else "season"
    return (
        rosters.filter(pl.col("pfr_id").is_not_null())
        .sort(ordering)
        .unique(["season", "pfr_id"], keep="last")
        .select(
            "season",
            "pfr_id",
            "gsis_id",
            "full_name",
            "first_name",
            "last_name",
            pl.col("position").alias("roster_position"),
        )
    )


def _stats_for_join(player_stats: pl.DataFrame) -> pl.DataFrame:
    keys = {"season", "week", "game_id", "team"}
    scored = score_player_stats(player_stats)
    renamed = [
        pl.col(column) if column in keys else pl.col(column).alias(f"stats_{column}")
        for column in scored.columns
    ]
    return scored.select(renamed)


def derive_weekly_roles(
    snap_counts: pl.DataFrame,
    rosters: pl.DataFrame,
    player_stats: pl.DataFrame,
    *,
    threshold: float = DEFAULT_FULL_TIME_SNAP_THRESHOLD,
) -> pl.DataFrame:
    """Derive all weekly LB evidence; qualification is a separate boolean column."""
    threshold = normalize_threshold(threshold)
    required_snap = {
        "season",
        "week",
        "game_id",
        "pfr_player_id",
        "player",
        "team",
        "position",
        "defense_snaps",
        "defense_pct",
    }
    missing = required_snap - set(snap_counts.columns)
    if missing:
        raise ValueError(f"snap_counts is missing required columns: {sorted(missing)}")

    linebackers = snap_counts.filter(pl.col("position") == LINEBACKER_POSITION)
    identities = _identity_bridge(rosters)
    joined = linebackers.join(
        identities,
        left_on=["season", "pfr_player_id"],
        right_on=["season", "pfr_id"],
        how="left",
    )

    stats = _stats_for_join(player_stats)
    joined = joined.join(
        stats,
        left_on=["season", "week", "game_id", "team", "gsis_id"],
        right_on=["season", "week", "game_id", "team", "stats_player_id"],
        how="left",
    )

    result = joined.select(
        "season",
        "week",
        "game_id",
        pl.coalesce(
            pl.col("gsis_id"), pl.concat_str([pl.lit("pfr:"), pl.col("pfr_player_id")])
        ).alias("player_id"),
        "pfr_player_id",
        pl.coalesce("full_name", "stats_player_display_name", "player").alias(
            "player_name"
        ),
        pl.coalesce(
            "first_name",
            pl.coalesce("full_name", "stats_player_display_name", "player")
            .str.split(" ")
            .list.first(),
        ).alias("first_name"),
        pl.coalesce(
            "last_name",
            pl.coalesce("full_name", "stats_player_display_name", "player")
            .str.split(" ")
            .list.last(),
        ).alias("last_name"),
        "team",
        pl.lit(LINEBACKER_POSITION).alias("position"),
        pl.col("defense_snaps").alias("defensive_snaps"),
        pl.col("defense_pct").alias("defensive_snap_pct"),
        pl.lit(threshold).alias("role_threshold"),
        (pl.col("defense_pct").fill_null(0) >= threshold).alias(
            "qualifies_full_time"
        ),
        pl.col("stats_fantasy_points").fill_null(0.0).alias("fantasy_points"),
    ).sort(["season", "player_id", "week", "game_id"])
    return add_longitudinal_history(result)


def add_longitudinal_history(frame: pl.DataFrame) -> pl.DataFrame:
    """Add compact deterministic acquisition/loss/reacquisition history columns."""
    rows: list[dict[str, object]] = []
    for group in frame.partition_by(["season", "player_id"], maintain_order=True):
        records = group.sort(["week", "game_id"]).to_dicts()
        qualifying_weeks = [int(row["week"]) for row in records if row["qualifies_full_time"]]
        first_week = qualifying_weeks[0] if qualifying_weeks else None
        prior_qualified = False
        ever_qualified = False
        current_streak = 0
        longest_streak = 0
        for row in records:
            qualifies = bool(row["qualifies_full_time"])
            lost = not qualifies and prior_qualified
            reacquired = qualifies and ever_qualified and not prior_qualified
            if qualifies:
                current_streak = current_streak + 1 if prior_qualified else 1
                longest_streak = max(longest_streak, current_streak)
                state = "acquired" if not ever_qualified else (
                    "retained" if prior_qualified else "reacquired"
                )
                ever_qualified = True
            else:
                current_streak = 0
                state = "lost" if lost else (
                    "not_qualified" if not ever_qualified else "unqualified_after_loss"
                )
            row.update(
                first_qualifying_week=first_week,
                qualifying_weeks=qualifying_weeks,
                qualifying_streak=current_streak,
                longest_qualifying_streak=0,  # finalized below
                lost_after_qualifying=lost,
                reacquired=reacquired,
                role_state=state,
            )
            rows.append(row)
            prior_qualified = qualifies
        for row in rows[-len(records) :]:
            row["longest_qualifying_streak"] = longest_streak
    return pl.DataFrame(rows, schema_overrides={"qualifying_weeks": pl.List(pl.Int64)})


def _source_frames(config: DataConfig, season: int) -> tuple[pl.DataFrame, ...]:
    manager = DataManager(config)
    missing = [
        name
        for name in SOURCE_DATASETS
        if not manager.partition_path(name, season).exists()
    ]
    if missing:
        commands = "; ".join(
            f"python -m ndat.data fetch {name} --season {season}" for name in missing
        )
        raise MissingSourceDataError(
            f"Missing local source data for {season}: {', '.join(missing)}. Run: {commands}"
        )
    return tuple(
        pl.read_parquet(manager.partition_path(name, season))
        for name in SOURCE_DATASETS
    )


def derived_path(config: DataConfig, season: int, threshold: float) -> Path:
    return (
        config.derived_root
        / DERIVED_VIEW_NAME
        / f"season={season}"
        / f"threshold={normalize_threshold(threshold):.3f}"
        / "data.parquet"
    )


def register_derived_view(config: DataConfig) -> None:
    update_catalogue(config)


def build_season(
    season: int,
    *,
    threshold: float = DEFAULT_FULL_TIME_SNAP_THRESHOLD,
    config: DataConfig | None = None,
) -> tuple[pl.DataFrame, Path, list[str]]:
    config = config or DataConfig.from_project()
    snap_counts, rosters, player_stats = _source_frames(config, season)
    frame = derive_weekly_roles(
        snap_counts, rosters, player_stats, threshold=threshold
    )
    destination = derived_path(config, season, threshold)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".parquet.tmp")
    frame.write_parquet(temporary)
    temporary.replace(destination)
    register_derived_view(config)
    _, unsupported = scoring_support(player_stats.columns)
    return frame, destination, unsupported


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ndat.lb_roles")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_FULL_TIME_SNAP_THRESHOLD)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    threshold = normalize_threshold(arguments.threshold)
    try:
        frame, path, unsupported = build_season(
            arguments.season, threshold=threshold
        )
    except MissingSourceDataError as error:
        raise SystemExit(str(error)) from error
    print(
        json.dumps(
            {
                "season": arguments.season,
                "threshold": threshold,
                "rows": frame.height,
                "qualifying_player_weeks": frame.filter(
                    pl.col("qualifies_full_time")
                ).height,
                "derived_data": str(path),
                "duckdb_view": DERIVED_VIEW_NAME,
                "unsupported_scoring_categories": unsupported,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
