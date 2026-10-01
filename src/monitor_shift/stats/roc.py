"""ROC statistics. Pure maths: no I/O.

`auroc` is the Mann-Whitney U statistic (scipy) scaled to [0, 1]; `partial_auroc` wraps
scikit-learn. Positives are attacks; ties count half. The bootstrap resamples within each
class (a stratified bootstrap), assuming runs are independent. M3 adds clustering by task
for L0, where tasks repeat.
"""

# numpy 2.5's stubs leave an Unknown in most array-function overloads; see docs/decisions.md.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import scipy.stats as sps
from sklearn.metrics import roc_auc_score  # pyright: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class Estimate:
    value: float
    lo: float
    hi: float
    method: str


def _check(negatives: Sequence[float], positives: Sequence[float]) -> None:
    if not negatives or not positives:
        raise ValueError("scores need at least one negative and one positive")


def auroc(negatives: Sequence[float], positives: Sequence[float]) -> float:
    """P(attack scores above honest), ties counted half: Mann-Whitney U / (n_pos * n_neg)."""
    _check(negatives, positives)
    # scipy is untyped here; the U statistic is a float.
    result = sps.mannwhitneyu(positives, negatives, method="asymptotic")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    u = cast(float, result.statistic)  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
    return float(u) / (len(positives) * len(negatives))


def partial_auroc(negatives: Sequence[float], positives: Sequence[float], max_fpr: float) -> float:
    """McClish-standardised partial AUROC over FPR in [0, max_fpr] (0.5 = chance, 1 = perfect)."""
    _check(negatives, positives)
    y = np.r_[np.zeros(len(negatives)), np.ones(len(positives))]
    s = np.r_[np.asarray(negatives, float), np.asarray(positives, float)]
    return float(cast(float, roc_auc_score(y, s, max_fpr=max_fpr)))


def bootstrap_auroc(
    negatives: Sequence[float],
    positives: Sequence[float],
    *,
    n_boot: int = 2_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> Estimate:
    """AUROC with a percentile interval from a stratified bootstrap."""
    _check(negatives, positives)
    rng = np.random.default_rng(seed)
    neg, pos = np.asarray(negatives, float), np.asarray(positives, float)
    # wins[i, j] = 1 if attack i outscores honest j, 0.5 on a tie: AUROC is its mean, and a
    # bootstrap draw is the mean over resampled rows and columns.
    wins = (pos[:, None] > neg[None, :]) + 0.5 * (pos[:, None] == neg[None, :])
    draws = np.empty(n_boot)
    for b in range(n_boot):
        rows = rng.integers(0, pos.size, pos.size)
        cols = rng.integers(0, neg.size, neg.size)
        draws[b] = wins[np.ix_(rows, cols)].mean()
    lo, hi = np.quantile(draws, [alpha / 2, 1 - alpha / 2])
    return Estimate(auroc(negatives, positives), float(lo), float(hi), "stratified bootstrap")
