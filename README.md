# NDAT

NDAT is a staged bootstrap for a flexible NFL and fantasy-football analysis workspace built around upstream NFLverse data. This repository currently contains development infrastructure only; it does not yet implement data ingestion, analysis, storage, visualisation, or an application interface.

## Development setup

This project requires Python 3.12 and [uv](https://docs.astral.sh/uv/). From the existing repository checkout, create or synchronise the repository-local environment with:

```powershell
uv sync
```

Run the current bootstrap validation with:

```powershell
uv run pytest
```

Implementation normally proceeds through staged Codex work in this existing checkout on `main`. Review `AGENTS.md` before beginning a stage; it defines the shared repository and scope rules.
