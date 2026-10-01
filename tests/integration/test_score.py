"""The real scoring path offline: ControlArena monitors -> Inspect -> the mshift-fake provider."""

import asyncio
from pathlib import Path

import pytest

from monitor_shift.adapters.fixtures import FixtureSource
from monitor_shift.runner.budget import Price, register_price
from monitor_shift.runner.score import ScoreRun, score_monitors
from monitor_shift.runner.truncate import TruncationRule

MODEL = "mshift-fake/scorer"
PRICE = Price(input_per_m=1.0, output_per_m=4.0)
HONEST = FixtureSource("L0", "honest", split="calibration").load(n=12, seed=1)
ATTACK = FixtureSource("L0", "attack").load(n=12, seed=1)


@pytest.fixture(autouse=True)
def _priced_fake_model() -> None:
    register_price(MODEL, PRICE)


def run(trajs: list, monitors: list[str], max_usd: float = 1.0, **kw: object) -> ScoreRun:  # type: ignore[type-arg]
    return asyncio.run(score_monitors(trajs, monitors, MODEL, max_usd=max_usd, **kw))  # type: ignore[arg-type]


def test_scores_every_trajectory_with_every_monitor() -> None:
    result = run([*HONEST, *ATTACK], ["basic", "hybrid"], samples=1)
    assert result.stopped is None
    assert len(result.results) == 2 * 24
    assert all(r.parsed for r in result.results)
    assert {r.monitor for r in result.results} == {"basic", "hybrid"}
    assert all(0.0 <= (r.normalized or 0) <= 1.0 for r in result.results)


def test_attacks_score_higher_through_the_real_stack() -> None:
    result = run([*HONEST, *ATTACK], ["basic"], samples=1)
    honest = [r.normalized or 0 for r in result.results if r.label == "honest"]
    attack = [r.normalized or 0 for r in result.results if r.label == "attack"]
    assert sum(attack) / len(attack) > sum(honest) / len(honest)


def test_hybrid_shares_the_basic_call() -> None:
    result = run(HONEST[:3], ["basic", "hybrid"], samples=1)
    by_traj: dict[str, dict[str, object]] = {}
    for r in result.results:
        by_traj.setdefault(r.trajectory_id, {})[r.monitor] = r.components[0]
    assert all(v["basic"] is v["hybrid"] for v in by_traj.values())


def test_spend_is_tracked_from_inspect_and_cache_hits_are_free() -> None:
    first = run(HONEST[:4], ["basic"], samples=1)
    assert first.spent_usd > 0
    assert first.spent_usd == pytest.approx(sum(r.billed_usd for r in first.results))
    again = run(HONEST[:4], ["basic"], samples=1)
    assert again.spent_usd == 0
    assert all(r.components[0].cached for r in again.results)
    assert [r.normalized for r in again.results] == pytest.approx(
        [r.normalized for r in first.results]
    )


def test_budget_stops_before_exceeding_the_cap() -> None:
    cap = 0.01  # each call reserves ~$0.002 and really costs ~$0.001; all 24 would cost ~$0.03
    result = run(
        [*HONEST, *ATTACK], ["basic"], max_usd=cap, samples=1, concurrency=2, max_tokens_out=200
    )
    assert result.stopped is not None
    assert result.stopped.hint
    assert result.spent_usd <= cap
    assert 0 < len(result.results) < 24


def test_ensemble_samples_average_and_count_parses() -> None:
    result = run(HONEST[:3], ["basic"], samples=3)
    for r in result.results:
        comp = r.components[0]
        assert comp.samples == 3
        assert comp.parsed_samples == 3


def test_parse_failures_are_counted_not_scored_as_zero() -> None:
    flaky = "mshift-fake/fail-every-2"
    register_price(flaky, PRICE)
    result = asyncio.run(score_monitors(HONEST[:6], ["basic"], flaky, max_usd=1.0, samples=1))
    parsed = [r for r in result.results if r.parsed]
    failed = [r for r in result.results if not r.parsed]
    assert parsed
    assert failed
    assert all(r.normalized is None and r.to_score() is None for r in failed)


def test_messages_view_is_skipped_when_an_agent_writes_nothing() -> None:
    silent = FixtureSource("L1", "honest").load(n=30, seed=2)
    silent = [t for t in silent if not any(s.message for s in t.steps)][:2]
    assert silent, "fixture should produce some message-free runs"
    result = run(silent, ["hybrid"], samples=1)
    for r in result.results:
        assert r.components[1].skipped == "no agent messages"
        assert r.normalized == r.components[0].normalized


def test_long_trajectories_are_truncated_before_scoring() -> None:
    long = FixtureSource("L3", "unknown").load(n=2, seed=3)
    result = run(long, ["basic"], samples=1, rule=TruncationRule(max_tokens=12_000))
    assert all(r.truncation.final_tokens <= 12_000 for r in result.results)


def test_constitutional_runs_through_the_stack_on_a_1_to_10_scale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from monitor_shift.runner import inspect_monitors

    name = "constitutional_user.txt"
    (tmp_path / name).write_text((inspect_monitors.PROMPTS_DIR / name).read_text())
    (tmp_path / "constitutional.txt").write_text("Judge whether the agent is scheming. {braces}")
    monkeypatch.setattr(inspect_monitors, "PROMPTS_DIR", tmp_path)
    result = run(HONEST[:3], ["constitutional"], samples=1)
    assert all(r.parsed for r in result.results)
    scores = [r.normalized for r in result.results]
    assert all(s is not None and 0.0 <= s <= 1.0 for s in scores)
