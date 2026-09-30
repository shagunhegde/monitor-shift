"""`mshift demo --fake`: fixtures -> fake monitors -> calibration -> ladder table."""

import time

import pytest
from rich.console import Console
from syrupy.assertion import SnapshotAssertion

from monitor_shift.cli.demo import LITE_SIZES, DemoResult, render, run_demo


@pytest.fixture(scope="module")
def full() -> DemoResult:
    return run_demo(seed=7)


def test_full_demo_runs_in_under_a_minute() -> None:
    start = time.perf_counter()
    run_demo(seed=7)
    assert time.perf_counter() - start < 60


def test_demo_uses_the_lite_sizes(full: DemoResult) -> None:
    sizes = {(row.monitor, row.group): row.n for row in full.rows}
    for monitor in full.monitors:
        for group, n in LITE_SIZES.items():
            if group != "L0 calibration":
                assert sizes[(monitor, group)] == n
    assert full.n_calibration == LITE_SIZES["L0 calibration"] == 1000


def test_calibration_never_overshoots(full: DemoResult) -> None:
    for threshold in full.thresholds.values():
        assert threshold.achieved_fpr <= threshold.target_fpr
        assert threshold.n == full.n_calibration


def test_fixture_ladder_shows_rising_flag_rates(full: DemoResult) -> None:
    for monitor in full.monitors:
        rates = [full.rate(monitor, group, 0.01).rate for group in ("L1", "L2", "L3")]
        assert rates == sorted(rates)
        assert rates[0] < rates[-1]


def test_attacks_are_caught_at_the_5_percent_threshold(full: DemoResult) -> None:
    for monitor in full.monitors:
        assert full.rate(monitor, "L0 attack", 0.05).rate > 0.8


def test_rendered_table_is_stable(snapshot: SnapshotAssertion) -> None:
    console = Console(width=120, record=True, color_system=None, force_terminal=False)
    render(run_demo(seed=7, scale=0.1), console)
    assert console.export_text() == snapshot
