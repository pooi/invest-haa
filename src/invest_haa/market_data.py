from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from .constants import UNIVERSE
from .db import Repository
from .toss import TossClient

NEW_YORK = ZoneInfo("America/New_York")


class MarketDataService:
    def __init__(self, client: TossClient, repository: Repository):
        self.client = client
        self.repository = repository

    def validate_universe(self) -> list[dict]:
        stocks = self.client.stocks(UNIVERSE)
        by_symbol = {item["symbol"]: item for item in stocks}
        errors: list[str] = []
        for symbol in UNIVERSE:
            item = by_symbol.get(symbol)
            if item is None:
                errors.append(f"{symbol}: not found")
                continue
            if item["status"] != "ACTIVE":
                errors.append(f"{symbol}: status={item['status']}")
            if item["currency"] != "USD":
                errors.append(f"{symbol}: currency={item['currency']}")
            if item["securityType"] not in {"ETF", "FOREIGN_ETF"}:
                errors.append(f"{symbol}: securityType={item['securityType']}")
        if errors:
            raise ValueError("invalid HAA universe: " + "; ".join(errors))
        return stocks

    def sync_symbol(self, symbol: str, target_count: int = 400) -> int:
        before: str | None = None
        seen_before: set[str] = set()
        candles = []
        while len(candles) < target_count:
            page, next_before = self.client.candle_page(symbol, before)
            candles.extend(page)
            if not next_before or next_before in seen_before:
                break
            seen_before.add(next_before)
            before = next_before
        unique = {candle.timestamp: candle for candle in candles}
        selected = sorted(unique.values(), key=lambda candle: candle.timestamp)[-target_count:]
        return self.repository.upsert_candles(selected)

    def sync_all(self, target_count: int = 400) -> dict[str, int]:
        self.validate_universe()
        return {symbol: self.sync_symbol(symbol, target_count) for symbol in UNIVERSE}

    def monthly_closes(self, signal_month: str) -> tuple[dict[str, dict[str, Decimal]], dict[str, dict[str, date]]]:
        closes: dict[str, dict[str, Decimal]] = {}
        dates: dict[str, dict[str, date]] = {}
        for symbol in UNIVERSE:
            last_by_month = {}
            for candle in self.repository.candles(symbol):
                local = candle.timestamp.astimezone(NEW_YORK)
                month = local.strftime("%Y-%m")
                if month <= signal_month and (
                    month not in last_by_month or candle.timestamp > last_by_month[month].timestamp
                ):
                    last_by_month[month] = candle
            closes[symbol] = {month: candle.close_price for month, candle in last_by_month.items()}
            dates[symbol] = {
                month: candle.timestamp.astimezone(NEW_YORK).date() for month, candle in last_by_month.items()
            }
        return closes, dates
