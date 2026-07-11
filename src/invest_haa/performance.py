from __future__ import annotations

from decimal import Decimal

from .domain import MonthlyPerformance
from .strategy import shift_month


def calculate_monthly_performance(
    monthly_closes: dict[str, dict[str, Decimal]],
    signal_month: str,
    previous_target_weights: dict[str, Decimal],
) -> MonthlyPerformance:
    if sum(previous_target_weights.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("previous target weights must total exactly 1")

    previous_month = shift_month(signal_month, -1)
    asset_returns: dict[str, Decimal] = {}
    contributions: dict[str, Decimal] = {}
    for symbol, weight in previous_target_weights.items():
        prices = monthly_closes.get(symbol, {})
        if previous_month not in prices or signal_month not in prices:
            raise ValueError(f"{symbol}: missing prices for monthly performance")
        previous_close = prices[previous_month]
        current_close = prices[signal_month]
        if previous_close <= 0 or current_close <= 0:
            raise ValueError(f"{symbol}: performance prices must be positive")
        asset_return = current_close / previous_close - 1
        asset_returns[symbol] = asset_return
        contributions[symbol] = weight * asset_return

    return MonthlyPerformance(
        start_month=previous_month,
        end_month=signal_month,
        total_return=sum(contributions.values(), Decimal("0")),
        asset_returns=asset_returns,
        contributions=contributions,
    )
