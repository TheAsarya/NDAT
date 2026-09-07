from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ndat.scoring import (
    PLAYER_STATS_MAPPINGS,
    load_profile,
    score_player,
    score_record,
    validate_profile,
)


def complete_player_row(**updates: object) -> dict[str, object]:
    fields = {
        field
        for mapping in PLAYER_STATS_MAPPINGS.values()
        for field in mapping.fields
    }
    row: dict[str, object] = {field: 0 for field in fields}
    row.update(updates)
    return row


def test_named_profiles_load_and_lob_is_explicitly_non_ppr() -> None:
    lob = load_profile("LoB")
    idp = load_profile("Stage3_IDP")

    assert lob.name == "LoB"
    assert lob.rules["reception"].points == 0
    assert idp.rules["sack"].points == 4


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"passing_yards": 250}, 10),
        ({"passing_tds": 2}, 8),
        ({"passing_interceptions": 2}, -4),
        ({"rushing_yards": 80, "rushing_tds": 1}, 14),
        ({"receptions": 12, "receiving_yards": 90, "receiving_tds": 1}, 15),
        ({"fumbles_lost_total": 1}, -2),
        ({"special_teams_tds": 1}, 6),
        ({"fumble_recovery_tds": 1}, 6),
    ],
)
def test_lob_player_scoring(values: dict[str, object], expected: float) -> None:
    result = score_player(complete_player_row(**values), "LoB")
    assert result.total_points == pytest.approx(expected)


def test_future_ppr_profile_needs_only_configuration_change(tmp_path: Path) -> None:
    source = load_profile("LoB").path.read_text(encoding="utf-8")
    source = source.replace(
        '[rules.reception]\ntype = "event"\npoints = 0',
        '[rules.reception]\ntype = "event"\npoints = 1',
    ).replace('name = "LoB"', 'name = "Test_PPR"', 1)
    path = tmp_path / "ppr.toml"
    path.write_text(source, encoding="utf-8")
    profile = validate_profile(tomllib.loads(source), path=path)

    result = score_player(complete_player_row(receptions=7), profile)
    assert result.component_points["reception"] == 7


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("fg_made_0_19", 3),
        ("fg_made_20_29", 3),
        ("fg_made_30_39", 3),
        ("fg_made_40_49", 4),
        ("fg_made_50_59", 5),
        ("fg_made_60_", 5),
    ],
)
def test_field_goal_distance_buckets(field: str, expected: float) -> None:
    assert score_player(complete_player_row(**{field: 1})).total_points == expected


def test_missed_kicks_and_null_stats() -> None:
    result = score_player(
        complete_player_row(fg_missed=2, pat_missed=1, passing_yards=None)
    )
    assert result.total_points == -3
    assert result.component_points["passing_yards"] == 0


@pytest.mark.parametrize(
    ("allowed", "expected"),
    [(0, 5), (1, 4), (6, 4), (7, 3), (13, 3), (14, 1), (20, 1),
     (21, 0), (27, 0), (28, -1), (34, -1), (35, -4)],
)
def test_dst_points_allowed_boundaries(allowed: int, expected: float) -> None:
    result = score_record({"points_allowed": allowed}, entity="team_defense")
    assert result.component_points["points_allowed"] == expected


@pytest.mark.parametrize(
    ("allowed", "expected"),
    [(99, 5), (100, 3), (199, 3), (200, 2), (299, 2), (300, 0),
     (349, 0), (350, -1), (399, -1), (400, -3), (449, -3),
     (450, -5), (499, -5), (500, -6), (549, -6), (550, -7)],
)
def test_dst_yards_allowed_boundaries(allowed: int, expected: float) -> None:
    result = score_record({"yards_allowed": allowed}, entity="team_defense")
    assert result.component_points["yards_allowed"] == expected


def test_fractional_stage3_sack_and_full_idp_profile() -> None:
    row = complete_player_row(
        def_sacks=0.5,
        def_tackles_solo=3,
        def_tackles_with_assist=2,
        def_punt_blocks=1,
        def_interceptions=1,
        fumble_recovery_opp=1,
        def_fumbles_forced=1,
        def_safeties=1,
        def_tackles_for_loss=1,
        def_pass_defended=1,
    )
    result = score_player(row, "Stage3_IDP")
    assert result.total_points == 32
    assert result.component_points["sack"] == 2
    assert "stuff" in result.unsupported_components


def test_missing_source_columns_are_reported_not_silently_zero() -> None:
    result = score_player({"passing_yards": 100}, "LoB")
    assert result.total_points == 4
    assert "passing_td" in result.unsupported_components
    assert "special_teams_player_forced_fumble" in result.unsupported_components
