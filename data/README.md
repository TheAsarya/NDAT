# Local data directory

This tracked file reserves the directory; the data itself is local and ignored.

- `source/<dataset>/season=<YYYY>/data.parquet` contains canonical, unchanged
  NDAT copies acquired from NFLverse through `nflreadpy`.
- `derived/lb_weekly_role/season=<YYYY>/threshold=<fraction>/data.parquet` contains
  reproducible Stage 3 linebacker-week role evidence. The adjacent HTML is its
  generated team-grouped visualization.
- `manifest.json` records source partition provenance and schemas.
- `ndat.duckdb` contains stable views over available source Parquet partitions.

Do not commit downloaded data, generated datasets, the manifest, or the DuckDB
catalogue.
