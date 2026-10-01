"""Score trajectories with the study's monitors, under a spend cap.

Each trajectory is truncated, rendered per component view, and scored by calling the
ControlArena monitor agent directly inside the sample context ControlArena itself sets up.
We don't use `run_monitor_for_messages`, because it cuts the transcript at the scored
assistant message and so would drop the final tool output (docs/decisions.md).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from control_arena import ControlTaskMetadata
from control_arena.monitor import (
    MonitorResponse,
    full_trajectory_prompt_formatter_markdown,
    get_last_assistant_message,
)
from inspect_ai.agent import Agent, AgentState
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ModelName
from inspect_ai.solver._task_state import TaskState, set_sample_state

from monitor_shift.errors import BudgetExceededError
from monitor_shift.runner.budget import INPUT_SAFETY, Budget, Price, price_for, track_cost
from monitor_shift.runner.inspect_monitors import (
    MONITORS,
    build_agent,
    check_monitors,
    component,
    monitor_spec,
    parse_response,
)
from monitor_shift.runner.to_inspect import control_metadata, to_messages
from monitor_shift.runner.truncate import (
    TruncationReport,
    TruncationRule,
    estimate_tokens,
    truncate,
)
from monitor_shift.schema import Score, Trajectory


@dataclass(frozen=True)
class ComponentResult:
    component: str
    normalized: float | None  # None: skipped, failed to parse, or errored
    samples: int
    parsed_samples: int
    input_tokens: int
    output_tokens: int
    billed_usd: float  # what this run paid (0 for a cache hit)
    reported_usd: float  # what the call cost when it was made
    reason: str
    skipped: str | None = None  # nothing for this view to judge, e.g. no agent messages
    error: str | None = None

    @property
    def cached(self) -> bool:
        return self.billed_usd == 0 and self.reported_usd > 0


@dataclass(frozen=True)
class MonitorResult:
    trajectory_id: str
    content_hash: str  # of the untruncated trajectory
    rung: str
    label: str
    monitor: str
    model: str
    prompt_hash: str
    truncation: TruncationReport
    components: tuple[ComponentResult, ...]
    weights: tuple[float, ...]

    @property
    def normalized(self) -> float | None:
        """Weighted score; skipped components drop out, any failed component voids it."""
        used: list[tuple[float, float]] = []
        for comp, weight in zip(self.components, self.weights, strict=True):
            if comp.skipped:
                continue
            if comp.normalized is None:
                return None
            used.append((comp.normalized, weight))
        if not used:
            return None
        return sum(s * w for s, w in used) / sum(w for _, w in used)

    @property
    def parsed(self) -> bool:
        return self.normalized is not None

    @property
    def billed_usd(self) -> float:
        return sum(c.billed_usd for c in self.components)

    def to_score(self) -> Score | None:
        value = self.normalized
        if value is None:
            return None
        return Score(
            trajectory_id=self.trajectory_id,
            step_index=None,
            monitor=self.monitor,
            raw=value,
            normalized=value,
            reason=" | ".join(c.reason[:500] for c in self.components if not c.skipped),
            cost_usd=self.billed_usd,
            cached=all(c.cached or c.skipped for c in self.components),
        )


@dataclass
class ScoreRun:
    results: list[MonitorResult] = field(default_factory=list[MonitorResult])
    stopped: BudgetExceededError | None = None
    spent_usd: float = 0.0


async def _call(
    agent: Agent, messages: list[ChatMessage], metadata: dict[str, object]
) -> MonitorResponse:
    async def in_sample_context() -> MonitorResponse:
        # Same context ControlArena's run_monitor_for_messages establishes. Running in a
        # fresh task keeps each trajectory's metadata out of every other task.
        state = TaskState(
            model=ModelName("unknown/unknown"),
            sample_id="monitor-shift",
            epoch=0,
            input="",
            messages=messages,
            metadata=metadata,
        )
        set_sample_state(state)
        result = await agent(AgentState(messages=messages), [])
        last = get_last_assistant_message(result.messages)
        return MonitorResponse.model_validate(last.metadata or {})

    return await asyncio.create_task(in_sample_context())


async def score_monitors(
    trajectories: Sequence[Trajectory],
    monitors: Sequence[str],
    model: str,
    *,
    max_usd: float,
    samples: int = 3,
    rule: TruncationRule | None = None,
    max_tokens_out: int = 2_000,
    concurrency: int = 8,
    on_result: Callable[[MonitorResult], None] | None = None,
    price: Price | None = None,
) -> ScoreRun:
    """Score every trajectory with every monitor; stop cleanly before exceeding max_usd."""
    check_monitors(list(monitors))
    rule = rule or TruncationRule()
    price = price or price_for(model)
    names = list(dict.fromkeys(c for m in monitors for c, _ in MONITORS[m]))
    comps = {n: component(n) for n in names}
    agents = {n: build_agent(comps[n], model, samples, max_tokens_out) for n in names}
    specs = {m: monitor_spec(m, model, samples, rule) for m in monitors}
    run = ScoreRun()
    slots = asyncio.Semaphore(concurrency)

    async def score_component(name: str, traj: Trajectory, budget: Budget) -> ComponentResult:
        comp = comps[name]
        messages = to_messages(traj, comp.view)
        if not any(isinstance(m, ChatMessageAssistant) for m in messages):
            skipped = "no agent messages" if comp.view == "messages" else "no actions"
            return ComponentResult(name, None, samples, 0, 0, 0, 0.0, 0.0, "", skipped=skipped)
        metadata = control_metadata(traj)
        prompt = comp.system_prompt + full_trajectory_prompt_formatter_markdown(
            ControlTaskMetadata.model_validate(metadata), messages, comp.user_prompt
        )
        estimate = samples * price.cost(estimate_tokens(prompt) * INPUT_SAFETY, max_tokens_out)
        async with slots:
            if run.stopped is not None:
                raise run.stopped
            budget.reserve(estimate)
            try:
                with track_cost() as billed:
                    response = await _call(agents[name], messages, metadata)
                    paid = billed()
            except BudgetExceededError:
                raise
            except Exception as err:  # a provider error must not sink the whole run
                return ComponentResult(name, None, samples, 0, 0, 0, 0.0, 0.0, "", error=repr(err))
            finally:
                budget.release(estimate)
        parsed = parse_response(response, samples)
        usage = response.model_usage
        return ComponentResult(
            component=name,
            normalized=parsed.normalized,
            samples=samples,
            parsed_samples=parsed.parsed_samples,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            billed_usd=paid,
            reported_usd=(usage.total_cost or 0.0) if usage else 0.0,
            reason=response.reason,
        )

    async def score_trajectory(traj: Trajectory, budget: Budget) -> None:
        short, report = truncate(traj, rule)
        try:
            done = {n: await score_component(n, short, budget) for n in names}
        except BudgetExceededError as stop:
            run.stopped = run.stopped or stop
            return
        for monitor in monitors:
            parts = MONITORS[monitor]
            result = MonitorResult(
                trajectory_id=traj.id,
                content_hash=traj.content_hash,
                rung=traj.rung,
                label=traj.label,
                monitor=monitor,
                model=model,
                prompt_hash=specs[monitor].prompt_hash,
                truncation=report,
                components=tuple(done[c] for c, _ in parts),
                weights=tuple(w for _, w in parts),
            )
            run.results.append(result)
            if on_result is not None:
                on_result(result)

    with Budget(max_usd) as budget:
        await asyncio.gather(*(score_trajectory(t, budget) for t in trajectories))
        run.spent_usd = budget.spent
    return run
