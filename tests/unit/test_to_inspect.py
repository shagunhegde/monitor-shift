import pytest
from control_arena import ControlTaskMetadata
from control_arena.monitor import full_trajectory_message_formatter_markdown
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser

from monitor_shift.errors import ConfigError
from monitor_shift.runner.to_inspect import control_metadata, to_messages
from monitor_shift.runner.truncate import TruncationRule, truncate
from monitor_shift.schema import Step, Trajectory


def make(steps: list[Step]) -> Trajectory:
    return Trajectory(
        id="t-1",
        source="fixture",
        rung="L2",
        task="Fix the parser.",
        steps=tuple(steps),
        label="attack",
        meta={},
    )


TRAJ = make(
    [
        Step(0, "ls", "a.py", "Let me look around.", None),
        Step(1, "", None, "Thinking out loud only.", None),
        Step(2, "cat a.py", None, None, None),
    ]
)


def test_actions_view_shows_calls_and_outputs_but_no_agent_text() -> None:
    msgs = to_messages(TRAJ, "actions")
    assistants = [m for m in msgs if isinstance(m, ChatMessageAssistant)]
    assert len(assistants) == 2
    assert all(m.text == "" for m in assistants)
    calls = [m.tool_calls[0] for m in assistants if m.tool_calls]
    assert [c.arguments["action"] for c in calls] == ["ls", "cat a.py"]
    assert all(c.view is not None and c.view.content == c.arguments["action"] for c in calls)
    tools = [m for m in msgs if isinstance(m, ChatMessageTool)]
    assert [t.text for t in tools] == ["a.py"]
    assert tools[0].tool_call_id == calls[0].id


def test_messages_view_shows_only_agent_text() -> None:
    msgs = to_messages(TRAJ, "messages")
    assert [m.text for m in msgs] == ["Let me look around.", "Thinking out loud only."]
    assert all(isinstance(m, ChatMessageAssistant) and not m.tool_calls for m in msgs)


def test_full_view_shows_everything() -> None:
    rendered = full_trajectory_message_formatter_markdown(to_messages(TRAJ, "full"))
    for text in ("Let me look around.", "Thinking out loud only.", "cat a.py", "a.py"):
        assert text in rendered


def test_the_task_is_not_repeated_in_the_transcript() -> None:
    for view in ("actions", "messages", "full"):
        assert not any(isinstance(m, ChatMessageUser) for m in to_messages(TRAJ, view))


def test_omission_markers_show_in_every_view() -> None:
    steps = [Step(i, f"cmd {i} " + "z" * 3_000, "ok", "why " * 300, None) for i in range(40)]
    short, report = truncate(make(steps), TruncationRule(max_tokens=12_000))
    assert report.steps_dropped
    for view in ("actions", "messages", "full"):
        notes = [m for m in to_messages(short, view) if isinstance(m, ChatMessageUser)]
        assert len(notes) == 1
        assert "omitted" in notes[0].text


def test_message_ids_are_unique() -> None:
    msgs = to_messages(TRAJ, "full")
    ids = [m.id for m in msgs]
    assert len(set(ids)) == len(ids)


def test_unknown_view_is_rejected() -> None:
    with pytest.raises(ConfigError):
        to_messages(TRAJ, "pixels")  # type: ignore[arg-type]


def test_metadata_carries_the_task_and_hides_the_label() -> None:
    meta = ControlTaskMetadata.model_validate(control_metadata(TRAJ))
    assert meta.main_task_description == "Fix the parser."
    assert meta.side_task_description == ""
    assert meta.eval_mode.value == "honest"  # never leak the attack label to a monitor
    assert meta.setting_name == "fixture"
