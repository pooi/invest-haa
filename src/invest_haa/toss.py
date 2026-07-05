from __future__ import annotations

import logging
import random
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import httpx

from .config import TossConnectionSettings
from .domain import Candle, Holding, MarketCalendar, MarketDay, PriceQuote

logger = logging.getLogger(__name__)


class TossApiError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str, request_id: str | None = None):
        super().__init__(f"Toss API {status_code} {code}: {message} (request_id={request_id or 'unknown'})")
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


class TossClient:
    """Read-only client. There is intentionally no order endpoint in this class."""

    def __init__(
        self,
        settings: TossConnectionSettings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self._client = client or httpx.Client(
            base_url=settings.toss_base_url,
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": "invest-haa/0.1.0"},
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)
        self._token_lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TossClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _access_token(self, force: bool = False) -> str:
        with self._token_lock:
            if not force and self._token and datetime.now(UTC) < self._token_expires_at - timedelta(seconds=60):
                return self._token
            for attempt in range(self.settings.max_api_attempts):
                try:
                    response = self._client.post(
                        "/oauth2/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": self.settings.toss_client_id,
                            "client_secret": self.settings.toss_client_secret.get_secret_value(),
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                except httpx.TransportError as exc:
                    if attempt + 1 >= self.settings.max_api_attempts:
                        raise RuntimeError(f"Toss token transport failed after retries: {type(exc).__name__}") from exc
                    self._sleep(self._backoff(attempt))
                    continue
                self._log_rate_limit("/oauth2/token", response)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 >= self.settings.max_api_attempts:
                        self._raise(response)
                    retry_after = _decimal(response.headers.get("Retry-After", "0"))
                    self._sleep(max(float(retry_after), self._backoff(attempt)))
                    continue
                if response.is_error:
                    self._raise(response)
                payload = response.json()
                self._token = str(payload["access_token"])
                self._token_expires_at = datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"]))
                return self._token
            raise RuntimeError("Toss token request exhausted retries")

    def _get(self, path: str, *, params: dict[str, Any] | None = None, account: bool = False) -> Any:
        if path.startswith("/api/v1/orders"):
            raise AssertionError("order endpoints are forbidden in dry-run mode")
        refreshed = False
        last_transport_error: Exception | None = None
        for attempt in range(self.settings.max_api_attempts):
            headers = {"Authorization": f"Bearer {self._access_token()}"}
            if account:
                account_seq = getattr(self.settings, "toss_account_seq", None)
                if account_seq is None:
                    raise ValueError("TOSS_ACCOUNT_SEQ is required for this endpoint")
                headers["X-Tossinvest-Account"] = str(account_seq)
            try:
                response = self._client.get(path, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_transport_error = exc
                if attempt + 1 >= self.settings.max_api_attempts:
                    raise RuntimeError(f"Toss API transport failed after retries: {type(exc).__name__}") from exc
                self._sleep(self._backoff(attempt))
                continue

            self._log_rate_limit(path, response)
            error_code = self._error_code(response)
            if response.status_code == 401 and error_code == "expired-token" and not refreshed:
                self._access_token(force=True)
                refreshed = True
                continue
            if response.status_code == 429:
                if attempt + 1 >= self.settings.max_api_attempts:
                    self._raise(response)
                retry_after = _decimal(response.headers.get("Retry-After", "0"))
                self._sleep(max(float(retry_after), self._backoff(attempt)))
                continue
            if response.status_code >= 500:
                if attempt + 1 >= self.settings.max_api_attempts:
                    self._raise(response)
                self._sleep(self._backoff(attempt))
                continue
            if response.is_error:
                self._raise(response)
            return response.json().get("result")
        raise RuntimeError("Toss API request exhausted retries") from last_transport_error

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(8.0, 2**attempt) + random.uniform(0, 0.25)

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            return str(response.json().get("error", {}).get("code", "unknown-error"))
        except (ValueError, AttributeError):
            return "unknown-error"

    @classmethod
    def _raise(cls, response: httpx.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error", {})
        if isinstance(error, str):
            code, message = error, str(payload.get("error_description", error))
            request_id = None
        else:
            code = str(error.get("code", "unknown-error"))
            message = str(error.get("message", response.reason_phrase))
            request_id = error.get("requestId")
        request_id = request_id or response.headers.get("X-Request-Id") or response.headers.get("x-amz-cf-id")
        raise TossApiError(response.status_code, code, message, request_id)

    @staticmethod
    def _log_rate_limit(path: str, response: httpx.Response) -> None:
        if "X-RateLimit-Limit" in response.headers:
            logger.info(
                "toss_rate_limit path=%s limit=%s remaining=%s reset=%s",
                path,
                response.headers.get("X-RateLimit-Limit"),
                response.headers.get("X-RateLimit-Remaining"),
                response.headers.get("X-RateLimit-Reset"),
            )

    def accounts(self) -> list[dict[str, Any]]:
        return list(self._get("/api/v1/accounts"))

    def stocks(self, symbols: tuple[str, ...]) -> list[dict[str, Any]]:
        return list(self._get("/api/v1/stocks", params={"symbols": ",".join(symbols)}))

    def candle_page(self, symbol: str, before: str | None = None) -> tuple[list[Candle], str | None]:
        params: dict[str, Any] = {"symbol": symbol, "interval": "1d", "count": 200, "adjusted": "true"}
        if before:
            params["before"] = before
        result = self._get("/api/v1/candles", params=params)
        candles = [
            Candle(
                symbol=symbol,
                timestamp=_datetime(item["timestamp"]),
                open_price=_decimal(item["openPrice"]),
                high_price=_decimal(item["highPrice"]),
                low_price=_decimal(item["lowPrice"]),
                close_price=_decimal(item["closePrice"]),
                volume=_decimal(item["volume"]),
                currency=str(item["currency"]),
            )
            for item in result["candles"]
        ]
        return candles, result.get("nextBefore")

    def prices(self, symbols: tuple[str, ...]) -> dict[str, PriceQuote]:
        result = self._get("/api/v1/prices", params={"symbols": ",".join(symbols)})
        return {
            item["symbol"]: PriceQuote(
                item["symbol"],
                _datetime(item["timestamp"]) if item.get("timestamp") else None,
                _decimal(item["lastPrice"]),
                item["currency"],
            )
            for item in result
        }

    def holdings(self) -> list[Holding]:
        result = self._get("/api/v1/holdings", account=True)
        return [
            Holding(
                symbol=item["symbol"],
                currency=item["currency"],
                quantity=_decimal(item["quantity"]),
                last_price=_decimal(item["lastPrice"]),
                market_value=_decimal(item["marketValue"]["amount"]),
            )
            for item in result["items"]
        ]

    def buying_power_usd(self) -> Decimal:
        result = self._get("/api/v1/buying-power", params={"currency": "USD"}, account=True)
        return _decimal(result["cashBuyingPower"])

    def sellable_quantity(self, symbol: str) -> Decimal:
        result = self._get("/api/v1/sellable-quantity", params={"symbol": symbol}, account=True)
        return _decimal(result["sellableQuantity"])

    def us_commission_rate(self) -> Decimal:
        result = self._get("/api/v1/commissions", account=True)
        rows = [item for item in result if item["marketCountry"] == "US"]
        if len(rows) != 1:
            raise ValueError(f"expected exactly one US commission rate, found {len(rows)}")
        return _decimal(rows[0]["commissionRate"])

    def us_market_calendar(self, target_date: date) -> MarketCalendar:
        result = self._get("/api/v1/market-calendar/US", params={"date": target_date.isoformat()})
        return MarketCalendar(
            today=_market_day(result["today"]),
            previous_business_day=_market_day(result["previousBusinessDay"]),
            next_business_day=_market_day(result["nextBusinessDay"]),
        )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _market_day(payload: dict[str, Any]) -> MarketDay:
    regular = payload.get("regularMarket")
    return MarketDay(
        date=date.fromisoformat(payload["date"]),
        regular_start=_datetime(regular["startTime"]) if regular else None,
        regular_end=_datetime(regular["endTime"]) if regular else None,
    )
