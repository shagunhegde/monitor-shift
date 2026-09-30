"""Rates with intervals. Pure maths: no I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import statsmodels.stats.proportion as smp


@dataclass(frozen=True)
class Rate:
    k: int
    n: int
    rate: float
    lo: float
    hi: float
    method: str


def wilson(k: int, n: int, alpha: float = 0.05) -> Rate:
    """k of n with a Wilson score interval (statsmodels), clipped to contain the point estimate."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"count k={k} of n={n} is not a valid proportion")
    # statsmodels is untyped; the cast pins down what proportion_confint returns for scalars.
    interval = smp.proportion_confint(k, n, alpha=alpha, method="wilson")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    lo, hi = cast(tuple[float, float], interval)
    rate = k / n
    return Rate(
        k=k, n=n, rate=rate, lo=min(max(lo, 0.0), rate), hi=max(min(hi, 1.0), rate), method="wilson"
    )
