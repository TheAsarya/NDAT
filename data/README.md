# Local data directory

This tracked file reserves the directory; the data itself is local and ignored.

- `source/<dataset>/season=<YYYY>/data.parquet` contains canonical, unchanged
  NDAT copies acquired from NFLverse through `nflreadpy`.
- `derived/lb_weekly_role/season=<YYYY>/threshold=<fraction>/data.parquet` contains
  reproducible Stage 3 linebacker-week role evidence.
- `derived/lb_weekly_role/season=<YYYY>/linebacker_roles_<YYYY>.xlsx` is the
  generated weekly workbook for the configured thresholds.
- `manifest.json` records source partition provenance and schemas.
- `ndat.duckdb` contains stable views over available source Parquet partitions.

Do not commit downloaded data, generated datasets, the manifest, or the DuckDB
catalogue.
