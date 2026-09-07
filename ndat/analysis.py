"""Core SQL-first analytical primitives for Stage 4."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import duckdb
import polars as pl

from ndat.scoring import player_stats_scoring_sql


@dataclass(frozen=True)
class AnalysisResult:
    rows: pl.DataFrame
    sql: str
    unsupported_components: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersistenceResult:
    summary: pl.DataFrame
    players: pl.DataFrame
    sql: str
    unsupported_components: tuple[str, ...] = ()


def _positions(positions: str | Sequence[str]) -> list[str]:
    values = [positions] if isinstance(positions, str) else list(positions)
    if not values:
        raise ValueError("At least one position is required")
    return [value.upper() for value in values]


def _fetch_frame(connection: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    names = [description[0] for description in connection.description]
    return pl.DataFrame(connection.fetchall(), schema=names, orient="row")


def _score_parts(profile: str, alias: str = "pg") -> tuple[str, tuple[str, ...]]:
    expressions, unsupported = player_stats_scoring_sql(profile, table_alias=alias)
    if not expressions:
        raise ValueError(f"Profile {profile!r} has no player_stats scoring components")
    combined = " + ".join(f"({expression})" for expression in expressions.values())
    return f"cast(({combined}) AS DOUBLE)", unsupported


def positional_rank_curve(
    connection: duckdb.DuckDBPyConnection,
    *,
    season: int,
    positions: str | Sequence[str],
    profile: str = "LoB",
) -> AnalysisResult:
    """Return deterministic ordinal ranks from regular-season player-game data."""
    requested = _positions(positions)
    score, unsupported = _score_parts(profile)
    placeholders = ", ".join("?" for _ in requested)
    sql = f"""
WITH player_season AS (
    SELECT
        pg.season,
        pg.canonical_position AS position,
        pg.player_id,
        max(pg.player_display_name) AS player_name,
        round(sum({score}), 6) AS fantasy_points
    FROM player_game AS pg
    WHERE pg.season = ?
      AND pg.season_type = 'REG'
      AND pg.canonical_position IN ({placeholders})
    GROUP BY pg.season, pg.canonical_position, pg.player_id
)
SELECT
    season,
    position,
    row_number() OVER (
        PARTITION BY season, position
        ORDER BY fantasy_points DESC, player_id ASC
    ) AS rank,
    player_id,
    player_name,
    fantasy_points
FROM player_season
ORDER BY season, position, rank, player_id
""".strip()
    connection.execute(sql, [season, *requested])
    table = _fetch_frame(connection)
    return AnalysisResult(table, sql, unsupported)


def top_n_persistence(
    connection: duckdb.DuckDBPyConnection,
    *,
    position: str,
    top_n: int,
    start_season: int,
    end_season: int,
    profile: str = "LoB",
    horizon: int = 1,
) -> PersistenceResult:
    """Measure whether source top-N players repeat after a configurable horizon."""
    if top_n < 1 or horizon < 1 or end_season <= start_season:
        raise ValueError(
            "top_n/horizon must be positive and the season range must span years"
        )
    score, unsupported = _score_parts(profile)
    sql = f"""
WITH player_season AS (
    SELECT
        pg.season,
        pg.player_id,
        max(pg.player_display_name) AS player_name,
        round(sum({score}), 6) AS fantasy_points
    FROM player_game AS pg
    WHERE pg.season BETWEEN ? AND ?
      AND pg.season_type = 'REG'
      AND pg.canonical_position = ?
    GROUP BY pg.season, pg.player_id
), ranked AS (
    SELECT *, row_number() OVER (
        PARTITION BY season ORDER BY fantasy_points DESC, player_id ASC
    ) AS position_rank
    FROM player_season
), source AS (
    SELECT * FROM ranked
    WHERE position_rank <= ? AND season + ? <= ?
), details AS (
    SELECT
        source.season AS source_season,
        source.season + ? AS target_season,
        source.player_id,
        source.player_name,
        source.position_rank AS source_rank,
        target.position_rank AS target_rank,
        coalesce(target.position_rank <= ?, false) AS repeated
    FROM source
    LEFT JOIN ranked AS target
      ON target.season = source.season + ?
     AND target.player_id = source.player_id
)
SELECT * FROM details
ORDER BY source_season, source_rank, player_id
""".strip()
    parameters = [
        start_season,
        end_season,
        position.upper(),
        top_n,
        horizon,
        end_season,
        horizon,
        top_n,
        horizon,
    ]
    connection.execute(sql, parameters)
    players = _fetch_frame(connection)
    if players.is_empty():
        summary = pl.DataFrame(
            schema={
                "source_season": pl.Int64,
                "target_season": pl.Int64,
                "eligible_players": pl.Int64,
                "repeat_players": pl.Int64,
                "repeat_rate": pl.Float64,
            }
        )
    else:
        summary = (
            players.group_by(["source_season", "target_season"])
            .agg(
                pl.len().alias("eligible_players"),
                pl.col("repeated").sum().alias("repeat_players"),
            )
            .with_columns(
                (pl.col("repeat_players") / pl.col("eligible_players")).alias(
                    "repeat_rate"
                )
            )
            .sort("source_season")
        )
    return PersistenceResult(summary, players, sql, unsupported)


def historical_threshold_events(
    connection: duckdb.DuckDBPyConnection,
    *,
    positions: str | Sequence[str],
    predicates: Mapping[str, float],
    start_season: int,
    end_season: int,
) -> AnalysisResult:
    """Filter player-game rows with simultaneous ordinary numeric predicates."""
    requested = _positions(positions)
    if not predicates:
        raise ValueError("At least one numeric predicate is required")
    available = {
        row[0] for row in connection.execute("DESCRIBE player_game").fetchall()
    }
    invalid = [
        name
        for name in predicates
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name not in available
    ]
    if invalid:
        raise ValueError(f"Unknown or unsafe player_game fields: {sorted(invalid)}")
    position_placeholders = ", ".join("?" for _ in requested)
    clauses = "\n      AND ".join(f'coalesce(pg."{name}", 0) >= ?' for name in predicates)
    selected = ",\n    ".join(f'pg."{name}"' for name in predicates)
    sql = f"""
SELECT
    pg.season,
    pg.week,
    pg.game_id,
    pg.player_id,
    pg.player_display_name AS player_name,
    pg.raw_position,
    pg.canonical_position AS position,
    pg.team,
    {selected}
FROM player_game AS pg
WHERE pg.season BETWEEN ? AND ?
  AND pg.season_type = 'REG'
  AND pg.canonical_position IN ({position_placeholders})
  AND {clauses}
ORDER BY pg.season, pg.week, pg.game_id, pg.player_id
""".strip()
    parameters = [start_season, end_season, *requested, *predicates.values()]
    connection.execute(sql, parameters)
    return AnalysisResult(_fetch_frame(connection), sql)
