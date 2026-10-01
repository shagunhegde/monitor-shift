import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from monitor_shift.stats.roc import auroc, bootstrap_auroc, partial_auroc


def mann_whitney(neg: list[float], pos: list[float]) -> float:
    pairs = list(itertools.product(pos, neg))
    return sum(1.0 if p > n else 0.5 if p == n else 0.0 for p, n in pairs) / len(pairs)


def test_perfect_and_chance_separation() -> None:
    assert auroc([0.1, 0.2], [0.8, 0.9]) == 1.0
    assert auroc([0.5, 0.5], [0.5, 0.5]) == 0.5
    assert auroc([0.8, 0.9], [0.1, 0.2]) == 0.0


scores = st.lists(st.sampled_from([0.0, 0.1, 0.25, 0.5, 0.9, 1.0]), min_size=1, max_size=30)


@given(scores, scores)
def test_matches_the_mann_whitney_statistic_with_ties(neg: list[float], pos: list[float]) -> None:
    assert auroc(neg, pos) == pytest.approx(mann_whitney(neg, pos))


def test_partial_auroc_is_standardised() -> None:
    assert partial_auroc([0.1, 0.2, 0.3], [0.8, 0.9], max_fpr=0.1) == pytest.approx(1.0)
    assert 0.0 <= partial_auroc([0.1, 0.6, 0.3], [0.5, 0.9], max_fpr=0.1) <= 1.0


def test_bootstrap_interval_brackets_the_estimate_and_is_seeded() -> None:
    neg = [0.1, 0.3, 0.2, 0.6, 0.4, 0.35, 0.15, 0.5]
    pos = [0.7, 0.4, 0.9, 0.65, 0.8, 0.55, 0.3, 0.95]
    est = bootstrap_auroc(neg, pos, n_boot=500, seed=3)
    assert est.lo <= est.value <= est.hi
    assert est == bootstrap_auroc(neg, pos, n_boot=500, seed=3)
    assert est.method == "stratified bootstrap"


def test_both_classes_are_required() -> None:
    with pytest.raises(ValueError, match="positive"):
        auroc([0.1], [])
