from datetime import UTC, datetime
from decimal import Decimal

from invest_haa.domain import Holding, PriceQuote
from invest_haa.portfolio import build_portfolio_plan, floor_quantity


def quote(symbol: str, price: str) -> PriceQuote:
    return PriceQuote(symbol, datetime.now(UTC), Decimal(price), "USD")


def test_cap_buffer_tolerance_and_sell_before_buy():
    holdings = [Holding("SPY", "USD", Decimal("10"), Decimal("100"), Decimal("1000"))]
    quotes = {"SPY": quote("SPY", "100"), "IEF": quote("IEF", "50")}
    plan = build_portfolio_plan(
        target_weights={"IEF": Decimal("1")},
        holdings=holdings,
        quotes=quotes,
        buying_power=Decimal("2000"),
        capital_ceiling=Decimal("2500"),
        us_commission_rate_percent=Decimal("0.1"),
        sellable_quantities={"SPY": Decimal("9.1234569")},
    )
    assert plan.gross_capital == Decimal("2500")
    assert plan.cash_buffer == Decimal("12.500")
    assert plan.investable_capital == Decimal("2487.500")
    assert plan.tolerance == Decimal("6.2187500")
    assert plan.estimated_commission == Decimal("3.399845600")
    assert [trade.side for trade in plan.trades] == ["SELL", "BUY"]
    assert plan.trades[0].quantity == Decimal("9.123456")
    assert plan.trades[1].order_amount == Decimal("2487.50")


def test_mixed_account_ignores_non_haa_holdings():
    holdings = [
        Holding("AAPL", "USD", Decimal("100"), Decimal("200"), Decimal("20000")),
        Holding("IEF", "USD", Decimal("1"), Decimal("100"), Decimal("100")),
    ]
    plan = build_portfolio_plan(
        target_weights={"IEF": Decimal("1")},
        holdings=holdings,
        quotes={"IEF": quote("IEF", "100")},
        buying_power=Decimal("0"),
        capital_ceiling=Decimal("10000"),
        us_commission_rate_percent=Decimal("0.1"),
        sellable_quantities={"IEF": Decimal("1")},
    )
    assert plan.gross_capital == Decimal("100")
    assert not plan.trades


def test_quantity_rounds_down_to_six_places():
    assert floor_quantity(Decimal("1.2345679")) == Decimal("1.234567")


def test_rejects_buy_plan_when_limited_sellable_quantity_causes_cash_shortfall():
    holdings = [Holding("SPY", "USD", Decimal("10"), Decimal("100"), Decimal("1000"))]
    try:
        build_portfolio_plan(
            target_weights={"IEF": Decimal("1")},
            holdings=holdings,
            quotes={"SPY": quote("SPY", "100"), "IEF": quote("IEF", "50")},
            buying_power=Decimal("1500"),
            capital_ceiling=Decimal("2500"),
            us_commission_rate_percent=Decimal("0.1"),
            sellable_quantities={"SPY": Decimal("0")},
        )
    except ValueError as exc:
        assert "not executable" in str(exc)
    else:
        raise AssertionError("an unaffordable buy plan must be rejected")
