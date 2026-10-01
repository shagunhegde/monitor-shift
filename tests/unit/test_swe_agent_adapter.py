"""SWE-agent adapter on synthetic rows shaped like nebius/SWE-agent-trajectories."""

from typing import Any

import pytest

from monitor_shift.adapters.swe_agent import FetchedRow, SweAgentSource, parse_row, split_turn
from monitor_shift.errors import ConfigError

TASK_TEXT = (
    "We're currently solving the following issue within our repository. Here's the issue text:\n"
    "ISSUE:\nWidget.resize() crashes when width is zero\n\nSteps: call resize(0, 10).\n\n"
    "INSTRUCTIONS:\nNow, you're going to solve this issue on your own.\n"
)


def row(instance: str = "acme__widgets-42", model: str = "agent-x", **extra: Any) -> dict[str, Any]:
    return {
        "instance_id": instance,
        "model_name": model,
        "target": True,
        "exit_status": "submitted",
        "trajectory": [
            {"role": "system", "text": "", "system_prompt": "You are SWE-agent."},
            {"role": "user", "text": TASK_TEXT},
            {"role": "ai", "text": "Let's find the file first.\n\n```\nfind_file widget.py\n```"},
            {"role": "user", "text": "Found 1 matches:\n/acme/widgets/widget.py"},
            {
                "role": "ai",
                "text": "```\nedit 10:10\n    if width == 0:\n        return\nend_of_edit\n```",
            },
            {"role": "user", "text": "File updated."},
            {
                "role": "ai",
                "text": "I think the fix is complete, so I'll submit without a command block.",
            },
            {"role": "ai", "text": "Submitting.\n\n```\nsubmit\n```"},
        ],
        **extra,
    }


def test_split_turn_takes_the_last_fenced_block_as_the_action() -> None:
    assert split_turn("Look.\n\n```\nls -la\n```") == ("Look.", "ls -la")
    assert split_turn("```\nfirst\n```\nthen\n```\nsecond\n```") == (
        "```\nfirst\n```\nthen",
        "second",
    )
    assert split_turn("No command here.") == ("No command here.", "")


def test_parse_row_builds_task_steps_and_meta() -> None:
    traj = parse_row(row(), row_index=7, dataset_sha="abc123")
    assert traj is not None
    assert traj.id == "acme__widgets-42:agent-x:7"
    assert traj.source == "swe_agent"
    assert traj.rung == "L2"
    assert traj.label == "unknown"
    assert traj.task.startswith("Resolve this issue in the acme/widgets repository:")
    assert "Widget.resize() crashes" in traj.task
    assert "INSTRUCTIONS" not in traj.task
    assert [s.action for s in traj.steps] == [
        "find_file widget.py",
        "edit 10:10\n    if width == 0:\n        return\nend_of_edit",
        "",
        "submit",
    ]
    assert traj.steps[0].message == "Let's find the file first."
    assert traj.steps[0].observation == "Found 1 matches:\n/acme/widgets/widget.py"
    assert traj.steps[1].message is None
    assert traj.steps[2].message is not None
    assert traj.steps[3].observation is None
    assert traj.meta["repo"] == "acme/widgets"
    assert traj.meta["agent_model"] == "agent-x"
    assert traj.meta["resolved"] == "True"
    assert traj.meta["dataset_sha"] == "abc123"


def test_rows_without_an_issue_header_keep_the_whole_first_message() -> None:
    r = row()
    r["trajectory"][1]["text"] = "Fix the flaky test in tests/test_io.py."
    traj = parse_row(r, row_index=1, dataset_sha="s")
    assert traj is not None
    assert traj.task.endswith("Fix the flaky test in tests/test_io.py.")


def test_rows_with_no_agent_turns_are_skipped() -> None:
    r = row()
    r["trajectory"] = r["trajectory"][:2]
    assert parse_row(r, row_index=1, dataset_sha="s") is None


class FakeHub:
    def __init__(self, truncated: set[int] = frozenset()) -> None:  # type: ignore[assignment]
        self.truncated = truncated
        self.requested: list[int] = []

    def __call__(self, index: int) -> FetchedRow:
        self.requested.append(index)
        return FetchedRow(
            row=row(instance=f"acme__widgets-{index}"), truncated=index in self.truncated
        )


def test_source_samples_reproducibly_and_skips_truncated_rows() -> None:
    hub = FakeHub(truncated={0})
    source = SweAgentSource(fetch_row=hub, total_rows=1_000, dataset_sha="abc")
    first = source.load(n=20, seed=7)
    assert len(first) == 20
    assert [t.id for t in first] == [
        t.id for t in SweAgentSource(FakeHub({0}), 1_000, "abc").load(20, 7)
    ]
    assert len({t.id for t in first}) == 20
    assert source.skipped_truncated == (1 if 0 in hub.requested else 0)


def test_source_fingerprint_pins_the_dataset_revision() -> None:
    a = SweAgentSource(FakeHub(), 1_000, "sha-a").fingerprint()
    assert a == SweAgentSource(FakeHub(), 1_000, "sha-a").fingerprint()
    assert a != SweAgentSource(FakeHub(), 1_000, "sha-b").fingerprint()


def test_stratification_is_not_supported_yet() -> None:
    with pytest.raises(ConfigError):
        SweAgentSource(FakeHub(), 1_000, "s").load(n=5, seed=1, stratify=["model"])
