"""Stage 3 weekly linebacker snap-share role analysis."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from ndat.catalogue import update_catalogue
from ndat.config import DataConfig
from ndat.manager import DataManager
from ndat.scoring import PLAYER_STATS_MAPPINGS, load_profile


DEFAULT_FULL_TIME_SNAP_THRESHOLD = 0.85
LINEBACKER_POSITION = "LB"
DERIVED_VIEW_NAME = "lb_weekly_role"
SOURCE_DATASETS = ("snap_counts", "rosters", "player_stats", "play_by_play")

STUFF_REQUIRED_FIELDS = {
    "season",
    "week",
    "game_id",
    "defteam",
    "rush_attempt",
    "yards_gained",
}
STUFF_TFL_CREDIT_FIELDS = (
    "tackle_for_loss_1_player_id",
    "tackle_for_loss_2_player_id",
)
STUFF_PRIMARY_TACKLE_FIELDS = (
    "solo_tackle_1_player_id",
    "solo_tackle_2_player_id",
    "tackle_with_assist_1_player_id",
    "tackle_with_assist_2_player_id",
)


IDP_PROFILE = load_profile("Stage3_IDP")
# Kept as a public alias for callers that inspected the Stage 3 definition.
IDP_SCORING = IDP_PROFILE.rules


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


def scoring_support(
    columns: Sequence[str], play_by_play_columns: Sequence[str] = ()
) -> tuple[list[str], list[str]]:
    available = set(columns)
    supported: list[str] = []
    unsupported: list[str] = []
    for name in IDP_SCORING:
        if name == "stuff":
            pbp = set(play_by_play_columns)
            credit_fields = set(STUFF_TFL_CREDIT_FIELDS + STUFF_PRIMARY_TACKLE_FIELDS)
            if STUFF_REQUIRED_FIELDS <= pbp and credit_fields & pbp:
                supported.append(name)
            else:
                unsupported.append(name)
            continue
        mapping = PLAYER_STATS_MAPPINGS.get(name)
        if mapping and all(field in available for field in mapping.fields):
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
        if name == "stuff" and "stuff" in frame.columns:
            raw = _zero_filled(frame, "stuff")
            component_expressions.append(
                (raw * float(rule.points)).alias("points_stuff")
            )
            continue
        mapping = PLAYER_STATS_MAPPINGS.get(name)
        if mapping is None:
            component_expressions.append(pl.lit(0.0).alias(f"points_{name}"))
            continue
        raw = sum((_zero_filled(frame, field) for field in mapping.fields), pl.lit(0.0))
        component_expressions.append((raw * float(rule.points)).alias(f"points_{name}"))
    scored = frame.with_columns(component_expressions)
    point_columns = [f"points_{name}" for name in IDP_SCORING]
    return scored.with_columns(
        pl.sum_horizontal(point_columns).cast(pl.Float64).alias("fantasy_points")
    )


def derive_stuffs(play_by_play: pl.DataFrame) -> pl.DataFrame:
    """Approximate ESPN stuffs from credited zero/negative rushing plays.

    Negative runs prefer NFLverse tackle-for-loss credit. Zero-yard runs, and the
    rare negative run without TFL credit, use primary solo/tackle-with-assist
    credit. Shared primary credit is split so each play contributes one stuff.
    """
    missing = STUFF_REQUIRED_FIELDS - set(play_by_play.columns)
    if missing:
        raise ValueError(f"play_by_play is missing required fields: {sorted(missing)}")

    predicate = (
        (pl.col("rush_attempt").fill_null(0) == 1)
        & (pl.col("yards_gained").is_not_null())
        & (pl.col("yards_gained") <= 0)
        & pl.col("defteam").is_not_null()
    )
    if "play_type" in play_by_play.columns:
        predicate &= pl.col("play_type") == "run"
    for flag in ("qb_kneel", "qb_spike", "play_deleted", "aborted_play"):
        if flag in play_by_play.columns:
            predicate &= pl.col(flag).fill_null(0) == 0

    wanted = [
        "season",
        "week",
        "game_id",
        "defteam",
        "yards_gained",
        *(field for field in STUFF_TFL_CREDIT_FIELDS if field in play_by_play.columns),
        *(
            field
            for field in STUFF_PRIMARY_TACKLE_FIELDS
            if field in play_by_play.columns
        ),
    ]
    rows: list[dict[str, object]] = []
    for play in play_by_play.filter(predicate).select(wanted).to_dicts():
        preferred = STUFF_TFL_CREDIT_FIELDS if float(play["yards_gained"]) < 0 else ()
        defenders = [
            play.get(field)
            for field in preferred
            if play.get(field) not in (None, "")
        ]
        if not defenders:
            defenders = [
                play.get(field)
                for field in STUFF_PRIMARY_TACKLE_FIELDS
                if play.get(field) not in (None, "")
            ]
        defenders = list(dict.fromkeys(defenders))
        if not defenders:
            continue
        credit = 1.0 / len(defenders)
        for player_id in defenders:
            rows.append(
                {
                    "season": play["season"],
                    "week": play["week"],
                    "game_id": play["game_id"],
                    "team": play["defteam"],
                    "player_id": player_id,
                    "stuff": credit,
                }
            )

    schema = {
        "season": pl.Int64,
        "week": pl.Int64,
        "game_id": pl.String,
        "team": pl.String,
        "player_id": pl.String,
        "stuff": pl.Float64,
    }
    if not rows:
        return pl.DataFrame(schema=schema)
    return (
        pl.DataFrame(rows, schema_overrides=schema)
        .group_by("season", "week", "game_id", "team", "player_id")
        .agg(pl.col("stuff").sum())
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
            (
                pl.col("depth_chart_position")
                if "depth_chart_position" in rosters.columns
                else pl.lit(None, dtype=pl.String)
            ).alias("depth_chart_position"),
            (
                pl.col("ngs_position")
                if "ngs_position" in rosters.columns
                else pl.lit(None, dtype=pl.String)
            ).alias("ngs_position"),
        )
    )


def _stats_for_join(
    player_stats: pl.DataFrame, stuffs: pl.DataFrame | None = None
) -> pl.DataFrame:
    keys = {"season", "week", "game_id", "team"}
    if stuffs is not None:
        join_keys = ["season", "week", "game_id", "team", "player_id"]
        player_stats = player_stats.join(
            stuffs, on=join_keys, how="full", coalesce=True
        )
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
    play_by_play: pl.DataFrame | None = None,
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

    stuffs = derive_stuffs(play_by_play) if play_by_play is not None else None
    stats = _stats_for_join(player_stats, stuffs)
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
        pl.col("position").alias("raw_position"),
        pl.when(pl.col("ngs_position") == "EDGE")
        .then(pl.lit("EDGE"))
        .otherwise(pl.lit(LINEBACKER_POSITION))
        .alias("canonical_position"),
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
    snap_counts, rosters, player_stats, play_by_play = _source_frames(config, season)
    frame = derive_weekly_roles(
        snap_counts,
        rosters,
        player_stats,
        play_by_play,
        threshold=threshold,
    )
    destination = derived_path(config, season, threshold)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".parquet.tmp")
    frame.write_parquet(temporary)
    temporary.replace(destination)
    register_derived_view(config)
    _, unsupported = scoring_support(player_stats.columns, play_by_play.columns)
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
