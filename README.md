# monitor-shift

When an agent monitor is tuned to a 1% false-positive rate on public synthetic control settings,
what happens on real agent activity? `monitor-shift` converts agent logs (ControlArena, SWE-agent,
AI Village) into one trajectory format, scores them with ControlArena's monitors through Inspect,
calibrates thresholds on synthetic data, and measures how those thresholds behave on real logs.

**Status: milestone M0 (skeleton).** The schema, synthetic fixtures, a fake monitor, `doctor` and
an offline demo are in place. Real adapters and live scoring arrive in M1 and M2. See
[SPEC.md](SPEC.md) for the full plan.

## Quickstart (no keys needed)

```bash
uv sync --all-extras
uv run mshift demo --fake     # fixtures -> fake monitors -> calibration -> ladder table
uv run mshift doctor          # what you still need for live runs, with one fix per problem
```

## Development

```bash
uv run pytest -q              # offline: sockets are blocked in tests
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

## Data terms

AI Village data is used under AI Digest's research-only terms: no training without their
permission, no re-identification, and cite AI Digest. No AI Village text is ever committed to
this repo or included in a release. Releases carry record IDs and labels only.
