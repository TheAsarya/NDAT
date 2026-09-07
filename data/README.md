# Local data directory

This tracked file reserves the directory; the data itself is local and ignored.

- `source/<dataset>/season=<YYYY>/data.parquet` contains canonical, unchanged
  NDAT copies acquired from NFLverse through `nflreadpy`.
- `derived/` is reserved for reproducible NDAT-created datasets in later stages.
- `manifest.json` records source partition provenance and schemas.
- `ndat.duckdb` contains stable views over available source Parquet partitions.

Do not commit downloaded data, generated datasets, the manifest, or the DuckDB
catalogue.
