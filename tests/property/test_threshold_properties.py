import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from monitor_shift.calibrate.thresholds import fit_threshold, flag

# Few distinct values, so ties are the norm, as with integer monitor scales.
tied_scores = st.lists(st.sampled_from([i / 9 for i in range(10)]), min_size=1, max_size=400)
free_scores = st.lists(st.floats(0, 1, allow_nan=False), min_size=1, max_size=400)
scores_st = tied_scores | free_scores
targets = st.floats(0.001, 0.5)


@given(scores_st, targets)
def test_achieved_rate_never_exceeds_target(scores: list[float], target: float) -> None:
    t = fit_threshold(scores, target)
    assert t.achieved_fpr <= target
    assert t.n_flagged == int(flag(scores, t.value).sum())
    assert t.achieved_fpr == t.n_flagged / len(scores)


@given(scores_st, targets)
def test_threshold_is_the_lowest_that_meets_the_target(scores: list[float], target: float) -> None:
    t = fit_threshold(scores, target)
    lower = [s for s in set(scores) if s < t.value]
    if lower:
        assert flag(scores, max(lower)).mean() > target


@given(scores_st, targets, targets)
def test_threshold_moves_the_right_way(scores: list[float], a: float, b: float) -> None:
    low, high = sorted((a, b))
    assert fit_threshold(scores, low).value >= fit_threshold(scores, high).value
    assert fit_threshold(scores, low).n_flagged <= fit_threshold(scores, high).n_flagged


@given(scores_st, targets)
def test_threshold_is_an_observed_score(scores: list[float], target: float) -> None:
    assert fit_threshold(scores, target).value in np.asarray(scores)
