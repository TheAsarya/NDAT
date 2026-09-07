# Stage 3: linebacker snap-share roles

Stage 3 treats a linebacker as qualifying for a weekly full-time / three-down-proxy
role when the player's defensive snap share is at least a configurable threshold.
The default is 0.85 (85%), the architecture's initial working cutoff. It is an
analytical proxy, **not literal play-level proof of third-down participation**.
Personnel packages, down, play participation, and run/pass deployment are outside
this definition and remain possible future refinements.

## Source schema and identity

The analysis uses only local Stage 2 partitions:

- `snap_counts`: `game_id`, `season`, `week`, `pfr_player_id`, `player`, `position`,
  `team`, `defense_snaps`, and `defense_pct`. The percentage is already normalized
  to 0–1. The weekly PFR snap-count classification `position = 'LB'` is the
  linebacker selection rule.
- `rosters`: bridges `pfr_id` to `gsis_id` and supplies `full_name`, `first_name`,
  and `last_name`. The bridge is season/player based rather than team based so a
  player's weekly team continues to come from snap counts after a transaction.
- `player_stats`: uses canonical `player_id` (GSIS), plus season/week/game/team for
  the scoring join. A defender with no weekly stats row receives zero points rather
  than losing the snap-count observation.
- `play_by_play`: supplies qualifying rushing outcomes and credited defender IDs for
  the documented stuff approximation.

`player_id` in derived output is the GSIS ID when the roster bridge supplies one.
For an unmatched low-snap player it falls back explicitly to `pfr:<pfr_player_id>`;
the PFR ID is also preserved. Full-name resolution similarly falls back from roster
to player-stats display name to the full PFR snap-count name.

## Stage 3 IDP scoring

The shared named profile lives in `ndat/scoring_profiles/stage3_idp.toml` and is
loaded as `Stage3_IDP`. `ndat.lb_roles.IDP_SCORING` remains an introspection alias,
but scoring rules and NFLverse source mappings now come from the Stage 4 layer.

| Category | Points | NFLverse weekly player-stat field |
|---|---:|---|
| Sack | 4 | `def_sacks` (fractional values preserved) |
| Total tackle | 1 | `def_tackles_solo + def_tackles_with_assist` |
| Blocked punt, PAT, or field goal | 5 | `def_punt_blocks + def_pat_blocks + def_fg_blocks` |
| Interception | 5 | `def_interceptions` |
| Fumble recovered | 2 | `fumble_recovery_opp` for the defensive snap-count player |
| Fumble forced | 4 | `def_fumbles_forced` |
| Safety | 8 | `def_safeties` |
| Stuff | 2 | Derived approximation from `play_by_play` |
| Pass defended | 1 | `def_pass_defended` |

NFLverse defines total tackles as solo tackles plus tackles made with an assist.
`def_tackle_assists` is not added again, avoiding double counting. The recovery
field is NFLverse's opponent-fumble recovery field; it is joined only to the weekly
defensive snap-count player.

NFLverse has no direct ESPN “stuff” field, so Stage 3 uses a documented play-by-play
approximation rather than treating `def_tackles_for_loss` as the same statistic. A
valid stuff candidate is a recorded rushing attempt gaining zero or fewer yards,
excluding kneels, spikes, deleted plays, and aborted plays. Negative-yard plays use
the credited tackle-for-loss defender when available; zero-yard plays, plus the rare
negative play without TFL credit, use NFLverse's primary solo/tackle-with-assist
credit. Separate `assist_tackle_*` fields are not used because they represent assist
credit rather than the primary tackle attribution used by this approximation.

Each qualifying play contributes at most one stuff. If two primary defenders share
the selected credit, each receives 0.5; a candidate with no selected credited
defender is omitted rather than guessed. On the local 2025 data this rule found
credit for 1,890 of 2,404 candidate plays: 1,888 had one selected defender, two had
shared credit, and 514 had no defensible primary credit. This will not reproduce
ESPN exactly, but it retains a useful Stuff component while making the difference
auditable. Missing/null fields for other supported statistics still score as zero.

## Build and query

Missing sources produce a clear error with the exact Stage 2 fetch commands. Fetch
is always explicit:

```powershell
uv run python -m ndat.data fetch snap_counts --season 2025
uv run python -m ndat.data fetch rosters --season 2025
uv run python -m ndat.data fetch player_stats --season 2025
uv run python -m ndat.data fetch play_by_play --season 2025
```

Build individual 85% and 80% data partitions:

```powershell
uv run python -m ndat.lb_roles --season 2025
uv run python -m ndat.lb_roles --season 2025 --threshold 0.80
```

The normal weekly command refreshes all four inputs, builds both partitions, and
creates the Excel workbook:

```powershell
uv run python -m ndat.lb_workbook --season 2026 --refresh
```

Use `--top-rank`, `--second-rank`, and `--recent-weeks` to change the highlighting
bands and recent window. Use `--primary-threshold` and `--comparison-threshold` to
change the two snap-share cutoffs. `--regular-season-end` controls which week is the
last one included in season and recent-form highlights.

The output boundary is persisted because it gives future SQL a stable semantic
object without repeating identity and scoring joins. Each reproducible partition is
written to:

```text
data/derived/lb_weekly_role/season=<YYYY>/threshold=<fraction>/data.parquet
```

`data/ndat.duckdb` exposes their union as `lb_weekly_role`; filter
`role_threshold` when more than one cutoff exists. Every LB snap-count row remains
available. `qualifies_full_time` is independent from visualization filtering.
The raw `LB` selection is unchanged for compatibility. Derived rows additionally
preserve `raw_position` and expose `canonical_position`; explicit roster NGS EDGE
evidence is normalized to `EDGE`, while uncertain LB/OLB cases remain `LB`.

Longitudinal columns include `first_qualifying_week`, `qualifying_weeks`, current
and longest qualifying streak, `lost_after_qualifying`, `reacquired`, and a compact
`role_state`. A bye has no row and therefore does not create a false loss event.

The season workbook contains one matrix for each configured snap-share threshold
and a filterable weekly-detail sheet. Matrix cells show qualifying weeks only, with
weekly fantasy points and snap share. Weekly cell colours show scoring ranks;
player-name highlights show cumulative regular-season ranks; team-cell highlights
show ranks across the latest common NFL-week window. Playoffs are excluded from the
season and recent highlights. The title, explanatory note, header rows, team and
player columns remain frozen while navigating.

## 2025 validation

The completed 2025 dataset contains 3,896 linebacker-game observations. There are
854 qualifying player-weeks at 85% and 972 at 80%. All 32 teams and 116 qualifying
players appear at 85%.
Full-season high-snap examples include Bobby Wagner, Zack Baun, Jack Campbell,
Kaden Elliss, and Demario Davis. Mid-range rotational players remain in the
derived data but are absent from qualifying visualization cells. Acquisition, loss,
and reacquisition events appear in real data; for example, Akeem Davis-Gaither loses
and later reacquires qualification.

The 85% view retains meaningful near-full-time weeks while still excluding typical
rotational deployment. The 80% comparison exposes borderline roles without changing
the architectural default.
