# Stage 5: saved and parameterised analysis library

Stage 5 makes human-authored SQL and the reusable Stage 4 Python primitives peers
in one discoverable local analysis library. The library supplies identity,
documentation, typed parameters, NDAT catalogue access, and readable terminal
output. It does not introduce a query language: SQL remains SQL, and Python
analyses retain their existing implementations and result shapes.

## Architecture

```text
queries/**/*.sql + optional adjacent TOML metadata
                         ┐
registered Python callable + in-code metadata
                         ┴─> discovery -> typed parameters -> NDAT connection
                                                           -> named result tables
```

`ndat.library` owns discovery, metadata validation, parameter conversion, safe SQL
binding, Python-result adaptation, and execution records. `ndat.query` is the thin
terminal interface. It resolves `DataConfig.from_project()` and opens the canonical
configured DuckDB catalogue read-only. SQL files never contain connection setup,
and running an analysis never refreshes data.

An `AnalysisExecution` records the definition, resolved parameter values, named
Polars tables, SQL text when available, and Stage 4 unsupported scoring components.
Named tables preserve heterogeneous results: ordinary analyses expose `rows`, while
`persistence.top-n` exposes `summary` and `players`, and the registered parlay-rate
analysis exposes `summary` and `weekly`.

## SQL source and the promotion workflow

Tracked, reusable SQL lives below repository-root `queries/`, organized by analysis
type rather than position. Stage 5 starts with:

```text
queries/historical/threshold_events/
├── receiving_threshold.sql
└── receiving_threshold.analysis.toml
```

There are two intentionally different workflows:

1. Any personal or exploratory `.sql` file can run directly with no metadata.
2. Add an adjacent `.analysis.toml` only when promoting it into the discoverable,
   safely parameterised library.

This keeps query writing frictionless. The sidecar is the durable declaration of
the information that SQL cannot expose consistently: stable ID, title,
description, tags, source file, and parameter types/defaults. It uses standard
TOML rather than a custom SQL-comment parser. The SQL remains directly editable in
VS Code and its location appears in `show` output.

A minimal sidecar is:

```toml
id = "collection.my-analysis"
title = "My analysis"
description = "What it answers."
execution = "sql"
source = "my_analysis.sql"
tags = ["collection"]
```

Parameter tables are optional. Add one for each `$name` used by DuckDB:

```toml
[parameters.position]
type = "string"
description = "Canonical position"
default = "TE"

[parameters.start_season]
type = "integer"
description = "First season, inclusive"
```

Supported CLI types are `string`, `integer`, `float`, `boolean`, `string_list`,
and `json_object`. Omitting `default` makes a parameter required. Lists use commas;
JSON objects primarily support direct invocation of the existing Stage 4 threshold
primitive. User values are passed to DuckDB as a named parameter dictionary; NDAT
does not interpolate them into SQL text. Structural SQL remains authored in SQL.

## Discover, inspect, and run

From the repository root in the VS Code terminal:

```powershell
uv run python -m ndat.query list
uv run python -m ndat.query show historical.receiving-threshold

uv run python -m ndat.query run historical.receiving-threshold `
  --param position=TE `
  --param yards=100 `
  --param touchdowns=2 `
  --param start_season=2020 `
  --param end_season=2025
```

Defaults in the supplied threshold analysis make this shorter equivalent valid:

```powershell
uv run python -m ndat.query run historical.receiving-threshold
```

An unregistered SQL file needs no sidecar and no library ID:

```powershell
uv run python -m ndat.query run queries/scratch/my_question.sql
```

Direct files are deliberately non-parameterised because no trusted type declaration
exists. Promote a query with a sidecar when it needs reusable CLI parameters.

The registered Stage 4 Python analyses use the same commands:

```powershell
uv run python -m ndat.query run fantasy.positional-rank-curve `
  --param season=2025 `
  --param positions=QB,RB,WR,TE

uv run python -m ndat.query run persistence.top-n `
  --param position=TE `
  --param top_n=10 `
  --param start_season=2023 `
  --param end_season=2025 `
  --param horizon=1

uv run python -m ndat.query run historical.threshold-events `
  --param positions=TE,WR `
  --param 'predicates={"receiving_yards":120,"receiving_tds":2}' `
  --param start_season=2023 `
  --param end_season=2025

uv run python -m ndat.query run historical.parlay-wr1-envelope `
  --param start_season=2021 `
  --param end_season=2025 `
  --param cohort_size=12 `
  --param standard_yards=60 `
  --param reduced_yards=40
```

## Included analyses and result meaning

| ID | Type | Result tables | Purpose |
|---|---|---|---|
| `historical.receiving-threshold` | saved SQL | `rows` | Qualifying player-games plus overall and per-season player-game frequency context |
| `historical.threshold-events` | Python | `rows` | Existing generic Stage 4 threshold primitive |
| `historical.parlay-wr1-envelope` | Python | `summary`, `weekly` | DuckDB weekly quartet retrieval followed by Python rate ranking and percentiles |
| `fantasy.positional-rank-curve` | Python | `rows` | Existing Stage 4 positional rank curve |
| `persistence.top-n` | Python | `summary`, `players` | Existing Stage 4 top-N persistence primitive |

The saved receiving analysis reports qualifying and denominator player-games,
percentage occurrence, 1-in-N player-game frequency, and season counts alongside
the underlying qualifying rows. Its denominator is regular-season player-games at
the selected canonical position. It is not the percentage of NFL games containing
a qualifying player and is not a true player-specific probability.

### SQL retrieval plus Python statistics

`historical.parlay-wr1-envelope` is the concrete Stage 5 example of a saved Python
analysis whose work naturally crosses the SQL/Python boundary:

```text
parlay_0002.sql
    -> weekly rows from DuckDB
    -> registered Python callable
    -> rate ordering and percentile interpolation
    -> summary + weekly tables
```

The SQL source selects each season's top receiving-yardage WR cohort, enumerates
every four-player combination among cohort members with a player-game in the same
regular-season week, designates each receiver once as the reduced-yardage leg, and
returns combinations, hits, and a hit rate for each season/week. The parameters are
bound values; Python is not embedded in the SQL file or a TOML sidecar.

The Python step sorts the weekly rates from highest to lowest, adds `rate_rank` and
`hit_pct`, and uses local linear interpolation to produce `weeks_analysed`,
`minimum_rate`, `p25`, `median`, `p75`, and `maximum_rate`. Rate statistics are
fractions from 0 to 1; `weekly.hit_pct` is included for terminal readability. A
period with no qualifying weekly combinations returns a one-row summary with zero
weeks and null rate statistics plus an empty, typed `weekly` table.

This estimates an empirical weekly cohort envelope, not the probability of one
specific four-player selection. Players in a quartet share an NFL week but need not
be in the same game. The retrieval source remains directly inspectable at
`queries/historical/threshold_events/parlay_0002.sql`; it is invoked through the
registered Python analysis because the post-query statistics are intentionally
Python-owned.

Terminal output includes identity, execution type, resolved parameter values, each
named table, and unsupported scoring components when a Stage 4 analysis reports
them. Empty tables retain their column names and print an explicit `No rows`
message. Generated SQL from Python primitives remains available on the execution
record; saved SQL retains its source path and source text.

## Extension rules and non-goals

- Put durable human-authored SQL under the analysis-type hierarchy in `queries/`.
- Use a position parameter instead of creating QB/RB/WR/TE directory trees.
- Register an existing Python callable directly when its arguments already fit;
  do not copy its generated SQL or add a wrapper solely for registration.
- Keep generated results under derived-data conventions, never in `queries/`.
- The linebacker workbook remains a separate workflow: its file generation and
  orchestration do not naturally fit a read-only analysis execution yet.

Stage 5 does not provide a filter/group/join DSL, natural-language querying, a UI,
DST semantics, R integration, remote execution, scheduled work, result caching, or
a persistent run-history database.
