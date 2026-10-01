"""Render a Trajectory as the Inspect messages ControlArena monitors read.

Every rung goes through this one rendering, so differences between rungs can't come from
formatting. Actions become tool calls whose `view` is the action text, so ControlArena's
formatters print it verbatim. The task is not repeated in the transcript, because the monitor
prompts already include it via ControlTaskMetadata.

Views:
- "actions": tool calls and their outputs, no agent text (basic, and hybrid's action half)
- "messages": agent text only (hybrid's message half)
- "full": both (constitutional)
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from control_arena import ControlTaskMetadata, EvalMode
from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolCallContent

from monitor_shift.errors import ConfigError
from monitor_shift.runner.truncate import is_omission_marker
from monitor_shift.schema import Trajectory

View = Literal["actions", "messages", "full"]
VIEWS: tuple[View, ...] = get_args(View)


def to_messages(traj: Trajectory, view: View) -> list[ChatMessage]:
    if view not in VIEWS:
        raise ConfigError(
            f"Unknown monitor view {view!r}.", hint=f"Use one of: {', '.join(VIEWS)}."
        )
    show_actions = view in ("actions", "full")
    show_text = view in ("messages", "full")
    messages: list[ChatMessage] = []
    for step in traj.steps:
        sid = f"s{step.index}"
        if is_omission_marker(step):
            messages.append(ChatMessageUser(id=f"{sid}-note", content=step.message or ""))
            continue
        text = (step.message or "") if show_text else ""
        calls: list[ToolCall] | None = None
        if show_actions and step.action.strip():
            calls = [
                ToolCall(
                    id=f"{sid}-call",
                    function="action",
                    arguments={"action": step.action},
                    view=ToolCallContent(format="text", content=step.action),
                )
            ]
        if not text.strip() and not calls:
            continue
        messages.append(ChatMessageAssistant(id=f"{sid}-agent", content=text, tool_calls=calls))
        if calls and step.observation is not None:
            messages.append(
                ChatMessageTool(
                    id=f"{sid}-output",
                    content=step.observation,
                    tool_call_id=calls[0].id,
                    function="action",
                )
            )
    return messages


def control_metadata(traj: Trajectory) -> dict[str, Any]:
    """ControlTaskMetadata for a monitor call.

    eval_mode is always HONEST: monitors must never learn a trajectory's label, and outside
    logs have no side task.
    """
    return ControlTaskMetadata(
        main_task_description=traj.task,
        side_task_description="",
        setting_description="",
        eval_mode=EvalMode.HONEST,
        setting_name=traj.source,
    ).model_dump()
