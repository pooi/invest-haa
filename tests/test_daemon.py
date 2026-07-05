from datetime import UTC, date, datetime, timedelta

from invest_haa.daemon import HaaDaemon
from invest_haa.db import Repository
from invest_haa.domain import MarketCalendar, MarketDay


class CalendarClient:
    def __init__(self, market_day: MarketDay):
        self.market_day = market_day

    def us_market_calendar(self, target_date):
        adjacent = MarketDay(target_date - timedelta(days=1), None, None)
        return MarketCalendar(self.market_day, adjacent, adjacent)


class Notifier:
    def __init__(self):
        self.calls = 0

    def flush(self):
        self.calls += 1
        return (0, 0)


def test_daemon_does_not_plan_outside_regular_hours(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    start = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    end = datetime(2026, 7, 6, 20, 0, tzinfo=UTC)
    market_day = MarketDay(date(2026, 7, 6), start, end)
    notifier = Notifier()
    daemon = HaaDaemon(settings, CalendarClient(market_day), repository, notifier)  # type: ignore[arg-type]

    daemon.tick(start - timedelta(seconds=1))
    daemon.tick(end)

    assert notifier.calls == 2
    assert repository.list_runs() == []


def test_daemon_does_not_duplicate_existing_month(settings):
    start = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    end = datetime(2026, 7, 6, 20, 0, tzinfo=UTC)
    market_day = MarketDay(date(2026, 7, 6), start, end)
    notifier = Notifier()

    class ExistingRunRepository:
        def has_run(self, signal_month):
            assert signal_month == "2026-06"
            return True

    daemon = HaaDaemon(
        settings,
        CalendarClient(market_day),  # type: ignore[arg-type]
        ExistingRunRepository(),  # type: ignore[arg-type]
        notifier,  # type: ignore[arg-type]
    )
    daemon.tick(start + timedelta(minutes=1))
    assert notifier.calls == 1
