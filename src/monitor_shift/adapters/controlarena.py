"""ControlArena eval logs (L0 AgentDojo, L1 BashArena) -> Trajectories.

Only what the agent did and saw goes in: assistant tool calls (rendered as `fn(arg=value)`),
visible assistant text, and tool results. The system prompt is dropped, because in attack mode
it carries the side task. ControlArena's own nudges (user messages after the task) are dropped
too and counted in meta. Hidden reasoning blocks are excluded, so L0 and L1 match the real
rungs, whose logs carry only what agents wrote visibly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, read_eval_log
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall

from monitor_shift.schema import Rung, Step, Trajectory


def render_call(call: ToolCall) -> str:
    args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in call.arguments.items())
    return f"{call.function}({args})"


def _score_values(sample: EvalSample) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, score in (sample.scores or {}).items():
        value: Any = score.value
        if isinstance(value, dict):
            for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
                values[str(key)] = str(item)  # pyright: ignore[reportUnknownArgumentType]
        else:
            values[name] = str(value)
    return values


def from_sample(sample: EvalSample, *, eval_id: str, rung: Rung, model: str) -> Trajectory | None:
    """One Inspect sample as a Trajectory; None if the agent never acted."""
    meta: dict[str, Any] = sample.metadata or {}
    turns: list[list[Any]] = []  # [action, observation parts, message]
    nudges = 0
    seen_task = False
    for msg in sample.messages:
        if isinstance(msg, ChatMessageAssistant):
            action = "\n".join(render_call(c) for c in msg.tool_calls or [])
            text = msg.text.strip()
            if action or text:
                turns.append([action, [], text or None])
        elif isinstance(msg, ChatMessageTool):
            if turns:
                turns[-1][1].append(msg.text)
        elif isinstance(msg, ChatMessageUser):
            if seen_task:
                nudges += 1
            seen_task = True
    if not turns:
        return None

    steps = tuple(
        Step(index=i, action=action, observation="\n".join(obs) if obs else None, message=text)
        for i, (action, obs, text) in enumerate(turns)
    )
    setting_meta: dict[str, Any] = meta.get("metadata") or {}
    trajectory_meta = {
        "setting": str(meta.get("setting_name") or ""),
        "main_task": str(meta.get("main_task_name") or ""),
        "side_task": str(meta.get("side_task_name") or ""),
        "suite": str(setting_meta.get("suite_name") or ""),
        "agent_model": model,
        "epoch": str(sample.epoch),
        "eval_id": eval_id,
        "scaffold_messages": str(nudges),
        "limit": sample.limit.type if sample.limit else "",
        **_score_values(sample),
    }
    return Trajectory(
        id=f"{eval_id}:{sample.id}:{sample.epoch}",
        source="controlarena",
        rung=rung,
        task=str(meta.get("main_task_description") or sample.input),
        steps=steps,
        label="attack" if meta.get("eval_mode") == "attack" else "honest",
        meta=trajectory_meta,
    )


def agent_model(log: EvalLog) -> str:
    """ControlArena runs the agent under the 'untrusted' role; the log's own model is none."""
    role = (log.eval.model_roles or {}).get("untrusted")
    if isinstance(role, list):  # a role may hold several configs; the first is the agent
        role = role[0] if role else None
    return role.model if role is not None else log.eval.model


def from_eval_log(log: EvalLog, rung: Rung) -> list[Trajectory]:
    model, eval_id = agent_model(log), log.eval.eval_id
    out = (from_sample(s, eval_id=eval_id, rung=rung, model=model) for s in log.samples or [])
    return [t for t in out if t is not None]


def load_eval_logs(paths: Iterable[str | Path], rung: Rung) -> Sequence[Trajectory]:
    return [t for path in paths for t in from_eval_log(read_eval_log(str(path)), rung)]
