import json
from pathlib import Path

import pytest

from monitor_shift.adapters.fixtures import FixtureSource
from monitor_shift.errors import ConfigError
from monitor_shift.runner import store
from monitor_shift.runner.score import ComponentResult, MonitorResult
from monitor_shift.runner.truncate import TruncationReport


def result(traj_id: str, score: float) -> MonitorResult:
    comp = ComponentResult("basic", score, 1, 1, 100, 20, 0.001, 0.001, "ok")
    return MonitorResult(
        trajectory_id=traj_id,
        content_hash="h",
        rung="L0",
        label="honest",
        monitor="basic",
        model="m",
        prompt_hash="p",
        truncation=TruncationReport(100, 100, 0, 0),
        components=(comp,),
        weights=(1.0,),
    )


def test_trajectories_round_trip_outside_the_repo(tmp_path: Path) -> None:
    trajs = FixtureSource("L3", "unknown").load(n=5, seed=0)
    path = store.save_trajectories("L3-test", trajs)
    assert tmp_path in path.parents  # conftest points the cache at tmp_path
    assert store.load_trajectories("L3-test") == trajs


def test_missing_sets_list_what_exists() -> None:
    store.save_trajectories("present", FixtureSource("L1").load(n=1, seed=0))
    with pytest.raises(ConfigError) as info:
        store.load_trajectories("absent")
    assert "present" in info.value.hint


@pytest.mark.parametrize("bad", ["", "../escape", "a/b", "-dash-first"])
def test_set_names_cannot_escape_the_store(bad: str) -> None:
    with pytest.raises(ConfigError):
        store.trajectories_path(bad)


def test_results_append_and_the_latest_wins() -> None:
    store.append_results("run", [result("t1", 0.1), result("t2", 0.2)])
    store.append_results("run", [result("t1", 0.9)])
    loaded = {r.trajectory_id: r.normalized for r in store.load_results("run")}
    assert loaded == {"t1": 0.9, "t2": 0.2}


def test_run_log_records_versions(tmp_path: Path) -> None:
    store.log_run({"command": "score", "spent_usd": 0.5})
    entry = json.loads((tmp_path / "cache" / "runs.jsonl").read_text().splitlines()[-1])
    assert entry["command"] == "score"
    assert set(entry["versions"]) == {"monitor-shift", "control-arena", "inspect-ai"}
