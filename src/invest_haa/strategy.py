from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from .constants import CANARY, DEFENSIVE, LOOKBACKS, OFFENSIVE, SLOT_WEIGHT, TOP_N, UNIVERSE
from .domain import SignalScore, StrategyResult


class InsufficientHistory(ValueError):
    pass


def shift_month(month: str, months: int) -> str:
    year, number = map(int, month.split("-"))
    absolute = year * 12 + number - 1 + months
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def month_end(month: str) -> date:
    year, number = map(int, month.split("-"))
    return date(year, number, monthrange(year, number)[1])


def calculate_strategy(
    monthly_closes: dict[str, dict[str, Decimal]],
    monthly_dates: dict[str, dict[str, date]],
    signal_month: str,
) -> StrategyResult:
    required_months = [shift_month(signal_month, -offset) for offset in range(13)]
    for symbol in UNIVERSE:
        missing = [month for month in required_months if month not in monthly_closes.get(symbol, {})]
        if missing:
            raise InsufficientHistory(f"{symbol}: missing consecutive month ends: {', '.join(missing)}")

    signal_dates = {monthly_dates[symbol][signal_month] for symbol in UNIVERSE}
    if len(signal_dates) != 1:
        raise ValueError(f"symbols do not share one signal date: {sorted(signal_dates)}")
    signal_date = next(iter(signal_dates))

    scores: dict[str, SignalScore] = {}
    for symbol in UNIVERSE:
        current = monthly_closes[symbol][signal_month]
        if current <= 0:
            raise ValueError(f"{symbol}: signal price must be positive")
        returns = {
            lookback: current / monthly_closes[symbol][shift_month(signal_month, -lookback)] - 1
            for lookback in LOOKBACKS
        }
        momentum = sum(returns.values(), Decimal("0")) / Decimal(len(LOOKBACKS))
        scores[symbol] = SignalScore(symbol=symbol, returns=returns, momentum=momentum)

    offensive_ranked = sorted(OFFENSIVE, key=lambda symbol: (-scores[symbol].momentum, symbol))
    for rank, symbol in enumerate(offensive_ranked, 1):
        score = scores[symbol]
        scores[symbol] = SignalScore(symbol, score.returns, score.momentum, rank)

    best_defensive = sorted(DEFENSIVE, key=lambda symbol: (-scores[symbol].momentum, symbol))[0]
    risk_on = scores[CANARY].momentum > 0
    if not risk_on:
        target_weights = {best_defensive: Decimal("1")}
    else:
        target_weights: dict[str, Decimal] = {}
        for symbol in offensive_ranked[:TOP_N]:
            selected = symbol if scores[symbol].momentum > 0 else best_defensive
            target_weights[selected] = target_weights.get(selected, Decimal("0")) + SLOT_WEIGHT

    if sum(target_weights.values(), Decimal("0")) != Decimal("1"):
        raise AssertionError("target weights must total exactly 1")

    return StrategyResult(
        signal_month=signal_month,
        signal_date=signal_date,
        scores=scores,
        target_weights=target_weights,
        risk_on=risk_on,
        best_defensive=best_defensive,
    )
