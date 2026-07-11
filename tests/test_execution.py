from datetime import UTC, datetime, timedelta
from decimal import Decimal

from invest_haa.db import RebalanceRunModel, Repository
from invest_haa.domain import BrokerOrder, MarketCalendar, MarketDay, PlannedTrade, PortfolioPlan, PriceQuote
from invest_haa.execution import LiveExecutor


class LiveClient:
    def __init__(self):
        self.submitted = []
        self.buying_power_calls = 0

    def us_market_calendar(self, target_date):
        now = datetime.now(UTC)
        today = MarketDay(target_date, now - timedelta(hours=1), now + timedelta(hours=1))
        return MarketCalendar(today, today, today)

    def create_market_order(self, **kwargs):
        self.submitted.append(kwargs)
        return f"order-{len(self.submitted)}"

    def open_order_symbols(self):
        return set()

    def order(self, order_id):
        request = self.submitted[int(order_id.split("-")[-1]) - 1]
        quantity = request.get("quantity") or Decimal("1")
        return BrokerOrder(
            order_id,
            request["symbol"],
            request["side"],
            "FILLED",
            quantity,
            request.get("order_amount"),
            quantity,
            Decimal("100"),
            request.get("order_amount") or quantity * Decimal("100"),
            Decimal("0.1"),
            datetime.now(UTC),
        )

    def buying_power_usd(self):
        self.buying_power_calls += 1
        return Decimal("1000")


def test_live_executor_sells_before_buying_and_persists_orders(settings):
    live_settings = settings.model_copy(
        update={
            "live_trading": True,
            "live_trading_account_seq": settings.toss_account_seq,
            "max_single_order_usd": Decimal("1000"),
        }
    )
    repository = Repository(settings.database_url)
    repository.create_schema()
    with repository.session() as session:
        session.add(
            RebalanceRunModel(
                id="run-1",
                signal_month="2026-06",
                signal_date=datetime(2026, 6, 30).date(),
                risk_on=True,
                best_defensive="IEF",
                gross_capital="1000",
                cash_buffer="5",
                investable_capital="995",
                tolerance="5",
                buying_power="500",
            )
        )
    now = datetime.now(UTC)
    plan = PortfolioPlan(
        gross_capital=Decimal("1000"),
        cash_buffer=Decimal("5"),
        investable_capital=Decimal("995"),
        tolerance=Decimal("5"),
        estimated_commission=Decimal("1"),
        holdings=(),
        quotes={
            "SPY": PriceQuote("SPY", now, Decimal("100"), "USD"),
            "IEF": PriceQuote("IEF", now, Decimal("100"), "USD"),
        },
        buying_power=Decimal("500"),
        trades=(
            PlannedTrade(1, "SPY", "SELL", Decimal("500"), Decimal("0"), Decimal("-500"), quantity=Decimal("5")),
            PlannedTrade(2, "IEF", "BUY", Decimal("0"), Decimal("500"), Decimal("500"), order_amount=Decimal("500")),
        ),
    )
    client = LiveClient()
    orders = LiveExecutor(live_settings, client, repository, sleep=lambda _: None).execute(
        "run-1", "2026-06", plan
    )

    assert [item["side"] for item in client.submitted] == ["SELL", "BUY"]
    assert client.buying_power_calls == 2
    assert [item.status for item in orders] == ["FILLED", "FILLED"]
    assert [item.status for item in repository.live_orders("run-1")] == ["FILLED", "FILLED"]
    assert repository.get_run("run-1").status == "COMPLETED"  # type: ignore[union-attr]
