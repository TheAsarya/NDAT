# NDAT repository instructions

Architectural decisions made in the main architecture discussion take precedence over speculative improvements suggested by implementation chats.

## Repository workflow

- Work in the existing repository checkout. Do not reclone the repository or create additional worktrees, copies, or nested repositories unless the architecture chat explicitly requests it.
- Normally work directly on `main`.
- Before editing, inspect `git status`, verify the current branch and configured remote, and fetch or synchronise with the remote as appropriate. Preserve pre-existing user changes and never overwrite unrelated local work.
- Do not use destructive Git commands merely to obtain a clean tree. Do not force-push or rewrite published history unless explicitly instructed.
- Completed stages should normally be committed with a meaningful message and pushed to `origin/main`. If the remote has advanced, integrate it safely; a rejected push is never grounds for force-pushing.
- Before committing or pushing, run validation appropriate to the stage. Leave the repository in a clean, reproducible state where practicable.

## Scope discipline

- Implement only the requested stage and small changes genuinely necessary to make it correct. Do not pre-implement future architecture.
- Report useful additional work as a recommendation for the architecture chat rather than silently expanding scope.
- Prefer mature existing libraries over recreating their functionality. NFLverse remains the upstream NFL data source and must not be reimplemented locally.

## Environment

- Use the repository-local `.venv`; do not create ad-hoc virtual environments elsewhere for this project.
- Do not commit `.venv`, caches, downloaded data sets, generated outputs, credentials, or other machine-specific state.
- `pyproject.toml` and `uv.lock` are the authoritative dependency and environment definition. Setup must be reproducible from a fresh clone, normally with `uv sync`.

## Code quality

- Prefer clear, small modules and explicit interfaces over premature framework-building. Add dependencies only when justified.
- Keep data, application state, source code, and generated/cache data conceptually distinct.
- Add tests appropriate to implemented behaviour and do not weaken tests merely to make a stage pass.
