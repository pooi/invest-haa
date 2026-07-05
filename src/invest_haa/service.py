from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import Settings
from .constants import UNIVERSE
from .db import Repository
from .domain import PortfolioPlan, StrategyResult
from .market_data import MarketDataService
from .portfolio import build_portfolio_plan
from .strategy import calculate_strategy
from .strategy import InsufficientHistory, shift_month
from .toss import TossClient


class HaaService:
    def __init__(self, settings: Settings, client: TossClient, repository: Repository):
        self.settings = settings
        self.client = client
        self.repository = repository
        self.market_data = MarketDataService(client, repository)

    def validate_account(self) -> dict:
        accounts = self.client.accounts()
        matches = [item for item in accounts if int(item["accountSeq"]) == self.settings.toss_account_seq]
        if len(matches) != 1:
            raise ValueError(f"TOSS_ACCOUNT_SEQ={self.settings.toss_account_seq} is not an accessible account")
        if matches[0]["accountType"] != "BROKERAGE":
            raise ValueError("configured account must be BROKERAGE")
        return matches[0]

    def validate(self) -> dict:
        account = self.validate_account()
        stocks = self.market_data.validate_universe()
        counts = {symbol: len(self.market_data.repository.candles(symbol)) for symbol in UNIVERSE}
        signal_month = shift_month(datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m"), -1)
        history_error = None
        try:
            closes, dates = self.market_data.monthly_closes(signal_month)
            calculate_strategy(closes, dates, signal_month)
        except (InsufficientHistory, ValueError) as exc:
            history_error = str(exc)
        return {
            "accountSeq": account["accountSeq"],
            "accountType": account["accountType"],
            "validSymbols": len(stocks),
            "dailyCandleCounts": counts,
            "signalMonth": signal_month,
            "historyError": history_error,
            "ready": history_error is None and all(count >= 253 for count in counts.values()),
        }

    def create_plan(self, signal_month: str, *, late: bool = False) -> tuple[str, StrategyResult, PortfolioPlan]:
        if self.repository.has_run(signal_month):
            raise ValueError(f"a run already exists for {signal_month}")
        self.validate_account()
        self.market_data.validate_universe()
        closes, dates = self.market_data.monthly_closes(signal_month)
        strategy = calculate_strategy(closes, dates, signal_month)

        holdings = self.client.holdings()
        quotes = self.client.prices(UNIVERSE)
        missing_quotes = sorted(set(UNIVERSE) - set(quotes))
        if missing_quotes:
            raise ValueError(f"missing quotes: {', '.join(missing_quotes)}")
        now = datetime.now(UTC)
        stale_quotes = sorted(
            symbol
            for symbol, quote in quotes.items()
            if quote.timestamp is None
            or abs((now - quote.timestamp.astimezone(UTC)).total_seconds()) > self.settings.max_quote_age_seconds
        )
        if stale_quotes:
            raise ValueError(f"missing or stale quotes: {', '.join(stale_quotes)}")
        buying_power = self.client.buying_power_usd()
        commission_rate = self.client.us_commission_rate()
        sellable = {
            holding.symbol: self.client.sellable_quantity(holding.symbol)
            for holding in holdings
            if holding.symbol in UNIVERSE and holding.currency == "USD" and holding.quantity > 0
        }
        plan = build_portfolio_plan(
            target_weights=strategy.target_weights,
            holdings=holdings,
            quotes=quotes,
            buying_power=buying_power,
            capital_ceiling=self.settings.capital_ceiling_usd,
            us_commission_rate_percent=commission_rate,
            sellable_quantities=sellable,
        )
        message = format_slack_message(strategy, plan, late)
        run_id = self.repository.save_completed_run(strategy, plan, late, message)
        return run_id, strategy, plan


def format_slack_message(strategy: StrategyResult, plan: PortfolioPlan, late: bool) -> str:
    regime = "Risk-On" if strategy.risk_on else "Risk-Off"
    weights = ", ".join(
        f"{symbol} {weight * Decimal('100')}%" for symbol, weight in sorted(strategy.target_weights.items())
    )
    trades = []
    for trade in plan.trades:
        detail = f"{trade.quantity}주" if trade.side == "SELL" else f"${trade.order_amount}"
        trades.append(f"{trade.sequence}. {trade.side} {trade.symbol} {detail}")
    trade_text = "\n".join(trades) if trades else "거래 없음"
    return (
        f"[HAA DRY-RUN] {strategy.signal_month}{' (late)' if late else ''}\n"
        f"국면: {regime} / 방어자산: {strategy.best_defensive}\n"
        f"목표: {weights}\n"
        f"운용액: ${plan.investable_capital:.2f} / 현금버퍼: ${plan.cash_buffer:.2f}\n"
        f"가상 주문:\n{trade_text}"
    )
