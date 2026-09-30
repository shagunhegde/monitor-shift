import numpy as np
import pytest

from monitor_shift.calibrate.thresholds import fit_threshold, flag


def test_distinct_scores_hit_the_target_exactly() -> None:
    scores = np.arange(100) / 100
    t = fit_threshold(scores, target_fpr=0.05)
    assert t.n_flagged == 5
    assert t.achieved_fpr == pytest.approx(0.05)
    assert t.value == pytest.approx(0.94)
    assert t.n == 100
    assert t.target_fpr == 0.05


def test_all_tied_scores_flag_nothing() -> None:
    t = fit_threshold([0.5] * 50, target_fpr=0.1)
    assert t.n_flagged == 0
    assert t.achieved_fpr == 0.0
    assert not flag([0.5] * 50, t.value).any()


def test_a_tie_that_straddles_the_target_is_not_flagged() -> None:
    scores = [0.1] * 990 + [0.9] * 20
    t = fit_threshold(scores, target_fpr=0.01)
    assert t.value == pytest.approx(0.9)
    assert t.n_flagged == 0


def test_achieved_rate_stays_under_target_where_a_percentile_would_not() -> None:
    """np.percentile(..., 99) with a strict > flags 2 of 150 (1.33%); we must not."""
    scores = np.arange(150, dtype=float)
    percentile = float(np.percentile(scores, 99))  # pyright: ignore[reportUnknownMemberType]
    assert (scores > percentile).sum() == 2
    t = fit_threshold(scores, target_fpr=0.01)
    assert t.n_flagged == 1
    assert t.achieved_fpr <= 0.01


def test_flag_is_strictly_greater_than() -> None:
    assert flag([0.2, 0.5, 0.7], 0.5).tolist() == [False, False, True]


@pytest.mark.parametrize("target", [0.0, 1.0, -0.1, 1.5, float("nan")])
def test_target_must_be_a_proper_fraction(target: float) -> None:
    with pytest.raises(ValueError, match="target_fpr"):
        fit_threshold([0.1, 0.2], target_fpr=target)


@pytest.mark.parametrize("scores", [[], [0.1, float("nan")], [float("inf")]])
def test_scores_must_be_finite_and_present(scores: list[float]) -> None:
    with pytest.raises(ValueError, match="scores"):
        fit_threshold(scores, target_fpr=0.05)
