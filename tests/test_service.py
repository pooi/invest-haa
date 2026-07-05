from datetime import UTC, datetime
from decimal import Decimal

from invest_haa.constants import UNIVERSE
from invest_haa.db import Repository
from invest_haa.domain import Candle, Holding, PriceQuote
from invest_haa.service import HaaService
from invest_haa.strategy import shift_month


class FakeClient:
    def accounts(self):
        return [{"accountSeq": 1, "accountType": "BROKERAGE"}]

    def stocks(self, symbols):
        return [{"symbol": symbol, "status": "ACTIVE", "currency": "USD", "securityType": "ETF"} for symbol in symbols]

    def holdings(self):
        return [Holding("SPY", "USD", Decimal("10"), Decimal("100"), Decimal("1000"))]

    def prices(self, symbols):
        return {symbol: PriceQuote(symbol, datetime.now(UTC), Decimal("100"), "USD") for symbol in symbols}

    def buying_power_usd(self):
        return Decimal("1000")

    def us_commission_rate(self):
        return Decimal("0.1")

    def sellable_quantity(self, symbol):
        return Decimal("10")


def test_service_creates_one_persisted_plan_and_outbox(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    for symbol in UNIVERSE:
        rows = []
        for index, offset in enumerate(reversed(range(13))):
            month = shift_month("2026-06", -offset)
            year, number = map(int, month.split("-"))
            timestamp = datetime(year, number, 28, 20, tzinfo=UTC)
            price = Decimal(100 + index)
            rows.append(Candle(symbol, timestamp, price, price, price, price, Decimal("1"), "USD"))
        repository.upsert_candles(rows)

    service = HaaService(settings, FakeClient(), repository)  # type: ignore[arg-type]
    run_id, strategy, plan = service.create_plan("2026-06")
    assert repository.get_run(run_id).signal_month == "2026-06"  # type: ignore[union-attr]
    assert strategy.target_weights
    assert plan.investable_capital > 0
    assert len(repository.pending_notifications()) == 1

    import pytest

    with pytest.raises(ValueError, match="already exists"):
        service.create_plan("2026-06")
