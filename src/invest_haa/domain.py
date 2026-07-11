from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class Candle:
    symbol: str
    timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    currency: str
    adjusted: bool = True


@dataclass(frozen=True)
class PriceQuote:
    symbol: str
    timestamp: datetime | None
    last_price: Decimal
    currency: str


@dataclass(frozen=True)
class Holding:
    symbol: str
    currency: str
    quantity: Decimal
    last_price: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class MarketDay:
    date: date
    regular_start: datetime | None
    regular_end: datetime | None


@dataclass(frozen=True)
class MarketCalendar:
    today: MarketDay
    previous_business_day: MarketDay
    next_business_day: MarketDay


@dataclass(frozen=True)
class SignalScore:
    symbol: str
    returns: dict[int, Decimal]
    momentum: Decimal
    rank: int | None = None


@dataclass(frozen=True)
class StrategyResult:
    signal_month: str
    signal_date: date
    scores: dict[str, SignalScore]
    target_weights: dict[str, Decimal]
    risk_on: bool
    best_defensive: str


@dataclass(frozen=True)
class PlannedTrade:
    sequence: int
    symbol: str
    side: Literal["SELL", "BUY"]
    current_value: Decimal
    target_value: Decimal
    delta_value: Decimal
    quantity: Decimal | None = None
    order_amount: Decimal | None = None


@dataclass(frozen=True)
class PortfolioPlan:
    gross_capital: Decimal
    cash_buffer: Decimal
    investable_capital: Decimal
    tolerance: Decimal
    estimated_commission: Decimal
    holdings: tuple[Holding, ...]
    quotes: dict[str, PriceQuote]
    buying_power: Decimal
    trades: tuple[PlannedTrade, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    symbol: str
    side: str
    status: str
    quantity: Decimal
    order_amount: Decimal | None
    filled_quantity: Decimal
    average_filled_price: Decimal | None
    filled_amount: Decimal | None
    commission: Decimal | None
    filled_at: datetime | None


JsonObject = dict[str, Any]
