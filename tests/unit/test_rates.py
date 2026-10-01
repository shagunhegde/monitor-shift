import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from monitor_shift.stats.rates import wilson


def wilson_closed_form(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (4, 300, 0.0052, 0.0338)],
)
def test_known_wilson_intervals(k: int, n: int, lo: float, hi: float) -> None:
    rate = wilson(k, n)
    assert rate.lo == pytest.approx(lo, abs=1e-4)
    assert rate.hi == pytest.approx(hi, abs=1e-4)


@given(st.integers(1, 5000).flatmap(lambda n: st.tuples(st.integers(0, n), st.just(n))))
def test_matches_the_closed_form(kn: tuple[int, int]) -> None:
    k, n = kn
    rate = wilson(k, n)
    lo, hi = wilson_closed_form(k, n)
    assert rate.k == k
    assert rate.n == n
    assert rate.rate == k / n
    assert rate.lo == pytest.approx(max(lo, 0.0), abs=1e-9)
    assert rate.hi == pytest.approx(min(hi, 1.0), abs=1e-9)
    assert 0.0 <= rate.lo <= rate.rate <= rate.hi <= 1.0
    assert rate.method == "wilson"


@pytest.mark.parametrize(("k", "n"), [(0, 0), (-1, 5), (6, 5)])
def test_invalid_counts_are_rejected(k: int, n: int) -> None:
    with pytest.raises(ValueError, match="count"):
        wilson(k, n)


def test_alpha_widens_the_interval() -> None:
    narrow = wilson(10, 200, alpha=0.2)
    wide = wilson(10, 200, alpha=0.01)
    assert wide.lo < narrow.lo < narrow.hi < wide.hi
