# NDAT

NDAT is an NFL Data Analysis Tool built on NFLverse. Its first analysis tracks
weekly linebacker defensive snap share as a configurable proxy for a full-time
role. See [`docs/stage-3-linebacker-roles.md`](docs/stage-3-linebacker-roles.md)
for the definition, scoring details, commands, and limitations.

Reusable named fantasy scoring and the first SQL-first analytical primitives are
documented in [`docs/stage-4-scoring-analysis.md`](docs/stage-4-scoring-analysis.md).
Stage 4 includes the complete non-PPR `LoB` profile, the shared `Stage3_IDP`
profile, position normalization, positional rank curves, top-N persistence, and
multi-predicate historical player-game thresholds. It does not include a saved
analysis catalogue or UI.

The authoritative development-stage roadmap, including the currently next planned
stage, is [`docs/development-stages.md`](docs/development-stages.md).

## Architecture and ownership

```text
NFLverse
   ↓  supported nflreadpy loaders
NDAT-managed source Parquet
   ↓
DuckDB catalogue views
   ├── ordinary SQL
   ├── Polars/Python
   └── future R
```

- **NFLverse / nflreadpy** owns upstream collection, cleaning, and supported access.
- **NDAT source data** is a deliberate project-managed Parquet copy of selected
  upstream datasets. The nflreadpy cache is not the canonical NDAT dataset.
- **DuckDB** supplies stable SQL names and a lightweight local catalogue. Views scan
  Parquet directly; NDAT does not duplicate source datasets into physical tables.
- **Polars/Python** may process the shared data but is not a competing datastore.
- **Future R code** will read the same standard Parquet files or open the same DuckDB
  catalogue. There will be no separate R data architecture.

See [`data/README.md`](data/README.md) for the exact on-disk convention.

## Setup

The project requires Python 3.12 and [uv](https://docs.astral.sh/uv/):

```powershell
uv sync
uv run pytest
```

The default data root is the repository's `data/` directory. Set
`NDAT_DATA_ROOT` to an alternative before running commands when bulk data must live
elsewhere. An explicit `DataConfig` can also be supplied by a future application.
Defaults are resolved from the project location, not the shell's current directory.

## Acquire and refresh data

Data lifecycle operations use the same `DataManager` API that a later CLI or UI can
call. The current thin command line requires explicit datasets and seasons:

```powershell
# Fetch only if the deterministic partition is absent
uv run python -m ndat.data fetch player_stats --season 2025
uv run python -m ndat.data fetch play_by_play --season 2025

# Deliberately replace one local partition from upstream
uv run python -m ndat.data refresh player_stats --season 2025

# Inspect only local state; this never performs a network request
uv run python -m ndat.data status

# Rebuild view definitions after moving an external data root/catalogue
uv run python -m ndat.data catalogue
```

Multiple `--season` arguments are accepted. A normal `fetch` skips existing
partitions, so repeated commands neither append duplicate rows nor create duplicate
copies. `refresh` replaces the Parquet partition and its provenance. Querying and
status inspection never refresh data automatically.

| Dataset command | DuckDB view | nflreadpy interface | Local status |
|---|---|---|---|
| `player_stats` | `player_stats` | `load_player_stats(..., summary_level="week")` | representative Stage 2 dataset |
| `play_by_play` | `play_by_play` | `load_pbp(...)` | representative Stage 2 dataset |
| `snap_counts` | `snap_counts` | `load_snap_counts(...)` | defined; fetched only on request |
| `participation` | `participation` | `load_participation(...)` | defined; fetched only on request |
| `rosters` | `rosters` | `load_rosters(...)` | defined; fetched only on request |
| `schedules` | `schedules` | `load_schedules(...)` | defined; fetched only on request |

No bulk source files are part of the repository. Which partitions are currently
downloaded is described by the local ignored `data/manifest.json` and the `status`
command, rather than by documentation that can go stale.

## Query with DuckDB

The ignored `data/ndat.duckdb` catalogue contains a view only when that dataset has
at least one local Parquet partition. Views use `union_by_name`, allowing compatible
upstream schema additions across seasons while the manifest records each schema.

```python
import duckdb

with duckdb.connect("data/ndat.duckdb", read_only=True) as connection:
    rows = connection.sql("""
        SELECT player_id, week, attempts
        FROM player_stats
        WHERE season = 2025
        ORDER BY attempts DESC
        LIMIT 10
    """).fetchall()
```

DuckDB views contain filesystem paths, so run the `catalogue` command after moving a
configured external data root. SQL execution itself remains entirely local.
When `player_stats` has its normal NFLverse schema, the catalogue also exposes
`player_game`, preserving `raw_position` and adding `canonical_position` for shared
scoring and analysis.

## Build the Stage 3 linebacker-role analysis

Fetch the four required source partitions explicitly, then build the derived data.
Analysis never downloads missing inputs:

```powershell
uv run python -m ndat.data fetch snap_counts --season 2025
uv run python -m ndat.data fetch rosters --season 2025
uv run python -m ndat.data fetch player_stats --season 2025
uv run python -m ndat.data fetch play_by_play --season 2025

# Default 85% threshold
uv run python -m ndat.lb_roles --season 2025

# Comparison at 80%; 80 is also accepted
uv run python -m ndat.lb_roles --season 2025 --threshold 0.80
```

Each threshold produces an ignored Parquet partition below
`data/derived/lb_weekly_role/`. All linebacker weeks, including non-qualifying
ones, remain in the Parquet data and the stable DuckDB view `lb_weekly_role`.

For the normal weekly workflow, one Python command can refresh the required source
partitions, build the 85% and 80% analyses, and create the formatted Excel workbook:

```powershell
uv run python -m ndat.lb_workbook --season 2026 --refresh
```

The workbook is written to
`data/derived/lb_weekly_role/season=2026/linebacker_roles_2026.xlsx`. Run the same
command again each week. Ranking bands and comparison settings are command-line
options; for example:

```powershell
uv run python -m ndat.lb_workbook --season 2026 --refresh `
  --primary-threshold 0.85 --comparison-threshold 0.80 `
  --top-rank 16 --second-rank 32 --recent-weeks 3
```

## Provenance

`data/manifest.json` is lightweight JSON metadata, not a data-version-control
system. For every source partition it records the dataset description, season,
project-relative (or external absolute) path, UTC acquisition time, row count,
column names and Polars types, a SHA-256 schema fingerprint, upstream identity
(`NFLverse via nflreadpy`), and the installed nflreadpy version. `status` also reports
whether recorded files remain present. The manifest and catalogue are ignored local
generated state.

## R interoperability

The season-partitioned layout supports game- and play-level data rather than only
player-season aggregates. nflreadpy currently exposes the inputs expected for the
planned three-down linebacker work: weekly stats, defensive snap counts,
play-by-play, play participation, rosters, and schedules. Participation is historical
from 2016 and excludes the in-progress season; snap counts are available from 2012.
Matching seasons use the already-defined partitions and join by NFLverse
player/game/team identifiers.

R can use `arrow::read_parquet("data/source/.../data.parquet")` for a partition or
`DBI::dbConnect(duckdb::duckdb(), "data/ndat.duckdb", read_only = TRUE)` to query the
same views. These examples describe future interoperability only; this stage does not
add an R environment or R dependencies.
