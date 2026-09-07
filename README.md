# NDAT

NDAT is an NFL Data Analysis Tool built on NFLverse. Stage 2 establishes a
canonical, inspectable local data layer; it does not yet provide saved analyses,
fantasy scoring, linebacker-role inference, dashboards, or natural-language queries.

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

## Provenance

`data/manifest.json` is lightweight JSON metadata, not a data-version-control
system. For every source partition it records the dataset description, season,
project-relative (or external absolute) path, UTC acquisition time, row count,
column names and Polars types, a SHA-256 schema fingerprint, upstream identity
(`NFLverse via nflreadpy`), and the installed nflreadpy version. `status` also reports
whether recorded files remain present. The manifest and catalogue are ignored local
generated state.

## Stage 3 readiness and R interoperability

The season-partitioned layout supports game- and play-level data rather than only
player-season aggregates. nflreadpy currently exposes the inputs expected for the
planned three-down linebacker work: weekly stats, defensive snap counts,
play-by-play, play participation, rosters, and schedules. Participation is historical
from 2016 and excludes the in-progress season; snap counts are available from 2012.
Stage 3 can fetch matching seasons into the already-defined partitions and join by
NFLverse player/game/team identifiers. Stage 2 does not infer any roles.

R can use `arrow::read_parquet("data/source/.../data.parquet")` for a partition or
`DBI::dbConnect(duckdb::duckdb(), "data/ndat.duckdb", read_only = TRUE)` to query the
same views. These examples describe future interoperability only; this stage does not
add an R environment or R dependencies.
