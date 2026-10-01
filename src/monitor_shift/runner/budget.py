"""Spend caps for live commands.

Inspect already prices every model call and records it against any open `cost_limit`, but it
checks after the call. To stop *before* exceeding `--max-usd`, each call first reserves a
worst-case estimate (input estimate x 1.3, plus the full output allowance), and the run stops
scheduling when a reservation won't fit. Actual spend is read back from Inspect's cost limits,
which skip cache hits, so re-running a command pays only for calls it hasn't made before.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, cast

from inspect_ai.model import ModelCost, ModelInfo, get_model_info, set_model_cost, set_model_info
from inspect_ai.util import cost_limit

from monitor_shift.errors import BudgetExceededError, ConfigError

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
INPUT_SAFETY = 1.3  # characters / 4 under-counts code and non-English text


@dataclass(frozen=True)
class Price:
    input_per_m: float  # USD per million input tokens
    output_per_m: float

    def cost(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.input_per_m + output_tokens * self.output_per_m) / 1e6


def price_for(model: str) -> Price:
    info = get_model_info(model)
    if info is None or info.cost is None:
        raise ConfigError(
            f"No price is registered for {model}, so --max-usd can't be enforced.",
            hint="Use an openrouter/... model (prices are fetched automatically), or call "
            "monitor_shift.runner.budget.register_price() first.",
        )
    return Price(info.cost.input, info.cost.output)


def register_price(model: str, price: Price) -> None:
    cost = ModelCost(
        input=price.input_per_m,
        output=price.output_per_m,
        input_cache_write=price.input_per_m,
        input_cache_read=price.input_per_m,
    )
    if get_model_info(model) is None:
        set_model_info(model, ModelInfo(cost=cost))
    else:
        set_model_cost(model, cost)


def _http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        body: bytes = response.read()
    return body


def fetch_openrouter_price(model: str, fetch: Callable[[str], bytes] = _http_get) -> Price:
    """Live price for an `openrouter/<vendor>/<model>` model, from OpenRouter's public API."""
    model_id = model.removeprefix("openrouter/")
    listing = cast(dict[str, Any], json.loads(fetch(OPENROUTER_MODELS_URL)))
    for entry in cast(list[dict[str, Any]], listing.get("data", [])):
        if entry.get("id") == model_id:
            pricing = cast(dict[str, Any], entry.get("pricing") or {})
            return Price(
                input_per_m=float(pricing.get("prompt", 0)) * 1e6,
                output_per_m=float(pricing.get("completion", 0)) * 1e6,
            )
    raise ConfigError(
        f"OpenRouter doesn't list a model called {model_id!r}.",
        hint="Check the id at https://openrouter.ai/models and pass it as openrouter/<id>.",
    )


FAKE_PRICE = Price(1.0, 4.0)  # nominal, so offline runs exercise the budget logic


def ensure_price(model: str, fetch: Callable[[str], bytes] = _http_get) -> Price:
    """Register a live OpenRouter price (or the fake model's nominal one) if needed."""
    info = get_model_info(model)
    if info is None or info.cost is None:
        if model.startswith("openrouter/"):
            register_price(model, fetch_openrouter_price(model, fetch))
        elif model.startswith("mshift-fake/"):
            register_price(model, FAKE_PRICE)
    return price_for(model)


def usd(amount: float) -> str:
    return f"${amount:,.2f}" if amount >= 1 else f"${amount:.4f}"


class Budget:
    """A spend cap: reserve before each call, read actual spend from Inspect."""

    def __init__(self, max_usd: float) -> None:
        if not max_usd > 0:
            raise ConfigError(
                f"--max-usd must be positive, got {max_usd}.", hint="Pass e.g. --max-usd 5"
            )
        self.max_usd = max_usd
        self._reserved = 0.0
        self._limit = cost_limit(max_usd)  # Inspect's own check stays on as a backstop

    def __enter__(self) -> Budget:
        self._limit.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._limit.__exit__(exc_type, exc, tb)

    @property
    def spent(self) -> float:
        return self._limit.usage

    @property
    def reserved(self) -> float:
        return self._reserved

    def reserve(self, cost: float) -> None:
        if self.spent + self._reserved + cost > self.max_usd:
            raise BudgetExceededError(
                f"Stopped before exceeding --max-usd {usd(self.max_usd)}: spent "
                f"{usd(self.spent)}, {usd(self._reserved)} in flight, and the next call could "
                f"cost up to {usd(cost)}.",
                hint="Raise --max-usd, or rerun the same command: finished calls are cached, "
                "so it resumes where it stopped.",
            )
        self._reserved += cost

    def release(self, cost: float) -> None:
        self._reserved = max(0.0, self._reserved - cost)


@contextmanager
def track_cost() -> Generator[Callable[[], float]]:
    """Measure what the calls inside this block actually cost (cache hits count as zero)."""
    with cost_limit(None) as limit:
        yield lambda: limit.usage
