from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from invest_haa.constants import UNIVERSE
from invest_haa.db import DailyCandleModel, Repository
from invest_haa.domain import Candle, Holding, PortfolioPlan, PriceQuote
from invest_haa.market_data import MarketDataService
from invest_haa.strategy import calculate_strategy, shift_month


def candle(symbol: str, timestamp: datetime, close: str) -> Candle:
    value = Decimal(close)
    return Candle(symbol, timestamp, value, value, value, value, Decimal("100"), "USD")


def test_candle_upsert_preserves_decimal_and_month_end(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    first = candle("SPY", datetime(2026, 6, 29, 20, tzinfo=UTC), "100.123456789")
    second = candle("SPY", datetime(2026, 6, 30, 20, tzinfo=UTC), "101.987654321")
    repository.upsert_candles([first, second])
    repository.upsert_candles([candle("SPY", second.timestamp, "102.000000001")])
    stored = repository.candles("SPY")
    assert len(stored) == 2
    assert stored[-1].close_price == Decimal("102.000000001")
    with repository._sessions() as session:
        assert session.scalar(select(func.count()).select_from(DailyCandleModel)) == 2


def test_candle_timestamp_is_normalized_to_utc(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    from datetime import timedelta, timezone

    kst = timezone(timedelta(hours=9))
    original = candle("TIP", datetime(2026, 6, 30, 9, tzinfo=kst), "100")
    repository.upsert_candles([original])
    stored = repository.candles("TIP")[0]
    assert stored.timestamp == datetime(2026, 6, 30, 0, tzinfo=UTC)


def test_monthly_closes_builds_strategy_ready_history(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    for symbol in UNIVERSE:
        for index, offset in enumerate(reversed(range(13))):
            month = shift_month("2026-06", -offset)
            year, number = map(int, month.split("-"))
            repository.upsert_candles([candle(symbol, datetime(year, number, 28, 20, tzinfo=UTC), str(100 + index))])
    market_data = MarketDataService(client=None, repository=repository)  # type: ignore[arg-type]
    closes, dates = market_data.monthly_closes("2026-06")
    result = calculate_strategy(closes, dates, "2026-06")
    assert result.signal_month == "2026-06"
    assert len(closes["SPY"]) == 13


def test_candle_sync_follows_next_before_until_target(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()

    class PageClient:
        def __init__(self):
            self.before = []

        def candle_page(self, symbol, before):
            self.before.append(before)
            start = 0 if before is None else 200
            rows = [
                candle(symbol, datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index), str(index + 1))
                for index in range(start, start + 200)
            ]
            return rows, "page-2" if before is None else None

    client = PageClient()
    service = MarketDataService(client, repository)  # type: ignore[arg-type]
    assert service.sync_symbol("SPY", 400) == 400
    assert client.before == [None, "page-2"]
    assert len(repository.candles("SPY")) == 400


def test_completed_run_is_unique_and_has_ordered_trades(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    closes = {}
    dates = {}
    for symbol in UNIVERSE:
        closes[symbol] = {}
        dates[symbol] = {}
        for index, offset in enumerate(reversed(range(13))):
            month = shift_month("2026-06", -offset)
            closes[symbol][month] = Decimal(100 + index)
            dates[symbol][month] = date(2026, 6, 30) if month == "2026-06" else date.fromisoformat(f"{month}-28")
    strategy = calculate_strategy(closes, dates, "2026-06")
    quote = PriceQuote("SPY", datetime.now(UTC), Decimal("100"), "USD")
    plan = PortfolioPlan(
        gross_capital=Decimal("100"),
        cash_buffer=Decimal("0.5"),
        investable_capital=Decimal("99.5"),
        tolerance=Decimal("5"),
        estimated_commission=Decimal("0.1"),
        holdings=(Holding("SPY", "USD", Decimal("1"), Decimal("100"), Decimal("100")),),
        quotes={"SPY": quote},
        buying_power=Decimal("0"),
    )
    run_id = repository.save_completed_run(strategy, plan, False, "test")
    assert repository.has_run("2026-06")
    assert repository.get_run(run_id).signal_month == "2026-06"  # type: ignore[union-attr]
    assert len(repository.pending_notifications()) == 1
