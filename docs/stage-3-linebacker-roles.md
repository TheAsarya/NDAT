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

`player_id` in derived output is the GSIS ID when the roster bridge supplies one.
For an unmatched low-snap player it falls back explicitly to `pfr:<pfr_player_id>`;
the PFR ID is also preserved. Full-name resolution similarly falls back from roster
to player-stats display name to the full PFR snap-count name.

## Stage 3 IDP scoring

The small structured definition lives in `ndat.lb_roles.IDP_SCORING`.

| Category | Points | NFLverse weekly player-stat field |
|---|---:|---|
| Sack | 4 | `def_sacks` (fractional values preserved) |
| Total tackle | 1 | `def_tackles_solo + def_tackles_with_assist` |
| Blocked punt, PAT, or field goal | 5 | `def_punt_blocks + def_pat_blocks + def_fg_blocks` |
| Interception | 5 | `def_interceptions` |
| Fumble recovered | 2 | `fumble_recovery_opp` for the defensive snap-count player |
| Fumble forced | 4 | `def_fumbles_forced` |
| Safety | 8 | `def_safeties` |
| Stuff | 2 | `def_tackles_for_loss` (explicit proxy) |
| Pass defended | 1 | `def_pass_defended` |

NFLverse defines total tackles as solo tackles plus tackles made with an assist.
`def_tackle_assists` is not added again, avoiding double counting. The recovery
field is NFLverse's opponent-fumble recovery field; it is joined only to the weekly
defensive snap-count player.

NFLverse has no dedicated run-specific “stuff” field in weekly player stats. Stage 3
therefore explicitly maps “stuff” to the closest available statistic,
`def_tackles_for_loss`. That source field is broader than a strictly run-specific
stuff and the two concepts should not be assumed identical. The two-point proxy may
also stack with sack scoring when NFLverse credits both statistics. This limitation
is repeated on the generated visualization rather than being hidden in code.
Missing/null supported statistics score as zero.

## Build and query

Missing sources produce a clear error with the exact Stage 2 fetch commands. Fetch
is always explicit:

```powershell
uv run python -m ndat.data fetch snap_counts --season 2025
uv run python -m ndat.data fetch rosters --season 2025
uv run python -m ndat.data fetch player_stats --season 2025
```

Build 85% and 90% versions:

```powershell
uv run python -m ndat.lb_roles --season 2025
uv run python -m ndat.lb_roles --season 2025 --threshold 0.90
```

The output boundary is persisted because it gives future SQL a stable semantic
object without repeating identity and scoring joins. Each reproducible partition is
written to:

```text
data/derived/lb_weekly_role/season=<YYYY>/threshold=<fraction>/data.parquet
```

`data/ndat.duckdb` exposes their union as `lb_weekly_role`; filter
`role_threshold` when more than one cutoff exists. Every LB snap-count row remains
available. `qualifies_full_time` is independent from visualization filtering.

Longitudinal columns include `first_qualifying_week`, `qualifying_weeks`, current
and longest qualifying streak, `lost_after_qualifying`, `reacquired`, and a compact
`role_state`. A bye has no row and therefore does not create a false loss event.

The adjacent `linebacker_roles.html` is self-contained. It shows qualifying weeks
only, with teams and full player names in stable rows, weekly fantasy points as the
primary cell content, and snap share as smaller text and a tooltip. Acquisition and
reacquisition have restrained highlighting. Use `--html PATH` to choose another
output location.

## 2025 validation

The completed 2025 dataset contains 3,896 linebacker-game observations. There are
854 qualifying player-weeks at 85% and 729 at 90%, so the higher cutoff removes 125
borderline observations. All 32 teams and 116 qualifying players appear at 85%.
Full-season high-snap examples include Bobby Wagner, Zack Baun, Jack Campbell,
Kaden Elliss, and Demario Davis. Qualifying weekly point totals range from 0 to 25
after applying the tackle-for-loss proxy. Mid-range rotational players remain in the
derived data but are absent from qualifying visualization cells. Acquisition, loss,
and reacquisition events appear in real data; for example, Akeem Davis-Gaither loses
and later reacquires qualification.

The 85% view retains meaningful near-full-time weeks while still excluding typical
rotational deployment. The 90% comparison is materially stricter, but this finding
does not change the architectural default.
