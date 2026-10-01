import json

import pytest

from monitor_shift.errors import BudgetExceededError, ConfigError
from monitor_shift.runner.budget import (
    Budget,
    Price,
    ensure_price,
    fetch_openrouter_price,
    price_for,
    register_price,
    usd,
)

LISTING = json.dumps(
    {
        "data": [
            {
                "id": "openai/gpt-6-luna",
                "pricing": {"prompt": "0.0000001", "completion": "0.0000005"},
            },
            {"id": "qwen/qwen3.8-flash", "pricing": {"prompt": "0.00000015", "completion": "0"}},
        ]
    }
).encode()


def fetch(url: str) -> bytes:
    assert url.startswith("https://openrouter.ai/")
    return LISTING


def test_price_cost_is_per_million_tokens() -> None:
    assert Price(1.0, 4.0).cost(1_000_000, 500_000) == pytest.approx(3.0)


def test_openrouter_prices_convert_from_per_token() -> None:
    price = fetch_openrouter_price("openrouter/openai/gpt-6-luna", fetch)
    assert price == Price(pytest.approx(0.1), pytest.approx(0.5))  # type: ignore[arg-type]


def test_unknown_openrouter_model_says_where_to_look() -> None:
    with pytest.raises(ConfigError) as info:
        fetch_openrouter_price("openrouter/acme/nope", fetch)
    assert "openrouter.ai/models" in info.value.hint


def test_ensure_price_registers_openrouter_models_once() -> None:
    calls: list[str] = []

    def counting_fetch(url: str) -> bytes:
        calls.append(url)
        return LISTING

    model = "openrouter/qwen/qwen3.8-flash"
    assert ensure_price(model, counting_fetch).input_per_m == pytest.approx(0.15)
    assert ensure_price(model, counting_fetch).input_per_m == pytest.approx(0.15)
    assert len(calls) == 1


def test_unpriced_models_refuse_to_run() -> None:
    with pytest.raises(ConfigError) as info:
        price_for("mshift-fake/never-priced")
    assert "register_price" in info.value.hint


def test_registered_prices_round_trip() -> None:
    register_price("mshift-fake/priced", Price(2.0, 8.0))
    assert price_for("mshift-fake/priced") == Price(2.0, 8.0)


def test_reservations_stop_before_the_cap() -> None:
    with Budget(1.0) as budget:
        budget.reserve(0.6)
        with pytest.raises(BudgetExceededError) as info:
            budget.reserve(0.5)
        assert "--max-usd" in info.value.hint or "rerun" in info.value.hint
        budget.release(0.6)
        budget.reserve(0.9)
        assert budget.reserved == pytest.approx(0.9)
        assert budget.spent == 0.0


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_cap_must_be_positive(bad: float) -> None:
    with pytest.raises(ConfigError):
        Budget(bad)


def test_money_formatting_keeps_small_amounts_readable() -> None:
    assert usd(150) == "$150.00"
    assert usd(0.0123456) == "$0.0123"
