"""Fit a trajectory into a monitor's input cap, and record what was cut.

Two passes. First, every long field keeps its head and tail around a marker. Then, if the whole
trajectory is still over the cap, middle steps are dropped: the first steps up to a quarter of
the budget and the last steps up to the rest, with one marker step saying how much was omitted.
The first and last steps always survive. Tokens are estimated as characters / 4; M1 compares
this estimate with the input tokens providers actually bill.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace

from monitor_shift.schema import Step, Trajectory, hash_text

OMISSION_PREFIX = "[monitor-shift] "


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def is_omission_marker(step: Step) -> bool:
    return not step.action and (step.message or "").startswith(OMISSION_PREFIX)


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = f"\n[... {len(text) - limit:,} characters cut by monitor-shift ...]\n"
    head = limit // 2
    return text[:head] + marker + text[len(text) - (limit - head) :], True


def _omission_text(n_steps: int, tokens: int) -> str:
    return (
        f"{OMISSION_PREFIX}{n_steps:,} steps (about {tokens:,} tokens) omitted here "
        "to fit the monitor's input cap."
    )


@dataclass(frozen=True)
class TruncationRule:
    max_tokens: int = 24_000  # whole trajectory, task included
    # Field caps are a safety valve for runaway outputs; the token cap does the real work.
    # SWE-agent file views run ~5,000 characters, so 2,000 clipped almost every L2 run (M1).
    max_text_chars: int = 6_000  # each action and message
    max_observation_chars: int = 6_000  # each tool output
    max_task_chars: int = 4_000
    head_share: float = 0.25  # share of the step budget kept from the start

    def __post_init__(self) -> None:
        if min(self.max_text_chars, self.max_observation_chars, self.max_task_chars) < 200:
            raise ValueError("field caps are too small to keep a readable head and tail")
        if self.max_tokens < self.min_tokens:
            raise ValueError(
                f"max_tokens={self.max_tokens} is too small: the task and the first and last "
                f"steps alone can need {self.min_tokens}"
            )

    @property
    def max_step_tokens(self) -> int:
        marker = 48  # longest field-cut marker, in characters
        chars = 2 * (self.max_text_chars + marker) + self.max_observation_chars + marker
        return estimate_tokens("x" * chars)

    @property
    def min_tokens(self) -> int:
        task = estimate_tokens("x" * (self.max_task_chars + 48))
        return task + 2 * self.max_step_tokens + 64

    @property
    def rule_hash(self) -> str:
        return hash_text(json.dumps(asdict(self), sort_keys=True))


@dataclass(frozen=True)
class TruncationReport:
    original_tokens: int
    final_tokens: int
    fields_clipped: int
    steps_dropped: int

    @property
    def truncated(self) -> bool:
        return self.fields_clipped > 0 or self.steps_dropped > 0


def _step_tokens(step: Step) -> int:
    return sum(estimate_tokens(f or "") for f in (step.action, step.observation, step.message))


def count_tokens(traj: Trajectory) -> int:
    return estimate_tokens(traj.task) + sum(_step_tokens(s) for s in traj.steps)


def truncate(traj: Trajectory, rule: TruncationRule) -> tuple[Trajectory, TruncationReport]:
    original = count_tokens(traj)
    clipped_count = 0

    def clip(text: str | None, limit: int) -> str | None:
        nonlocal clipped_count
        if text is None:
            return None
        out, cut = _clip(text, limit)
        clipped_count += cut
        return out

    task = clip(traj.task, rule.max_task_chars) or traj.task
    steps = [
        replace(
            s,
            action=clip(s.action, rule.max_text_chars) or "",
            observation=clip(s.observation, rule.max_observation_chars),
            message=clip(s.message, rule.max_text_chars),
        )
        for s in traj.steps
    ]

    costs = [_step_tokens(s) for s in steps]
    budget = rule.max_tokens - estimate_tokens(task)
    dropped = 0
    if sum(costs) > budget:
        budget -= estimate_tokens(_omission_text(len(steps), sum(costs)))
        head_end, used = 1, costs[0]
        while head_end < len(steps) - 1 and used + costs[head_end] <= budget * rule.head_share:
            used += costs[head_end]
            head_end += 1
        tail_start = len(steps) - 1
        used += costs[tail_start]
        while tail_start - 1 >= head_end and used + costs[tail_start - 1] <= budget:
            tail_start -= 1
            used += costs[tail_start]
        dropped = tail_start - head_end
        if dropped:
            gap = sum(costs[head_end:tail_start])
            marker = Step(index=0, action="", message=_omission_text(dropped, gap))
            steps = [*steps[:head_end], marker, *steps[tail_start:]]

    if not clipped_count and not dropped:
        return traj, TruncationReport(original, original, 0, 0)
    out = replace(
        traj,
        task=task,
        steps=tuple(replace(s, index=i) for i, s in enumerate(steps)),
        content_hash="",
    )
    return out, TruncationReport(original, count_tokens(out), clipped_count, dropped)
