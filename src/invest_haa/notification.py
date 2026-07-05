from __future__ import annotations

from datetime import timedelta

import httpx

from .config import Settings
from .db import Repository, utcnow


class SlackNotifier:
    def __init__(self, settings: Settings, repository: Repository, client: httpx.Client | None = None):
        self.settings = settings
        self.repository = repository
        self.client = client or httpx.Client(timeout=settings.request_timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def flush(self) -> tuple[int, int]:
        sent = failed = 0
        for item in self.repository.pending_notifications():
            try:
                response = self.client.post(
                    self.settings.slack_webhook_url.get_secret_value(),
                    json={"text": item.payload},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                failed += 1
                delay = min(3600, 60 * (2 ** min(item.attempts, 6)))
                safe_error = f"{type(exc).__name__} while posting Slack notification"
                if isinstance(exc, httpx.HTTPStatusError):
                    safe_error += f" status={exc.response.status_code}"
                self.repository.notification_failed(item.id, safe_error, utcnow() + timedelta(seconds=delay))
            else:
                sent += 1
                self.repository.notification_sent(item.id)
        return sent, failed
