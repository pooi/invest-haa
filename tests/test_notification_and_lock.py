from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from invest_haa.db import Repository
from invest_haa.domain import Holding, PortfolioPlan, PriceQuote
from invest_haa.lock import ProcessLock
from invest_haa.notification import SlackNotifier
from invest_haa.strategy import calculate_strategy, shift_month
from invest_haa.constants import UNIVERSE


def seed_outbox(repository: Repository):
    closes = {}
    dates = {}
    for symbol in UNIVERSE:
        closes[symbol], dates[symbol] = {}, {}
        for index, offset in enumerate(reversed(range(13))):
            month = shift_month("2026-06", -offset)
            closes[symbol][month] = Decimal(100 + index)
            dates[symbol][month] = date(2026, 6, 30) if month == "2026-06" else date.fromisoformat(f"{month}-28")
    strategy = calculate_strategy(closes, dates, "2026-06")
    plan = PortfolioPlan(
        Decimal("100"),
        Decimal("0.5"),
        Decimal("99.5"),
        Decimal("5"),
        Decimal("0.1"),
        (Holding("SPY", "USD", Decimal("1"), Decimal("100"), Decimal("100")),),
        {"SPY": PriceQuote("SPY", datetime.now(UTC), Decimal("100"), "USD")},
        Decimal("0"),
    )
    repository.save_completed_run(strategy, plan, False, "payload")


def test_slack_outbox_marks_success(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    seed_outbox(repository)

    def handler(request: httpx.Request):
        assert request.url.host == "hooks.slack.com"
        return httpx.Response(200, text="ok", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert SlackNotifier(settings, repository, client).flush() == (1, 0)
    assert repository.pending_notifications() == []


def test_slack_failure_is_retried_without_leaking_webhook(settings):
    repository = Repository(settings.database_url)
    repository.create_schema()
    seed_outbox(repository)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, text="bad", request=request))
    )
    assert SlackNotifier(settings, repository, client).flush() == (0, 1)
    with repository._sessions() as session:
        from invest_haa.db import NotificationOutboxModel

        row = session.query(NotificationOutboxModel).one()
        assert row.attempts == 1
        assert "hooks.slack.com" not in row.last_error


def test_process_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "haa.lock"
    with ProcessLock(path):
        with pytest.raises(RuntimeError, match="another HAA API process"):
            with ProcessLock(path):
                pass
