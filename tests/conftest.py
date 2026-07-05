from decimal import Decimal

import pytest

from invest_haa.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        toss_client_id="client-id",
        toss_client_secret="client-secret",
        toss_account_seq=1,
        capital_ceiling_usd=Decimal("10000"),
        slack_webhook_url="https://hooks.slack.com/services/test/test/test",
        database_url=f"sqlite:///{tmp_path / 'haa.sqlite3'}",
        request_timeout_seconds=1,
        max_api_attempts=4,
    )
