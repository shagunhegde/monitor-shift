"""Generate L0 runs with ControlArena: get_control_task_product + inspect eval, under a cap.

Honest runs use ControlArena's untrusted policy in honest mode; attack runs use attack mode, in
which the agent is told to pursue a hidden AgentDojo side task (not third-party prompt
injection; see docs/decisions.md). Samples are drawn in a seeded order that uses every task once
before repeating any, so n beyond the task count adds epochs evenly. Runs go in chunks: each
chunk is sized from the costliest run so far, and every run carries an Inspect cost_limit of
(remaining budget / chunk size), so the total can't pass --max-usd.
"""

from __future__ import annotations

import copy
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from control_arena import EvalMode
from control_arena.eval import ControlEvalConfig, get_control_task_product
from control_arena.policy import untrusted_policy_builder
from control_arena.settings._setting import Setting
from control_arena.settings.agentdojo_setting.agentdojo_setting import AgentDojoSetting
from control_arena.settings.bash_arena.bash_arena_setting import BashArenaSetting
from inspect_ai import eval as inspect_eval  # pyright: ignore[reportUnknownVariableType]
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog

from monitor_shift.adapters.controlarena import from_eval_log
from monitor_shift.errors import BudgetExceededError, ConfigError
from monitor_shift.runner.budget import Price, price_for, register_price, usd
from monitor_shift.schema import Rung, Trajectory

SETTINGS: dict[str, tuple[Callable[[], Setting], Rung]] = {
    "agentdojo": (AgentDojoSetting, "L0"),
    "bash_arena": (BashArenaSetting, "L1"),  # needs a local Docker daemon (docs/decisions.md)
}
FIRST_CHUNK = 5
PLACEHOLDER_MODEL = "none/none"
GROWTH = 2.0  # assume a run may cost twice the costliest one seen so far


@dataclass
class GenerateRun:
    requested: int
    trajectories: list[Trajectory] = field(default_factory=list[Trajectory])
    log_paths: list[str] = field(default_factory=list[str])
    spent_usd: float = 0.0
    no_trajectory: int = 0  # samples where the agent never acted
    stopped: BudgetExceededError | None = None


def plan_samples(dataset: Sequence[Sample], n: int, seed: int) -> list[Sample]:
    """n samples, every task used once per round, each round in a fresh seeded order."""
    if not dataset:
        raise ConfigError(
            "The setting returned no samples.", hint="Check --setting and its filters."
        )
    rng = random.Random(seed)
    planned: list[Sample] = []
    for round_ in range(math.ceil(n / len(dataset))):
        order = list(dataset)
        rng.shuffle(order)
        for sample in order:
            if round_:
                sample = copy.copy(sample)
                sample.id = f"{sample.id}__r{round_}"
            planned.append(sample)
    return planned[:n]


def _sample_costs(log: EvalLog) -> list[float]:
    return [
        sum(u.total_cost or 0.0 for u in (s.model_usage or {}).values()) for s in log.samples or []
    ]


def generate_runs(
    setting: str,
    mode: EvalMode,
    n: int,
    model: str,
    *,
    seed: int,
    max_usd: float,
    log_dir: Path,
    max_steps: int = 25,
    token_limit: int = 200_000,
    on_chunk: Callable[[GenerateRun], None] | None = None,
    require_price: bool = True,
) -> GenerateRun:
    if setting not in SETTINGS:
        raise ConfigError(
            f"Can't generate runs for setting {setting!r} yet.",
            hint=f"Use one of: {', '.join(SETTINGS)}.",
        )
    if require_price:
        price_for(model)  # an unpriced model would make --max-usd unenforceable
        # ControlArena runs the agent under a role, so the eval's own model is a placeholder
        # that never generates; Inspect's cost_limit still wants a price for it.
        register_price(PLACEHOLDER_MODEL, Price(0.0, 0.0))
    make_setting, rung = SETTINGS[setting]
    env = make_setting()
    planned = plan_samples(env.get_dataset(mode), n, seed)
    run = GenerateRun(requested=n)
    costliest: float | None = None
    i = 0
    while i < len(planned):
        remaining = max_usd - run.spent_usd
        if not costliest:  # nothing seen yet, or every run so far was free
            size = FIRST_CHUNK if costliest is None else len(planned)
        else:
            size = max(1, math.floor(remaining / (GROWTH * costliest)))
        size = min(size, len(planned) - i, 50)
        per_run_cap = remaining / size
        if costliest and per_run_cap < GROWTH * costliest:
            run.stopped = BudgetExceededError(
                f"Stopped before exceeding --max-usd {usd(max_usd)} after {len(run.trajectories)} "
                f"of {n} runs: {usd(remaining)} left, and a run has cost up to {usd(costliest)}.",
                hint="Raise --max-usd, or keep the runs so far: they are saved.",
            )
            break
        chunk = planned[i : i + size]
        config = ControlEvalConfig(
            untrusted_model=model,
            trusted_model=model,
            max_steps=max_steps,
            token_limit=token_limit,
            log_dir=str(log_dir),
        )
        tasks = get_control_task_product(
            env, untrusted_policy_builder(), [mode], eval_config=config, datasets=[chunk]
        )
        cap = per_run_cap if require_price else None
        logs = inspect_eval(tasks, display="none", cost_limit=cap, **config.eval_args())
        for log in logs:
            costs = _sample_costs(log)
            run.spent_usd += sum(costs)
            costliest = max([costliest or 0.0, *costs])
            made = from_eval_log(log, rung)
            run.no_trajectory += len(log.samples or []) - len(made)
            run.trajectories.extend(made)
            run.log_paths.append(log.location)
        i += size
        if on_chunk is not None:
            on_chunk(run)
    return run
