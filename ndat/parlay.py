"""Saved Python analysis for historical four-receiver parlay hit rates."""

from __future__ import annotations

import math
from dataclasses import dataclass

import duckdb
import polars as pl

from ndat.config import PROJECT_ROOT


PARLAY_WR1_SQL = (
    PROJECT_ROOT
    / "queries"
    / "historical"
    / "threshold_events"
    / "parlay_0002.sql"
)


@dataclass(frozen=True)
class ParlayRateResult:
    summary: pl.DataFrame
    weekly: pl.DataFrame
    sql: str


def _fetch_frame(connection: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    names = [description[0] for description in connection.description]
    return pl.DataFrame(connection.fetchall(), schema=names, orient="row")


def historical_wr1_parlay_envelope(
    connection: duckdb.DuckDBPyConnection,
    *,
    start_season: int = 2021,
    end_season: int = 2025,
    cohort_size: int = 12,
    standard_yards: float = 60.0,
    reduced_yards: float = 40.0,
) -> ParlayRateResult:
    """Retrieve weekly quartet rates in SQL and summarize their distribution in Python."""
    if end_season < start_season:
        raise ValueError("end_season must be greater than or equal to start_season")
    if cohort_size < 4:
        raise ValueError("cohort_size must be at least 4")
    if reduced_yards < 0 or standard_yards < 0:
        raise ValueError("yardage thresholds must be non-negative")
    if reduced_yards > standard_yards:
        raise ValueError("reduced_yards must not exceed standard_yards")

    sql = PARLAY_WR1_SQL.read_text(encoding="utf-8")
    connection.execute(
        sql,
        {
            "start_season": start_season,
            "end_season": end_season,
            "cohort_size": cohort_size,
            "standard_yards": standard_yards,
            "reduced_yards": reduced_yards,
        },
    )
    weekly = _fetch_frame(connection)
    if weekly.is_empty():
        weekly = pl.DataFrame(
            schema={
                "rate_rank": pl.UInt32,
                "season": pl.Int64,
                "week": pl.Int64,
                "combinations": pl.Int64,
                "hits": pl.Int64,
                "hit_rate": pl.Float64,
                "hit_pct": pl.Float64,
            }
        )
        summary = pl.DataFrame(
            {
                "weeks_analysed": pl.Series([0], dtype=pl.UInt32),
                "minimum_rate": pl.Series([None], dtype=pl.Float64),
                "p25": pl.Series([None], dtype=pl.Float64),
                "median": pl.Series([None], dtype=pl.Float64),
                "p75": pl.Series([None], dtype=pl.Float64),
                "maximum_rate": pl.Series([None], dtype=pl.Float64),
            }
        )
        return ParlayRateResult(summary, weekly, sql)

    weekly = (
        weekly.sort(["hit_rate", "season", "week"], descending=[True, False, False])
        .with_row_index("rate_rank", offset=1)
        .with_columns((100.0 * pl.col("hit_rate")).round(2).alias("hit_pct"))
    )
    rates = sorted(float(value) for value in weekly["hit_rate"].to_list())

    def percentile(quantile: float) -> float:
        position = (len(rates) - 1) * quantile
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return rates[lower]
        fraction = position - lower
        return rates[lower] + (rates[upper] - rates[lower]) * fraction

    summary = pl.DataFrame(
        {
            "weeks_analysed": pl.Series([len(rates)], dtype=pl.UInt32),
            "minimum_rate": [rates[0]],
            "p25": [percentile(0.25)],
            "median": [percentile(0.5)],
            "p75": [percentile(0.75)],
            "maximum_rate": [rates[-1]],
        }
    )
    return ParlayRateResult(summary, weekly, sql)
