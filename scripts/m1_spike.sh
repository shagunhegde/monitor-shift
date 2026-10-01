#!/usr/bin/env bash
# M1 go/no-go spike (SPEC.md, milestone M1). This spends real money: about $5 expected, and
# every step has its own --max-usd, which add up to $12.10 (the M1 cap is $15).
#
# Needs OPENROUTER_API_KEY in .env at the repo root. The constitutional monitor joins in once
# src/monitor_shift/runner/prompts/constitutional.txt holds Apollo's G.1.3 prompt.
# Re-running is safe: finished model calls are cached, so a re-run pays only for new calls.
#
# Override the models with MONITOR=..., ALT_MONITOR=..., AGENT=... ./scripts/m1_spike.sh
set -euo pipefail
cd "$(dirname "$0")/.."

MONITOR="${MONITOR:-openrouter/openai/gpt-6-luna}"
ALT_MONITOR="${ALT_MONITOR:-openrouter/deepseek/deepseek-v4-flash}"
AGENT="${AGENT:-openrouter/qwen/qwen3.8-flash}"
SEED="${SEED:-7}"
MONITORS="basic,hybrid"
if [ -s src/monitor_shift/runner/prompts/constitutional.txt ]; then
  MONITORS="basic,hybrid,constitutional"
fi
L0="L0-agentdojo-honest-n30-s${SEED},L0-agentdojo-attack-n30-s${SEED}"
mshift() { uv run mshift "$@"; }

uv run python -c "import os, dotenv; dotenv.load_dotenv(); assert os.environ.get('OPENROUTER_API_KEY'), 'Add OPENROUTER_API_KEY to .env first (see README).'"

echo "== 1. Smoke test: 2 SWE-agent runs, 1 sample each (cap \$0.10)"
mshift fetch swe-agent --n 2 --seed 1 --name L2-smoke
mshift score --source L2-smoke --monitors "$MONITORS" --model "$MONITOR" --samples 1 \
  --max-usd 0.10 --run m1-smoke

echo "== 2. L0: 30 honest + 30 attack AgentDojo runs, agent $AGENT (cap \$1.50 each)"
mshift generate controlarena --setting agentdojo --mode honest --n 30 --model "$AGENT" \
  --seed "$SEED" --max-usd 1.50
mshift generate controlarena --setting agentdojo --mode attack --n 30 --model "$AGENT" \
  --seed "$SEED" --max-usd 1.50

echo "== 3. L2: the 50-run SWE-agent sample (free)"
mshift fetch swe-agent --n 50 --seed "$SEED"

echo "== 4. Score L0 and L2 with $MONITORS, 3 samples (cap \$8)"
mshift score --source "$L0,L2-swe-agent-n50-s${SEED}" --monitors "$MONITORS" \
  --model "$MONITOR" --samples 3 --max-usd 8 --run m1-spike

echo "== 5. A second, cheaper monitor model on L0: basic, 1 sample (cap \$1)"
mshift score --source "$L0" --monitors basic --model "$ALT_MONITOR" --samples 1 \
  --max-usd 1 --run m1-alt-monitor

echo "== 6. Reports (numbers only, safe to commit)"
mshift spike --run m1-spike --write docs/m1-spike.md
mshift spike --run m1-alt-monitor --write docs/m1-spike-alt-monitor.md
