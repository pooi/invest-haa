from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable

from .config import Settings
from .constants import UNIVERSE
from .db import Repository
from .domain import BrokerOrder, PortfolioPlan
from .toss import TossClient


class LiveExecutionError(RuntimeError):
    pass


class LiveExecutor:
    def __init__(
        self,
        settings: Settings,
        client: TossClient,
        repository: Repository,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.client = client
        self.repository = repository
        self.sleep = sleep

    def execute(self, run_id: str, signal_month: str, plan: PortfolioPlan) -> list[BrokerOrder]:
        if not self.settings.live_trading:
            raise LiveExecutionError("LIVE_TRADING=true is required")
        if self.settings.live_trading_account_seq != self.settings.toss_account_seq:
            raise LiveExecutionError("live trading account allowlist mismatch")
        self.repository.set_run_state(run_id, mode="LIVE", status="VALIDATING")
        completed: list[BrokerOrder] = []
        try:
            self._require_regular_market()
            if any(trade.symbol not in UNIVERSE for trade in plan.trades):
                raise LiveExecutionError("plan contains a symbol outside the HAA allowlist")
            existing_open_orders = sorted(self.client.open_order_symbols() & set(UNIVERSE))
            if existing_open_orders:
                raise LiveExecutionError(
                    "existing OPEN orders must be resolved before rebalancing: " + ", ".join(existing_open_orders)
                )

            self.repository.set_run_state(run_id, status="SELLING")
            for trade in (item for item in plan.trades if item.side == "SELL"):
                value = (trade.quantity or Decimal("0")) * plan.quotes[trade.symbol].last_price
                self._check_order_limit(value)
                completed.append(self._submit_and_wait(run_id, signal_month, trade))

            self.repository.set_run_state(run_id, status="BUYING")
            buying_power = self.client.buying_power_usd()
            for trade in (item for item in plan.trades if item.side == "BUY"):
                amount = trade.order_amount or Decimal("0")
                self._check_order_limit(amount)
                if amount > buying_power:
                    raise LiveExecutionError(
                        f"BUY {trade.symbol} ${amount} exceeds refreshed buying power ${buying_power}"
                    )
                order = self._submit_and_wait(run_id, signal_month, trade)
                completed.append(order)
                buying_power = self.client.buying_power_usd()
        except Exception as exc:
            self.repository.set_run_state(run_id, status="HALTED", error=str(exc))
            raise

        self.repository.set_run_state(run_id, status="COMPLETED", error=None)
        return completed

    def _submit_and_wait(self, run_id: str, signal_month: str, trade: object) -> BrokerOrder:
        sequence = int(getattr(trade, "sequence"))
        symbol = str(getattr(trade, "symbol"))
        side = str(getattr(trade, "side"))
        quantity = getattr(trade, "quantity")
        amount = getattr(trade, "order_amount")
        client_order_id = f"haa-{signal_month.replace('-', '')}-{sequence:02d}-{symbol}-{side.lower()}"
        self.repository.create_live_order(
            run_id=run_id,
            sequence=sequence,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            amount=amount,
        )
        broker_order_id = self.client.create_market_order(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_amount=amount,
        )
        self.repository.live_order_submitted(client_order_id, broker_order_id)
        return self._wait_for_fill(client_order_id, broker_order_id)

    def _wait_for_fill(self, client_order_id: str, broker_order_id: str) -> BrokerOrder:
        deadline = time.monotonic() + self.settings.order_fill_timeout_seconds
        while True:
            order = self.client.order(broker_order_id)
            self.repository.update_live_order(client_order_id, order)
            if order.status == "FILLED":
                return order
            if order.status in {"CANCELED", "REJECTED", "REPLACED"}:
                raise LiveExecutionError(
                    f"order {broker_order_id} ended as {order.status} after filling {order.filled_quantity}"
                )
            if time.monotonic() >= deadline:
                self.client.cancel_order(broker_order_id)
                raise LiveExecutionError(f"order {broker_order_id} timed out and cancellation was requested")
            self.sleep(self.settings.order_status_poll_seconds)

    def _require_regular_market(self) -> None:
        now = datetime.now(UTC)
        calendar = self.client.us_market_calendar(now.date())
        start = calendar.today.regular_start
        end = calendar.today.regular_end
        if start is None or end is None or not (start.astimezone(UTC) <= now < end.astimezone(UTC)):
            raise LiveExecutionError("live orders are only allowed during the US regular market session")

    def _check_order_limit(self, value: Decimal) -> None:
        if value <= 0:
            raise LiveExecutionError("live order value must be positive")
        if value > self.settings.max_single_order_usd:
            raise LiveExecutionError(
                f"order value ${value:.2f} exceeds MAX_SINGLE_ORDER_USD=${self.settings.max_single_order_usd}"
            )
