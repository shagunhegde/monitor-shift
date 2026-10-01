# monitor-shift

When an agent monitor is tuned to a 1% false-positive rate on public synthetic control settings,
what happens on real agent activity? `monitor-shift` converts agent logs (ControlArena, SWE-agent,
AI Village) into one trajectory format, scores them with ControlArena's monitors through Inspect,
calibrates thresholds on synthetic data, and measures how those thresholds behave on real logs.

**Status: milestone M1 (go/no-go spike) in progress.** Adapters for ControlArena and SWE-agent
logs, ControlArena monitors scored through Inspect under a spend cap, AgentDojo generation, and
the go/no-go report are built and tested offline. The paid spike and the AI Village adapter are
next. See [SPEC.md](SPEC.md) for the plan and [docs/decisions.md](docs/decisions.md) for what
was decided and why.

## Quickstart (no keys needed)

```bash
uv sync --all-extras
uv run mshift demo --fake     # fixtures -> fake monitors -> calibration -> ladder table
uv run mshift doctor          # what you still need for live runs, with one fix per problem
```

## Live runs

Live commands call models through OpenRouter and stop before passing `--max-usd`. Put your key
in `.env` at the repo root (it is git-ignored and loaded automatically):

```bash
printf 'OPENROUTER_API_KEY=%s\nMSHIFT_MODEL=openrouter/openai/gpt-6-luna\n' "$(pbpaste)" > .env
```

```bash
uv run mshift fetch swe-agent --n 50 --seed 7                 # real SWE-agent runs (free)
uv run mshift generate controlarena --mode honest --n 30 --model openrouter/qwen/qwen3.8-flash --max-usd 1.5
uv run mshift score --source L2-swe-agent-n50-s7 --monitors basic,hybrid --max-usd 2
uv run mshift spike --run <run name>                          # the M1 go/no-go report
./scripts/m1_spike.sh                                          # the whole M1 spike, $12.10 cap
```

Data and scores live in the cache directory (`mshift doctor` shows where), never in the repo.

## Development

```bash
uv run pytest -q              # offline: network sockets are blocked in tests
uv run pytest -q -m slow      # real AgentDojo on Inspect's mock model (~10 s)
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

## Data terms

AI Village data is used under AI Digest's research-only terms: no training without their
permission, no re-identification, cite AI Digest, and tell AI Digest about resulting publications. No AI Village text is ever committed to
this repo or included in a release. Releases carry record IDs and labels only.
