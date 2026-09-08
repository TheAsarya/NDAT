# NDAT development stages

This is the authoritative repository reference for NDAT's development stages.
The architecture discussion defines architecture and stage boundaries; this document
records those decisions. Later stages may be refined or reordered there as real usage
informs the design.

## Current roadmap

| Stage | Status | Scope and key outputs | Completion / dependencies | Deferred work and non-goals |
|---|---|---|---|---|
| 1. Repository & Development Bootstrap | Complete | Python 3.12 and `uv` development baseline, reproducible project setup, and initial test workflow. | [`d04bb64`](https://github.com/TheAsarya/NDAT/commit/d04bb64) | — |
| 2. Canonical Local Data Layer | Complete | Project-managed NFLverse source Parquet, DuckDB catalogue views, provenance manifest, and explicit data lifecycle commands. | [`4cf5fa4`](https://github.com/TheAsarya/NDAT/commit/4cf5fa4) | NDAT remains an NFLverse analysis workspace, not a replacement for NFLverse. |
| 3. Linebacker Snap-Share Role Analysis / Tracking & Visualization | Complete | Configurable linebacker snap-share role analysis, shared IDP scoring, derived role data, and workbook workflow. | [`a956221`](https://github.com/TheAsarya/NDAT/commit/a956221); see [Stage 3 detail](stage-3-linebacker-roles.md). | The role threshold is an analytical proxy, not play-level proof of third-down deployment. |
| 4. Reusable Fantasy Scoring & Core Analytical Primitives | Complete | Named fantasy scoring profiles, position normalization, and Python/SQL-first primitives for rank curves, top-N persistence, and historical thresholds. | [`6532381`](https://github.com/TheAsarya/NDAT/commit/6532381); see [Stage 4 detail](stage-4-scoring-analysis.md). | DST/team-game materialized views remain deferred pending settled scoring semantics. No saved analysis catalogue or UI is included. |
| 5. Saved & Parameterised Analysis Library | **Next / planned** | A discoverable, parameterised library spanning saved SQL and existing Python analytical primitives. | Builds on the canonical data layer and Stage 4 primitives. | See [Stage 5 intent](#stage-5-intent). |
| 6. DST / Team-Game Scoring Semantics & Derived Views | Planned | Decide and implement team-game scoring semantics and resulting derived views. | Requires deliberate treatment of yards allowed, special teams, and other DST attribution. | Do not materialize a DST aggregation until those semantics are decided. |
| 7. Python / R Analytical Extensions | Planned | Selective R analytical capability alongside Python, sharing NDAT's DuckDB/Parquet data layer. | Depends on the shared canonical data layer. | Python remains the default orchestration/application language; R is introduced only when materially useful. |
| 8. Structured Analysis Definitions | Conditional / deferred | Consider higher-level structured definitions only if recurring domain concepts justify them. | Informed by usage of the saved analysis library. | Do not build a bespoke generic query DSL that recreates SQL. |
| 9. Natural-Language Interface | Conditional / deferred | Consider a natural-language interface after useful underlying analysis patterns are established. | Informed by real usage and any justified structured definitions. | Not a current implementation commitment. |

## Stage 5 intent

Stage 5 is a saved, discoverable, parameterised analysis library, not merely a
folder of `.sql` files.

- Saved SQL is a permanent first-class format. Human-authored SQL will likely live
  in a repository-root `queries/` hierarchy.
- One generic NDAT runner should provide connection and configuration, rather than
  each saved query carrying its own connection wrapper.
- SQL parameters should be safe, inspectable, and reusable. Saved analyses need
  lightweight identity and metadata: name, description, tags or collection,
  execution type, and parameter definitions.
- Existing Python analytical primitives remain first-class; not every analysis
  should be forced into SQL. Heterogeneous outputs may need more than one flat
  result table.
- Validate the design against real analysis types: historical threshold events,
  positional rank curves, top-N persistence, and role-analysis workflows that may
  not map neatly to saved SQL.

Avoid a heavyweight manifest, DSL, or schema unless the architecture discussion
explicitly approves it. Generated data and results must remain separate from saved
query source.

## Established principles

- DuckDB plus Parquet are the canonical local analytical data layer.
- Python is the default orchestration and application language.
- R may be added selectively, using the same DuckDB/Parquet data.
- Prefer real usage to speculative abstraction.

