from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import Settings
from .db import Repository
from .market_data import MarketDataService
from .notification import SlackNotifier
from .service import HaaService
from .strategy import shift_month
from .toss import TossClient

logger = logging.getLogger(__name__)
NEW_YORK = ZoneInfo("America/New_York")


class HaaDaemon:
    def __init__(self, settings: Settings, client: TossClient, repository: Repository, notifier: SlackNotifier):
        self.settings = settings
        self.client = client
        self.repository = repository
        self.notifier = notifier
        self.service = HaaService(settings, client, repository)
        self.market_data = MarketDataService(client, repository)

    def tick(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        local_date = now.astimezone(NEW_YORK).date()
        calendar = self.client.us_market_calendar(local_date)
        regular_start = calendar.today.regular_start
        regular_end = calendar.today.regular_end
        if (
            regular_start is None
            or regular_end is None
            or now < regular_start.astimezone(UTC)
            or now >= regular_end.astimezone(UTC)
        ):
            self.notifier.flush()
            return

        signal_month = shift_month(local_date.strftime("%Y-%m"), -1)
        if not self.repository.has_run(signal_month):
            first_day = date(local_date.year, local_date.month, 1)
            first_calendar = self.client.us_market_calendar(first_day)
            first_business_day = (
                first_calendar.today.date
                if first_calendar.today.regular_start
                else first_calendar.next_business_day.date
            )
            late = local_date > first_business_day
            logger.info("creating_monthly_plan signal_month=%s late=%s", signal_month, late)
            self.market_data.sync_all()
            self.service.create_plan(signal_month, late=late)
        self.notifier.flush()

    def run(self) -> None:
        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(
            self.tick,
            "interval",
            seconds=self.settings.poll_interval_seconds,
            id="haa-monthly-check",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC),
        )
        scheduler.start()
