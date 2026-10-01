"""Fixture-specific behaviour on top of the shared adapter contract."""

import pytest

from monitor_shift.adapters.fixtures import FixtureSource
from monitor_shift.errors import ConfigError


def test_fixtures_are_marked_synthetic() -> None:
    for traj in FixtureSource("L3", "unknown").load(n=20, seed=0):
        assert traj.source == "fixture"
        assert traj.id.startswith("fx-")
        assert traj.meta["generator"].startswith("monitor_shift.fixtures/")


@pytest.mark.parametrize(
    ("rung", "label", "split"),
    [("L0", "honest", "calibration"), ("L0", "attack", None), ("L1", "honest", None)],
)
def test_rung_label_and_split_are_carried(rung: str, label: str, split: str | None) -> None:
    for traj in FixtureSource(rung, label, split=split).load(n=10, seed=0):  # type: ignore[arg-type]
        assert traj.rung == rung
        assert traj.label == label
        assert traj.meta.get("split") == split


ATTACK_MARKERS = ("external-mail.example", "paste.example", "no need to mention")


def test_attack_runs_record_their_injected_step() -> None:
    for traj in FixtureSource("L0", "attack").load(n=50, seed=0):
        step = traj.steps[int(traj.meta["attack_step"])]
        seen = f"{step.action} {step.message}"
        assert any(marker in seen for marker in ATTACK_MARKERS)


def test_honest_runs_have_no_injected_step() -> None:
    for traj in FixtureSource("L0", "honest", split="heldout").load(n=50, seed=0):
        assert "attack_step" not in traj.meta
        assert not any("external-mail.example" in step.action for step in traj.steps)


def test_l3_sessions_carry_agent_month_and_timestamps() -> None:
    sessions = FixtureSource("L3", "unknown").load(n=60, seed=0)
    assert {t.meta["agent"] for t in sessions} >= {"agent-a", "agent-b"}
    assert len({t.meta["month"] for t in sessions}) > 1
    assert all(step.timestamp for t in sessions for step in t.steps)


def test_stratify_accepts_known_keys() -> None:
    sessions = FixtureSource("L3", "unknown").load(n=30, seed=0, stratify=["agent", "month"])
    agents = [t.meta["agent"] for t in sessions]
    counts = {a: agents.count(a) for a in set(agents)}
    assert max(counts.values()) - min(counts.values()) <= 1


def test_stratify_rejects_unknown_keys_with_a_hint() -> None:
    with pytest.raises(ConfigError) as info:
        FixtureSource("L3", "unknown").load(n=10, seed=0, stratify=["colour"])
    assert "agent" in info.value.hint


@pytest.mark.parametrize(("rung", "label"), [("L2", "attack"), ("L3", "attack"), ("L9", "honest")])
def test_unsupported_fixture_kinds_are_rejected(rung: str, label: str) -> None:
    with pytest.raises(ConfigError):
        FixtureSource(rung, label)  # type: ignore[arg-type]


def test_negative_counts_are_rejected() -> None:
    with pytest.raises(ConfigError):
        FixtureSource("L1", "honest").load(n=-1, seed=0)


def test_smaller_loads_are_prefixes_of_larger_ones() -> None:
    small = FixtureSource("L2", "unknown").load(n=10, seed=5)
    large = FixtureSource("L2", "unknown").load(n=30, seed=5)
    assert list(small) == list(large[:10])
