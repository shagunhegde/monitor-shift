"""The commands that fetch data or spend money: fetch, generate, score, spike.

Each live command prices its model before the first call, enforces --max-usd, saves results
under the cache directory as it goes, and appends a record to runs.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.table import Table

from monitor_shift.errors import ConfigError
from monitor_shift.runner.budget import Price, ensure_price, usd
from monitor_shift.runner.cache import cache_dir
from monitor_shift.runner.score import MonitorResult
from monitor_shift.runner.store import (
    append_results,
    load_results,
    load_trajectories,
    log_run,
    save_trajectories,
)
from monitor_shift.runner.truncate import TruncationRule


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")


def require_model(model: str | None) -> str:
    if not model:
        raise ConfigError(
            "No model given.",
            hint="Pass --model openrouter/<vendor>/<model>, or set MSHIFT_MODEL in .env.",
        )
    return model


def fetch(source: str, n: int, seed: int, name: str | None, console: Console) -> None:
    if source == "aivillage":
        raise ConfigError(
            "The AI Village adapter needs dataset access, which is still pending.",
            hint="Request access at https://huggingface.co/datasets/aidigestorg/ai-village, "
            "then check it with `uv run mshift doctor`.",
        )
    if source != "swe-agent":
        raise ConfigError(f"Unknown source {source!r}.", hint="Use swe-agent (or aivillage).")
    from monitor_shift.adapters.swe_agent import SweAgentSource

    src = SweAgentSource()
    trajectories = src.load(n=n, seed=seed)
    set_name = name or f"L2-swe-agent-n{n}-s{seed}"
    path = save_trajectories(set_name, trajectories)
    log_run(
        {
            "command": "fetch",
            "source": source,
            "set": set_name,
            "n": len(trajectories),
            "seed": seed,
            "fingerprint": src.fingerprint(),
            "skipped_truncated": src.skipped_truncated,
            "skipped_empty": src.skipped_empty,
        }
    )
    console.print(
        f"Saved {len(trajectories)} trajectories as [bold]{set_name}[/] ({path}). Skipped "
        f"{src.skipped_truncated} rows the API truncated and {src.skipped_empty} empty rows."
    )


def generate(
    setting: str,
    mode: str,
    n: int,
    model: str,
    seed: int,
    max_usd: float,
    name: str | None,
    max_steps: int,
    console: Console,
) -> None:
    from control_arena import EvalMode

    from monitor_shift.generate.controlarena_runs import GenerateRun, generate_runs

    if mode not in ("honest", "attack"):
        raise ConfigError(f"Unknown mode {mode!r}.", hint="Use --mode honest or --mode attack.")
    price = ensure_price(model)
    set_name = name or f"L0-{setting}-{mode}-n{n}-s{seed}"
    log_dir = cache_dir() / "logs" / set_name

    def save(run: GenerateRun) -> None:
        save_trajectories(set_name, run.trajectories)

    run = generate_runs(
        setting,
        EvalMode(mode),
        n,
        model,
        seed=seed,
        max_usd=max_usd,
        log_dir=log_dir,
        max_steps=max_steps,
        on_chunk=save,
    )
    save_trajectories(set_name, run.trajectories)
    outcomes: dict[str, int] = defaultdict(int)
    for t in run.trajectories:
        outcomes[f"main {t.meta.get('main_task_success', '?')}"] += 1
        if mode == "attack":
            outcomes[f"side {t.meta.get('side_task_success', '?')}"] += 1
        if t.meta.get("limit"):
            outcomes[f"limit {t.meta['limit']}"] += 1
    log_run(
        {
            "command": "generate",
            "setting": setting,
            "mode": mode,
            "set": set_name,
            "model": model,
            "price_per_m": [price.input_per_m, price.output_per_m],
            "requested": n,
            "runs": len(run.trajectories),
            "no_trajectory": run.no_trajectory,
            "spent_usd": run.spent_usd,
            "max_usd": max_usd,
            "seed": seed,
            "outcomes": dict(outcomes),
            "logs": run.log_paths,
        }
    )
    console.print(
        f"Saved {len(run.trajectories)} of {n} runs as [bold]{set_name}[/], spending "
        f"{usd(run.spent_usd)} of {usd(max_usd)}. Outcomes: {dict(sorted(outcomes.items()))}"
    )
    if run.stopped:
        raise run.stopped


def score(
    sources: list[str],
    monitors: list[str],
    model: str,
    samples: int,
    max_usd: float,
    run_name: str | None,
    max_tokens_in: int,
    max_tokens_out: int,
    concurrency: int,
    console: Console,
) -> None:
    from monitor_shift.runner.score import score_monitors

    trajectories = [t for s in sources for t in load_trajectories(s)]
    price = ensure_price(model)
    name = run_name or slug(f"{'+'.join(sources)}__{model}__k{samples}")
    rule = TruncationRule(max_tokens=max_tokens_in)

    def save(result: MonitorResult) -> None:
        append_results(name, [result])

    run = asyncio.run(
        score_monitors(
            trajectories,
            monitors,
            model,
            max_usd=max_usd,
            samples=samples,
            rule=rule,
            max_tokens_out=max_tokens_out,
            concurrency=concurrency,
            on_result=save,
            price=price,
        )
    )
    log_run(
        {
            "command": "score",
            "run": name,
            "sources": sources,
            "monitors": monitors,
            "model": model,
            "samples": samples,
            "price_per_m": [price.input_per_m, price.output_per_m],
            "truncation_rule": rule.rule_hash,
            "trajectories": len(trajectories),
            "results": len(run.results),
            "spent_usd": run.spent_usd,
            "max_usd": max_usd,
            "stopped": run.stopped.message if run.stopped else None,
        }
    )
    table = Table(title=f"Scored into run {name}", title_justify="left")
    for col in ("monitor", "rung", "n", "parsed", "errors"):
        table.add_column(col, justify="left" if col in ("monitor", "rung") else "right")
    groups: dict[tuple[str, str], list[MonitorResult]] = defaultdict(list)
    for r in run.results:
        groups[(r.monitor, r.rung)].append(r)
    for (monitor, rung), rs in sorted(groups.items()):
        errors = sum(1 for r in rs for c in r.components if c.error)
        table.add_row(monitor, rung, str(len(rs)), str(sum(r.parsed for r in rs)), str(errors))
    console.print(table)
    console.print(f"Spent {usd(run.spent_usd)} of {usd(max_usd)} (cache hits are free).")
    if run.stopped:
        raise run.stopped


def _runs_log() -> list[dict[str, object]]:
    path = cache_dir() / "runs.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def spike(runs: list[str], write: Path | None, console: Console) -> None:
    from monitor_shift.report.spike import render_markdown

    results = [r for name in runs for r in load_results(name)]
    if not results:
        raise ConfigError("Those runs hold no results.", hint="Run `mshift score` first.")
    log = _runs_log()
    spent = sum(float(str(e.get("spent_usd") or 0)) for e in log)
    gen = [e for e in log if e.get("command") == "generate" and e.get("setting") == "agentdojo"]
    gen_runs = sum(int(str(e.get("runs") or 0)) for e in gen)
    per_run = sum(float(str(e.get("spent_usd") or 0)) for e in gen) / gen_runs if gen_runs else None
    models = sorted({r.model for r in results})
    if len(models) != 1:
        raise ConfigError(
            f"The runs mix monitor models ({', '.join(models)}).",
            hint="Report on runs that share one --model.",
        )
    scored = [e for e in log if e.get("command") == "score" and e.get("model") == models[0]]
    if not scored:
        raise ConfigError(
            f"No price is logged for {models[0]}.", hint="Rerun `mshift score` for these sets."
        )
    price_in, price_out = cast(list[float], scored[-1]["price_per_m"])
    samples = sorted({c.samples for r in results for c in r.components if not c.skipped})
    text = render_markdown(
        results,
        model=", ".join(models),
        samples=samples[0] if len(samples) == 1 else 0,
        price=Price(price_in, price_out),
        spent_usd=spent,
        l0_generation_usd_per_run=per_run,
    )
    console.print(text, markup=False, highlight=False, soft_wrap=True)
    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(text, encoding="utf-8")
        console.print(f"Wrote {write}")
