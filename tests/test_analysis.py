from __future__ import annotations

import duckdb
import pytest

from ndat.analysis import (
    historical_threshold_events,
    positional_rank_curve,
    top_n_persistence,
)
from ndat.scoring import PLAYER_STATS_MAPPINGS


def fixture_connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    stat_fields = sorted(
        {
            field
            for mapping in PLAYER_STATS_MAPPINGS.values()
            for field in mapping.fields
        }
    )
    columns = [
        "season INTEGER", "week INTEGER", "game_id VARCHAR", "player_id VARCHAR",
        "player_display_name VARCHAR", "raw_position VARCHAR",
        "canonical_position VARCHAR", "team VARCHAR", "season_type VARCHAR",
        *(f'"{field}" DOUBLE' for field in stat_fields),
    ]
    connection.execute(f"CREATE TABLE player_game ({', '.join(columns)})")
    rows = [
        # A tie in 2020 is resolved by player_id; p3 is absent in 2021.
        (2020, 1, "g1", "p2", "Beta", "WR", "WR", "B", 100, 1),
        (2020, 1, "g2", "p1", "Alpha", "WR", "WR", "A", 100, 1),
        (2020, 1, "g3", "p3", "Gamma", "WR", "WR", "C", 90, 0),
        (2020, 1, "g4", "t1", "Tight", "TE", "TE", "D", 130, 2),
        (2021, 1, "g5", "p1", "Alpha", "WR", "WR", "A", 110, 1),
        (2021, 1, "g6", "p4", "Delta", "WR", "WR", "D", 105, 1),
        (2021, 1, "g7", "p2", "Beta", "WR", "WR", "B", 80, 0),
        (2022, 1, "g8", "p4", "Delta", "WR", "WR", "D", 125, 2),
    ]
    base_columns = [
        "season", "week", "game_id", "player_id", "player_display_name",
        "raw_position", "canonical_position", "team",
        "receiving_yards", "receiving_tds",
    ]
    for row in rows:
        values = dict(zip(base_columns, row, strict=True))
        values["season_type"] = "REG"
        for field in stat_fields:
            values.setdefault(field, 0)
        names = list(values)
        placeholders = ", ".join("?" for _ in names)
        connection.execute(
            f"INSERT INTO player_game ({', '.join(f'\"{name}\"' for name in names)}) VALUES ({placeholders})",
            list(values.values()),
        )
    return connection


def test_positional_ranking_is_deterministic_and_ties_use_player_id() -> None:
    connection = fixture_connection()
    first = positional_rank_curve(connection, season=2020, positions="WR")
    second = positional_rank_curve(connection, season=2020, positions=["WR"])

    assert first.rows.equals(second.rows)
    assert first.rows["player_id"].to_list() == ["p1", "p2", "p3"]
    assert first.rows["rank"].to_list() == [1, 2, 3]
    assert "row_number()" in first.sql


def test_top_n_persistence_counts_absent_players_as_non_repeats() -> None:
    result = top_n_persistence(
        fixture_connection(), position="WR", top_n=3,
        start_season=2020, end_season=2022,
    )

    assert result.summary.select("eligible_players", "repeat_players").rows() == [
        (3, 2), (3, 1)
    ]
    absent = result.players.filter(result.players["player_id"] == "p3")
    assert absent["target_rank"][0] is None
    assert absent["repeated"][0] is False


def test_threshold_events_support_predicates_positions_and_season_range() -> None:
    connection = fixture_connection()
    result = historical_threshold_events(
        connection,
        positions=["WR", "TE"],
        predicates={"receiving_yards": 120, "receiving_tds": 2},
        start_season=2020,
        end_season=2021,
    )

    assert result.rows["player_id"].to_list() == ["t1"]
    later = historical_threshold_events(
        connection,
        positions="WR",
        predicates={"receiving_yards": 120, "receiving_tds": 2},
        start_season=2022,
        end_season=2022,
    )
    assert later.rows["player_id"].to_list() == ["p4"]
    with pytest.raises(ValueError, match="Unknown or unsafe"):
        historical_threshold_events(
            connection, positions="WR", predicates={"drop table": 0},
            start_season=2020, end_season=2022,
        )
