import json

from hypothesis import given
from hypothesis import strategies as st

from monitor_shift.schema import Step, Trajectory, compute_content_hash

text = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
maybe_text = st.none() | st.text(max_size=40)


@st.composite
def trajectories(draw: st.DrawFn) -> Trajectory:
    n = draw(st.integers(min_value=1, max_value=6))
    steps = tuple(
        Step(
            index=i,
            action=draw(text),
            observation=draw(maybe_text),
            message=draw(maybe_text),
            timestamp=draw(maybe_text),
        )
        for i in range(n)
    )
    return Trajectory(
        id=draw(text),
        source=draw(st.sampled_from(["controlarena", "swe_agent", "aivillage", "fixture"])),
        rung=draw(st.sampled_from(["L0", "L1", "L2", "L3"])),
        task=draw(text),
        steps=steps,
        label=draw(st.sampled_from(["honest", "attack", "unknown"])),
        meta=draw(st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=3)),
    )


@given(trajectories())
def test_round_trip_through_json_preserves_everything(traj: Trajectory) -> None:
    restored = Trajectory.from_dict(json.loads(json.dumps(traj.to_dict())))
    assert restored == traj
    assert restored.content_hash == traj.content_hash


@given(trajectories())
def test_hash_is_a_pure_function_of_task_and_steps(traj: Trajectory) -> None:
    assert traj.content_hash == compute_content_hash(traj.task, traj.steps)
    assert compute_content_hash(traj.task, list(traj.steps)) == traj.content_hash


@given(trajectories(), text)
def test_any_task_edit_changes_the_hash(traj: Trajectory, suffix: str) -> None:
    assert compute_content_hash(traj.task + suffix, traj.steps) != traj.content_hash


@given(st.text(max_size=20), st.text(max_size=20))
def test_field_boundaries_cannot_collide(a: str, b: str) -> None:
    """Moving text between action and observation must change the hash."""
    left = (Step(0, "x" + a + b, "", None, None),)
    right = (Step(0, "x" + a, b, None, None),)
    if b:
        assert compute_content_hash("t", left) != compute_content_hash("t", right)
