from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from monitor_shift.runner.truncate import (
    TruncationRule,
    estimate_tokens,
    is_omission_marker,
    truncate,
)
from monitor_shift.schema import Step, Trajectory


def traj(
    steps: Sequence[tuple[str, str | None, str | None]], task: str = "Do the task."
) -> Trajectory:
    return Trajectory(
        id="t",
        source="fixture",
        rung="L3",
        task=task,
        steps=tuple(Step(i, a, o, m, None) for i, (a, o, m) in enumerate(steps)),
        label="unknown",
        meta={"agent": "a"},
    )


def test_small_trajectories_pass_through_untouched() -> None:
    t = traj([("ls", "a.txt", "looking"), ("cat a.txt", "hello", None)])
    out, report = truncate(t, TruncationRule())
    assert out == t
    assert not report.truncated
    assert report.original_tokens == report.final_tokens


def test_long_fields_keep_head_and_tail() -> None:
    long = "HEAD" + "x" * 10_000 + "TAIL"
    rule = TruncationRule(max_observation_chars=2_000)
    out, report = truncate(traj([("cat big.log", long, None)]), rule)
    obs = out.steps[0].observation
    assert obs is not None
    assert obs.startswith("HEAD")
    assert obs.endswith("TAIL")
    assert "characters cut by monitor-shift" in obs
    assert len(obs) < 2_200
    assert report.fields_clipped == 1
    assert report.steps_dropped == 0
    assert report.truncated


def test_over_budget_drops_middle_steps_and_marks_the_gap() -> None:
    steps = [(f"step {i} " + "y" * 1_500, "ok", None) for i in range(200)]
    rule = TruncationRule(max_tokens=12_000)
    out, report = truncate(traj(steps), rule)
    assert report.final_tokens <= rule.max_tokens
    assert report.steps_dropped > 0
    assert out.steps[0].action.startswith("step 0 ")
    assert out.steps[-1].action.startswith("step 199 ")
    markers = [s for s in out.steps if is_omission_marker(s)]
    assert len(markers) == 1
    assert [s.index for s in out.steps] == list(range(len(out.steps)))


def test_truncated_copy_keeps_identity_but_rehashes() -> None:
    steps = [("a" * 9_000, None, None)]
    t = traj(steps)
    out, _ = truncate(t, TruncationRule())
    assert (out.id, out.label, out.rung, dict(out.meta)) == (t.id, t.label, t.rung, dict(t.meta))
    assert out.content_hash != t.content_hash


def test_rule_hash_identifies_the_rule() -> None:
    assert TruncationRule().rule_hash == TruncationRule().rule_hash
    assert TruncationRule().rule_hash != TruncationRule(max_tokens=12_000).rule_hash


@pytest.mark.parametrize("bad", [{"max_tokens": 100}, {"max_observation_chars": 10}])
def test_rules_must_leave_room_to_work(bad: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="too small"):
        TruncationRule(**bad)


def test_estimate_tokens_is_a_ceiling_of_chars_over_four() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd" * 10) == 10


field = st.text(max_size=3_000)


@given(
    st.lists(
        st.tuples(field.filter(str.strip), st.none() | field, st.none() | field),
        min_size=1,
        max_size=60,
    ),
    st.integers(11_000, 30_000),
)
def test_output_always_fits_and_keeps_both_ends(
    steps: list[tuple[str, str | None, str | None]], cap: int
) -> None:
    rule = TruncationRule(max_tokens=cap)
    t = traj(steps)
    out, report = truncate(t, rule)
    assert report.final_tokens <= cap
    assert out.steps[0].action[:20] == t.steps[0].action[:20]
    assert out.steps[-1].action[:20] == t.steps[-1].action[:20]
    assert report.steps_dropped + len(out.steps) - (1 if report.steps_dropped else 0) == len(
        t.steps
    )
