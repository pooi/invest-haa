from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from .constants import (
    AMOUNT_STEP,
    CASH_BUFFER_RATE,
    MIN_TOLERANCE_USD,
    QUANTITY_STEP,
    TOLERANCE_RATE,
    UNIVERSE,
)
from .domain import Holding, PlannedTrade, PortfolioPlan, PriceQuote


def floor_quantity(value: Decimal) -> Decimal:
    return value.quantize(QUANTITY_STEP, rounding=ROUND_DOWN)


def floor_amount(value: Decimal) -> Decimal:
    return value.quantize(AMOUNT_STEP, rounding=ROUND_DOWN)


def build_portfolio_plan(
    *,
    target_weights: dict[str, Decimal],
    holdings: list[Holding],
    quotes: dict[str, PriceQuote],
    buying_power: Decimal,
    capital_ceiling: Decimal,
    us_commission_rate_percent: Decimal,
    sellable_quantities: dict[str, Decimal],
) -> PortfolioPlan:
    if buying_power < 0 or capital_ceiling <= 0:
        raise ValueError("buying power cannot be negative and capital ceiling must be positive")
    if sum(target_weights.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("target weights must total exactly 1")

    haa_holdings = [holding for holding in holdings if holding.symbol in UNIVERSE and holding.currency == "USD"]
    current_values: dict[str, Decimal] = {}
    for holding in haa_holdings:
        quote = quotes.get(holding.symbol)
        if quote is None or quote.currency != "USD" or quote.last_price <= 0:
            raise ValueError(f"missing valid USD quote for holding {holding.symbol}")
        current_values[holding.symbol] = holding.quantity * quote.last_price

    holdings_value = sum(current_values.values(), Decimal("0"))
    gross_capital = min(capital_ceiling, holdings_value + buying_power)
    commission_rate = us_commission_rate_percent / Decimal("100")
    # Reserve enough cash for a worst-case full portfolio rotation (sell + buy).
    # The actual estimate is recalculated from the resulting trade plan below.
    maximum_commission = gross_capital * Decimal("2") * commission_rate
    cash_buffer = max(maximum_commission, gross_capital * CASH_BUFFER_RATE)
    investable = max(Decimal("0"), gross_capital - cash_buffer)
    tolerance = max(MIN_TOLERANCE_USD, investable * TOLERANCE_RATE)

    sell_candidates: list[PlannedTrade] = []
    buy_candidates: list[PlannedTrade] = []
    symbols = sorted(set(current_values) | set(target_weights))
    for symbol in symbols:
        current = current_values.get(symbol, Decimal("0"))
        target = investable * target_weights.get(symbol, Decimal("0"))
        delta = target - current
        if delta < -tolerance:
            quote = quotes[symbol]
            requested = floor_quantity((-delta) / quote.last_price)
            sellable = floor_quantity(sellable_quantities.get(symbol, Decimal("0")))
            quantity = min(requested, sellable)
            if quantity > 0:
                sell_candidates.append(PlannedTrade(0, symbol, "SELL", current, target, delta, quantity=quantity))
        elif delta > tolerance:
            amount = floor_amount(delta)
            if amount > 0:
                buy_candidates.append(PlannedTrade(0, symbol, "BUY", current, target, delta, order_amount=amount))

    planned_sell_proceeds = sum(
        ((trade.quantity or Decimal("0")) * quotes[trade.symbol].last_price for trade in sell_candidates),
        Decimal("0"),
    )
    planned_buy_amount = sum(
        (trade.order_amount or Decimal("0") for trade in buy_candidates),
        Decimal("0"),
    )
    planned_turnover = planned_sell_proceeds + planned_buy_amount
    estimated_commission = planned_turnover * commission_rate
    available_for_buys = buying_power + planned_sell_proceeds
    required_for_buys = planned_buy_amount + estimated_commission
    if required_for_buys > available_for_buys:
        shortfall = required_for_buys - available_for_buys
        raise ValueError(
            "portfolio plan is not executable: "
            f"buy orders and estimated commission exceed available USD by {shortfall:.2f}; "
            "check sellable quantities or reduce the capital ceiling"
        )

    ordered: list[PlannedTrade] = []
    for sequence, trade in enumerate((*sell_candidates, *buy_candidates), 1):
        ordered.append(
            PlannedTrade(
                sequence,
                trade.symbol,
                trade.side,
                trade.current_value,
                trade.target_value,
                trade.delta_value,
                trade.quantity,
                trade.order_amount,
            )
        )

    return PortfolioPlan(
        gross_capital=gross_capital,
        cash_buffer=cash_buffer,
        investable_capital=investable,
        tolerance=tolerance,
        estimated_commission=estimated_commission,
        holdings=tuple(holdings),
        quotes=quotes,
        buying_power=buying_power,
        trades=tuple(ordered),
    )
