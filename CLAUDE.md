# monitor-shift: notes for Claude Code

## Commands
- uv sync --all-extras
- uv run pytest -q                          # offline, seconds
- uv run ruff check . && uv run pyright
- uv run ruff format .                      # CI runs `ruff format --check .`
- uv run mshift doctor                      # keys, dataset access, cache
- uv run mshift demo --fake                 # end to end on fixtures, no network

## Rules
- SPEC.md is the source of truth; one milestone at a time.
- Monitors come from ControlArena; model calls go through Inspect. Our code:
  adapters, the trajectory schema, calibration, sampling, adjudication, stats, reports.
- stats/ is pure numpy/scipy; adapters/ and runner/ own all I/O.
- Never commit AI Village text. Fixtures are synthetic.
- PREREG.md is frozen once tagged prereg-v1; deviations go in docs/deviations.md.
- Every error class carries a `hint`.
