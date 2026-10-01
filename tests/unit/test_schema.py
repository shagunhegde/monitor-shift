import json
from dataclasses import replace
from typing import Any

import pytest
from syrupy.assertion import SnapshotAssertion

from monitor_shift.errors import SchemaError
from monitor_shift.schema import (
    MonitorSpec,
    Score,
    Step,
    Trajectory,
    compute_content_hash,
    hash_text,
)


def make_steps(n: int = 2) -> tuple[Step, ...]:
    return tuple(
        Step(index=i, action=f"ls dir{i}", observation="a.txt", message=None, timestamp=None)
        for i in range(n)
    )


def make_traj(**overrides: Any) -> Trajectory:
    fields: dict[str, Any] = {
        "id": "t-1",
        "source": "fixture",
        "rung": "L0",
        "task": "List the files.",
        "steps": make_steps(),
        "label": "honest",
        "meta": {"agent": "a"},
    }
    fields.update(overrides)
    return Trajectory(**fields)


# --- Step -----------------------------------------------------------------------------------


def test_step_needs_an_action_or_a_message() -> None:
    with pytest.raises(SchemaError):
        Step(index=0, action="  ", observation=None, message=None, timestamp=None)
    assert Step(index=0, action="", observation=None, message="thinking", timestamp=None)


def test_step_index_is_non_negative() -> None:
    with pytest.raises(SchemaError):
        Step(index=-1, action="ls", observation=None, message=None, timestamp=None)


# --- Trajectory -----------------------------------------------------------------------------


def test_content_hash_is_computed_on_construction() -> None:
    traj = make_traj()
    assert traj.content_hash == compute_content_hash(traj.task, traj.steps)
    assert len(traj.content_hash) == 64


def test_content_hash_covers_only_what_the_monitor_sees() -> None:
    base = make_traj()
    same_content = make_traj(id="t-2", label="unknown", rung="L3", meta={"agent": "b"})
    assert base.content_hash == same_content.content_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"task": "List the files, please."},
        {"steps": make_steps(3)},
        {"steps": (Step(0, "ls dir0", "b.txt", None, None), make_steps()[1])},
        {"steps": (Step(0, "ls dir0", "a.txt", "hmm", None), make_steps()[1])},
        {"steps": (Step(0, "ls dir0", "a.txt", None, "2026-01-01T00:00:00Z"), make_steps()[1])},
    ],
)
def test_content_hash_changes_with_content(overrides: dict[str, Any]) -> None:
    assert make_traj(**overrides).content_hash != make_traj().content_hash


def test_stale_content_hash_is_rejected_with_a_hint() -> None:
    with pytest.raises(SchemaError) as info:
        make_traj(content_hash="0" * 64)
    assert info.value.hint


def test_matching_content_hash_is_accepted() -> None:
    traj = make_traj()
    assert make_traj(content_hash=traj.content_hash) == traj


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": " "},
        {"task": ""},
        {"task": "   \n"},
        {"steps": ()},
        {"steps": (Step(1, "ls", None, None, None),)},
        {"steps": (Step(0, "ls", None, None, None), Step(2, "ls", None, None, None))},
        {"source": "somewhere"},
        {"rung": "L9"},
        {"label": "benign"},
        {"meta": {"agent": 3}},
    ],
)
def test_invalid_trajectories_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(SchemaError) as info:
        make_traj(**overrides)
    assert info.value.hint


def test_meta_is_read_only() -> None:
    traj = make_traj()
    with pytest.raises(TypeError):
        traj.meta["agent"] = "b"  # type: ignore[index]


def test_meta_is_copied_from_caller() -> None:
    meta = {"agent": "a"}
    traj = make_traj(meta=meta)
    meta["agent"] = "b"
    assert traj.meta["agent"] == "a"


def test_trajectories_are_hashable_and_comparable() -> None:
    assert len({make_traj(), make_traj(), make_traj(id="t-2")}) == 2


def test_dict_round_trip_is_json_safe() -> None:
    traj = make_traj(meta={"agent": "a", "month": "2026-01"})
    payload = json.loads(json.dumps(traj.to_dict()))
    assert Trajectory.from_dict(payload) == traj


def test_replace_recomputes_nothing_silently() -> None:
    traj = make_traj()
    with pytest.raises(SchemaError):
        replace(traj, task="A different task.")
    fresh = replace(traj, task="A different task.", content_hash="")
    assert fresh.content_hash != traj.content_hash


def test_hash_scheme_is_pinned(snapshot: SnapshotAssertion) -> None:
    """Changing the hashing scheme invalidates every cache entry, so it must be deliberate."""
    assert make_traj().content_hash == snapshot
    assert hash_text("monitor prompt") == snapshot


# --- MonitorSpec and Score ------------------------------------------------------------------


def test_monitor_spec_defaults_follow_lite_scope() -> None:
    spec = MonitorSpec(name="basic", unit="trajectory", prompt_hash="p", model="m")
    assert spec.samples == 3
    assert spec.max_tokens_in == 24_000


@pytest.mark.parametrize(
    "overrides",
    [{"samples": 0}, {"max_tokens_in": 0}, {"unit": "session"}, {"name": ""}, {"model": ""}],
)
def test_monitor_spec_rejects_bad_values(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "name": "basic",
        "unit": "trajectory",
        "prompt_hash": "p",
        "model": "m",
    }
    fields.update(overrides)
    with pytest.raises(SchemaError):
        MonitorSpec(**fields)


def test_score_accepts_the_normalized_range() -> None:
    score = Score("t-1", None, "basic", raw=10.0, normalized=1.0, reason="r", cost_usd=0.0)
    assert score.cached is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"normalized": 1.01},
        {"normalized": -0.1},
        {"normalized": float("nan")},
        {"cost_usd": -1.0},
        {"raw": float("inf")},
        {"step_index": -1},
    ],
)
def test_score_rejects_bad_values(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "trajectory_id": "t-1",
        "step_index": None,
        "monitor": "basic",
        "raw": 3.0,
        "normalized": 0.2,
        "reason": "r",
        "cost_usd": 0.0,
    }
    fields.update(overrides)
    with pytest.raises(SchemaError):
        Score(**fields)
