# Stage 4: reusable scoring and analytical primitives

Stage 4 separates league rules, canonical NDAT statistics, and NFLverse source
fields. League rules are human-editable TOML in `ndat/scoring_profiles/`; they do
not contain upstream field names. `ndat.scoring` validates profiles, maps a weekly
NFLverse player-stat row to the canonical vocabulary, and returns total points,
component points, and unavailable components. Missing mapped columns are
unavailable rather than zero. A present null statistic scores as zero.

The stable profiles are:

- `LoB` in `ndat/scoring_profiles/lob.toml`, the complete non-PPR dynasty profile.
- `Stage3_IDP` in `ndat/scoring_profiles/stage3_idp.toml`, preserving the Stage 3
  workbook definition exactly.

Profiles support `linear`, `event`, and inclusive `buckets` rules. A future PPR or
half-PPR profile changes only `rules.reception.points` from LoB's explicit `0` to
`1` or `0.5`; no scoring-code change is required.

## Complete LoB profile

| Area | Canonical rule | Points |
|---|---|---:|
| Passing | `passing_yards` | 0.04/yard |
| Passing | `passing_td` | 4 |
| Passing | `passing_2pt_conversion` | 2 |
| Passing | `passing_interception` | -2 |
| Rushing | `rushing_yards` | 0.1/yard |
| Rushing | `rushing_td` | 6 |
| Rushing | `rushing_2pt_conversion` | 2 |
| Receiving | `reception` | **0** |
| Receiving | `receiving_yards` | 0.1/yard |
| Receiving | `receiving_td` | 6 |
| Receiving | `receiving_2pt_conversion` | 2 |
| Kicking | `field_goal_distance` | 0–19: 3; 20–29: 3; 30–39: 3; 40–49: 4; 50+: 5 |
| Kicking | `pat_made` | 1 |
| Kicking | `field_goal_missed` | -1 |
| Kicking | `pat_missed` | -1 |
| Team defense | `defensive_td` | 6 |
| Team defense | `points_allowed` | 0: 5; 1–6: 4; 7–13: 3; 14–20: 1; 21–27: 0; 28–34: -1; 35+: -4 |
| Team defense | `yards_allowed` | <100: 5; 100–199: 3; 200–299: 2; 300–349: 0; 350–399: -1; 400–449: -3; 450–499: -5; 500–549: -6; 550+: -7 |
| Team defense | `defensive_sack` | 1 |
| Team defense | `defensive_interception` | 2 |
| Team defense | `defensive_fumble_recovery` | 1 |
| Team defense | `defensive_safety` | 2 |
| Team defense | `defensive_forced_fumble` | 1 |
| Team defense | `blocked_kick` | 2 |
| ST defense | `special_teams_defense_td` | 6 |
| ST defense | `special_teams_defense_forced_fumble` | 1 |
| ST defense | `special_teams_defense_fumble_recovery` | 1 |
| ST player | `special_teams_player_td` | 6 |
| ST player | `special_teams_player_forced_fumble` | 1 |
| ST player | `special_teams_player_fumble_recovery` | 1 |
| Miscellaneous | `fumble_lost` | -2 |
| Miscellaneous | `fumble_recovery_td` | 6 |

## Source coverage and semantics

The following mapping was checked against the locally acquired 2025 schemas. The
canonical-to-source boundary is `PLAYER_STATS_MAPPINGS` and the broader coverage
inventory is `SOURCE_FIELD_COVERAGE` in `ndat/scoring.py`.

| LoB category | NFLverse source field(s) | Coverage |
|---|---|---|
| Passing | `passing_yards`, `passing_tds`, `passing_2pt_conversions`, `passing_interceptions` | Directly supported by `player_stats` |
| Rushing | `rushing_yards`, `rushing_tds`, `rushing_2pt_conversions` | Directly supported by `player_stats` |
| Receiving | `receptions`, `receiving_yards`, `receiving_tds`, `receiving_2pt_conversions` | Directly supported by `player_stats` |
| Made FG distance | `fg_made_0_19`, `fg_made_20_29`, `fg_made_30_39`, `fg_made_40_49`, `fg_made_50_59`, `fg_made_60_` | Directly supported bucket counts in `player_stats` |
| PAT made/missed, FG missed | `pat_made`, `pat_missed`, `fg_missed` | Directly supported by `player_stats` |
| Defensive TD, sack, interception, forced fumble, safety, blocked kick | `def_tds`, `def_sacks`, `def_interceptions`, `def_fumbles_forced`, `def_safeties`, and sum of `def_punt_blocks + def_pat_blocks + def_fg_blocks` | Derivable by team/game aggregation of `player_stats`; fractional sacks remain fractional |
| Defensive fumble recovery | `fumble_recovery_opp` | Derivable by team/game aggregation, but shared-credit behavior should be verified before a materialized DST view |
| Points allowed | opponent of `home_score` / `away_score` with `home_team` / `away_team` | Derivable from `schedules` |
| Yards allowed | opponent possession and yardage fields such as `posteam`, `yards_gained` | Requires `play_by_play` aggregation; fix the exact fantasy total-yards convention before materialization |
| ST defense TD | `special_teams_play`, `return_touchdown`, `return_team` | Requires `play_by_play` classification/aggregation |
| ST defense forced fumble/recovery | `special_teams_play` plus forced-fumble/recovery team attribution fields | Requires `play_by_play` classification/aggregation |
| ST player TD | `special_teams_tds` | Directly supported by `player_stats` |
| ST player forced fumble/recovery | `special_teams_play` plus player attribution fields | Requires `play_by_play`; unavailable to the current weekly-player adapter and explicitly reported |
| Fumble lost | `fumbles_lost_total` | Directly supported by `player_stats` |
| Fumble recovery TD | `fumble_recovery_tds` | Directly supported by `player_stats` |

No category is fabricated. The generic canonical `score_record` API can score a
complete team-defense record now, including both allowance buckets. Stage 4 does
not materialize a DST team-game aggregation because yards-allowed and special-teams
classification semantics require a deliberate architectural decision. The weekly
`score_player` adapter reports the two unavailable special-teams player components.

The `Stage3_IDP` weekly mapping is: `def_sacks` (4),
`def_tackles_solo + def_tackles_with_assist` (1), three block fields (5),
`def_interceptions` (5), `fumble_recovery_opp` (2), `def_fumbles_forced` (4),
`def_safeties` (8), the derived canonical `stuff` (2), and `def_pass_defended` (1).
Stuff is approximated from credited zero/negative non-kneel rushes in play-by-play.
Negative plays prefer TFL attribution; otherwise primary tackle credit is used, and
shared credit is split. This is not authoritative ESPN credit, uncredited plays are
unassignable, and no overlap with sacks is assumed.

## Position normalization

`player_game` preserves NFLverse `position` as both its original column and
`raw_position`, and adds `canonical_position`. The SQL mapping makes only small,
safe aliases (`HB`/`FB` → `RB`, safety variants → `S`) and otherwise preserves the
label. Stage 3 still selects the raw snap-count `LB` population. Its output now also
contains `raw_position` and a `canonical_position` that becomes `EDGE` only when
the joined roster row has explicit `ngs_position = 'EDGE'`; otherwise it remains
`LB`. NGS coverage is incomplete and occasionally conflicts with depth-chart
labels, so the implementation does not guess EDGE from `OLB` or maintain a manual
player list.

## SQL-first analytical interfaces

Rebuilding the catalogue creates stable `player_game` over locally available
`player_stats`, in addition to the source view. It is player/game-week grain and
contains the source columns plus raw/canonical positions. The scoring SQL compiler
uses supported LoB player components and returns its unavailable component list.

```python
import duckdb
from ndat.analysis import (
    historical_threshold_events,
    positional_rank_curve,
    top_n_persistence,
)

with duckdb.connect("data/ndat.duckdb", read_only=True) as db:
    curve = positional_rank_curve(
        db, season=2025, positions=["QB", "RB", "WR", "TE"], profile="LoB"
    )
    persistence = top_n_persistence(
        db, position="TE", top_n=10, start_season=2023, end_season=2025,
        profile="LoB", horizon=1,
    )
    events = historical_threshold_events(
        db, positions=["TE", "WR"],
        predicates={"receiving_yards": 120, "receiving_tds": 2},
        start_season=2023, end_season=2025,
    )
```

Every result exposes `.sql`. A curve's `.rows` has `season`, `position`, `rank`,
`player_id`, `player_name`, and `fantasy_points`. Rank is a deterministic ordinal
`row_number`: equal scores are broken by `player_id`, rather than sharing a rank.
Persistence returns `.summary` with source/target season, eligible/repeat counts,
and repeat rate, plus `.players` with source/target rank and `repeated`; absence in
the next season is a non-repeat. Threshold `.rows` are matching player/game records,
so `.height` is the occurrence count. Predicates are simultaneous `>=` comparisons
on validated ordinary `player_game` fields, not a new query language.

All three functions use regular-season rows. Curve and persistence score at
player-season grain; threshold events remain at player-game grain.

## Real-data validation

Local completed 2023–2025 `player_stats` were used. For 2025 the first LoB players
were Josh Allen (QB, 364.62), Jonathan Taylor (RB, 316.30), Puka Nacua (WR,
246.00), and Trey McBride (TE, 189.90). TE top-10 persistence was 4/10 (40%) from
2023 to 2024 and 3/10 (30%) from 2024 to 2025. Examples inspected include Sam
LaPorta, George Kittle, Travis Kelce, and Trey McBride repeating from 2023, while
T.J. Hockenson did not. The WR/TE threshold example found 57 regular-season games
with at least 120 receiving yards and two receiving TDs across 2023–2025, including
TE matches by Tucker Kraft, Brock Bowers, Trey McBride, and Kyle Pitts in 2025.
