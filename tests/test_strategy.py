from datetime import date
from decimal import Decimal

import pytest

from invest_haa.constants import UNIVERSE
from invest_haa.strategy import InsufficientHistory, calculate_strategy, shift_month


def history(slopes: dict[str, Decimal] | None = None):
    slopes = slopes or {}
    signal_month = "2026-06"
    months = [shift_month(signal_month, -offset) for offset in reversed(range(13))]
    closes = {}
    dates = {}
    for symbol in UNIVERSE:
        slope = slopes.get(symbol, Decimal("1"))
        closes[symbol] = {month: Decimal("100") + slope * index for index, month in enumerate(months)}
        dates[symbol] = {
            month: (date(2026, 6, 30) if month == signal_month else date.fromisoformat(f"{month}-28"))
            for month in months
        }
    return signal_month, closes, dates


def test_risk_off_selects_best_defensive():
    month, closes, dates = history({"TIP": Decimal("-1"), "IEF": Decimal("2"), "BIL": Decimal("0.2")})
    result = calculate_strategy(closes, dates, month)
    assert result.risk_on is False
    assert result.best_defensive == "IEF"
    assert result.target_weights == {"IEF": Decimal("1")}


def test_risk_on_is_deterministic_and_totals_one():
    slopes = {
        "TIP": Decimal("1"),
        "SPY": Decimal("8"),
        "IWM": Decimal("7"),
        "VEA": Decimal("6"),
        "VWO": Decimal("5"),
        "VNQ": Decimal("4"),
        "DBC": Decimal("3"),
        "IEF": Decimal("2"),
        "TLT": Decimal("1"),
    }
    month, closes, dates = history(slopes)
    result = calculate_strategy(closes, dates, month)
    assert result.risk_on is True
    assert result.target_weights == {
        "SPY": Decimal("0.25"),
        "IWM": Decimal("0.25"),
        "VEA": Decimal("0.25"),
        "VWO": Decimal("0.25"),
    }
    assert result.scores["SPY"].rank == 1
    assert sum(result.target_weights.values()) == Decimal("1")


def test_zero_canary_is_risk_off_and_defensive_tie_uses_symbol():
    month, closes, dates = history({"TIP": Decimal("0"), "IEF": Decimal("0"), "BIL": Decimal("0")})
    result = calculate_strategy(closes, dates, month)
    assert result.target_weights == {"BIL": Decimal("1")}


def test_negative_top_slot_is_replaced_by_defensive():
    month, closes, dates = history({symbol: Decimal("-0.2") for symbol in UNIVERSE})
    # Keep the canary positive while every offensive asset is negative.
    tip_months = sorted(closes["TIP"])
    closes["TIP"] = {value: Decimal(100 + index) for index, value in enumerate(tip_months)}
    result = calculate_strategy(closes, dates, month)
    assert result.target_weights == {"BIL": Decimal("1")}


def test_requires_thirteen_consecutive_months():
    month, closes, dates = history()
    del closes["SPY"]["2025-11"]
    with pytest.raises(InsufficientHistory):
        calculate_strategy(closes, dates, month)


def test_requires_common_signal_date():
    month, closes, dates = history()
    dates["SPY"][month] = date(2026, 6, 29)
    with pytest.raises(ValueError, match="signal date"):
        calculate_strategy(closes, dates, month)
