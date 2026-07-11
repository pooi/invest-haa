from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .domain import Candle, PortfolioPlan, StrategyResult


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class DailyCandleModel(Base):
    __tablename__ = "daily_candles"
    __table_args__ = (UniqueConstraint("symbol", "timestamp", "adjusted"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    adjusted: Mapped[bool] = mapped_column(Boolean)
    open_price: Mapped[str] = mapped_column(String(40))
    high_price: Mapped[str] = mapped_column(String(40))
    low_price: Mapped[str] = mapped_column(String(40))
    close_price: Mapped[str] = mapped_column(String(40))
    volume: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RebalanceRunModel(Base):
    __tablename__ = "rebalance_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_month: Mapped[str] = mapped_column(String(7), unique=True, index=True)
    signal_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16), default="DRY_RUN")
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED")
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_on: Mapped[bool] = mapped_column(Boolean)
    best_defensive: Mapped[str] = mapped_column(String(16))
    gross_capital: Mapped[str] = mapped_column(String(40))
    cash_buffer: Mapped[str] = mapped_column(String(40))
    investable_capital: Mapped[str] = mapped_column(String(40))
    tolerance: Mapped[str] = mapped_column(String(40))
    buying_power: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    trades: Mapped[list["PlannedTradeModel"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class SignalModel(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("signal_month", "symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_month: Mapped[str] = mapped_column(String(7), index=True)
    signal_date: Mapped[date] = mapped_column(Date)
    symbol: Mapped[str] = mapped_column(String(16))
    r1: Mapped[str] = mapped_column(String(40))
    r3: Mapped[str] = mapped_column(String(40))
    r6: Mapped[str] = mapped_column(String(40))
    r12: Mapped[str] = mapped_column(String(40))
    momentum: Mapped[str] = mapped_column(String(40))
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TargetAllocationModel(Base):
    __tablename__ = "target_allocations"
    __table_args__ = (UniqueConstraint("signal_month", "symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_month: Mapped[str] = mapped_column(String(7), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    target_weight: Mapped[str] = mapped_column(String(40))


class PortfolioSnapshotModel(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rebalance_runs.id"), unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    holdings_json: Mapped[str] = mapped_column(Text)
    quotes_json: Mapped[str] = mapped_column(Text)
    buying_power: Mapped[str] = mapped_column(String(40))


class PlannedTradeModel(Base):
    __tablename__ = "planned_trades"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rebalance_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    current_value: Mapped[str] = mapped_column(String(40))
    target_value: Mapped[str] = mapped_column(String(40))
    delta_value: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[str | None] = mapped_column(String(40), nullable=True)
    order_amount: Mapped[str | None] = mapped_column(String(40), nullable=True)

    run: Mapped[RebalanceRunModel] = relationship(back_populates="trades")


class NotificationOutboxModel(Base):
    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rebalance_runs.id"), index=True)
    payload: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LiveOrderModel(Base):
    __tablename__ = "live_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rebalance_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    client_order_id: Mapped[str] = mapped_column(String(36), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    requested_quantity: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requested_amount: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="CREATED")
    filled_quantity: Mapped[str] = mapped_column(String(40), default="0")
    average_filled_price: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filled_amount: Mapped[str | None] = mapped_column(String(40), nullable=True)
    commission: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("run_id", "sequence"),)


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///"):
        path = Path(database_url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, future=True)


class Repository:
    def __init__(self, database_url: str):
        self.engine = make_engine(database_url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    def upsert_candles(self, candles: list[Candle]) -> int:
        with self.session() as session:
            changed = 0
            for candle in candles:
                normalized_timestamp = candle.timestamp.astimezone(UTC).replace(tzinfo=None)
                row = session.scalar(
                    select(DailyCandleModel).where(
                        DailyCandleModel.symbol == candle.symbol,
                        DailyCandleModel.timestamp == normalized_timestamp,
                        DailyCandleModel.adjusted == candle.adjusted,
                    )
                )
                values = {
                    "open_price": str(candle.open_price),
                    "high_price": str(candle.high_price),
                    "low_price": str(candle.low_price),
                    "close_price": str(candle.close_price),
                    "volume": str(candle.volume),
                    "currency": candle.currency,
                    "fetched_at": utcnow(),
                }
                if row is None:
                    session.add(
                        DailyCandleModel(
                            symbol=candle.symbol,
                            timestamp=normalized_timestamp,
                            adjusted=candle.adjusted,
                            **values,
                        )
                    )
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                changed += 1
            return changed

    def candles(self, symbol: str) -> list[Candle]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DailyCandleModel)
                .where(DailyCandleModel.symbol == symbol, DailyCandleModel.adjusted.is_(True))
                .order_by(DailyCandleModel.timestamp)
            ).all()
            return [
                Candle(
                    row.symbol,
                    _as_utc(row.timestamp),
                    Decimal(row.open_price),
                    Decimal(row.high_price),
                    Decimal(row.low_price),
                    Decimal(row.close_price),
                    Decimal(row.volume),
                    row.currency,
                    row.adjusted,
                )
                for row in rows
            ]

    def has_run(self, signal_month: str) -> bool:
        with self._sessions() as session:
            return (
                session.scalar(select(RebalanceRunModel.id).where(RebalanceRunModel.signal_month == signal_month))
                is not None
            )

    def target_allocations(self, signal_month: str) -> dict[str, Decimal]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TargetAllocationModel).where(TargetAllocationModel.signal_month == signal_month)
            ).all()
            return {row.symbol: Decimal(row.target_weight) for row in rows}

    def save_completed_run(self, strategy: StrategyResult, plan: PortfolioPlan, late: bool, message: str) -> str:
        run_id = str(uuid.uuid4())
        holdings_json = json.dumps(
            [
                {
                    "symbol": item.symbol,
                    "currency": item.currency,
                    "quantity": str(item.quantity),
                    "lastPrice": str(item.last_price),
                    "marketValue": str(item.market_value),
                }
                for item in plan.holdings
            ],
            separators=(",", ":"),
        )
        quotes_json = json.dumps(
            {
                symbol: {
                    "lastPrice": str(quote.last_price),
                    "currency": quote.currency,
                    "timestamp": quote.timestamp.isoformat() if quote.timestamp else None,
                }
                for symbol, quote in plan.quotes.items()
            },
            separators=(",", ":"),
        )
        with self.session() as session:
            session.add(
                RebalanceRunModel(
                    id=run_id,
                    signal_month=strategy.signal_month,
                    signal_date=strategy.signal_date,
                    late=late,
                    risk_on=strategy.risk_on,
                    best_defensive=strategy.best_defensive,
                    gross_capital=str(plan.gross_capital),
                    cash_buffer=str(plan.cash_buffer),
                    investable_capital=str(plan.investable_capital),
                    tolerance=str(plan.tolerance),
                    buying_power=str(plan.buying_power),
                )
            )
            for score in strategy.scores.values():
                session.add(
                    SignalModel(
                        signal_month=strategy.signal_month,
                        signal_date=strategy.signal_date,
                        symbol=score.symbol,
                        r1=str(score.returns[1]),
                        r3=str(score.returns[3]),
                        r6=str(score.returns[6]),
                        r12=str(score.returns[12]),
                        momentum=str(score.momentum),
                        rank=score.rank,
                    )
                )
            for symbol, weight in strategy.target_weights.items():
                session.add(
                    TargetAllocationModel(signal_month=strategy.signal_month, symbol=symbol, target_weight=str(weight))
                )
            session.add(
                PortfolioSnapshotModel(
                    run_id=run_id,
                    holdings_json=holdings_json,
                    quotes_json=quotes_json,
                    buying_power=str(plan.buying_power),
                )
            )
            for trade in plan.trades:
                session.add(
                    PlannedTradeModel(
                        run_id=run_id,
                        sequence=trade.sequence,
                        symbol=trade.symbol,
                        side=trade.side,
                        current_value=str(trade.current_value),
                        target_value=str(trade.target_value),
                        delta_value=str(trade.delta_value),
                        quantity=str(trade.quantity) if trade.quantity is not None else None,
                        order_amount=str(trade.order_amount) if trade.order_amount is not None else None,
                    )
                )
            session.add(NotificationOutboxModel(run_id=run_id, payload=message))
        return run_id

    def set_run_state(self, run_id: str, *, mode: str | None = None, status: str | None = None, error: str | None = None) -> None:
        with self.session() as session:
            row = session.get(RebalanceRunModel, run_id)
            if row is None:
                raise ValueError(f"run not found: {run_id}")
            if mode is not None:
                row.mode = mode
            if status is not None:
                row.status = status
            row.error = error

    def create_live_order(
        self,
        *,
        run_id: str,
        sequence: int,
        client_order_id: str,
        symbol: str,
        side: str,
        quantity: Decimal | None,
        amount: Decimal | None,
    ) -> None:
        with self.session() as session:
            session.add(
                LiveOrderModel(
                    run_id=run_id,
                    sequence=sequence,
                    client_order_id=client_order_id,
                    symbol=symbol,
                    side=side,
                    requested_quantity=str(quantity) if quantity is not None else None,
                    requested_amount=str(amount) if amount is not None else None,
                )
            )

    def live_order_submitted(self, client_order_id: str, broker_order_id: str) -> None:
        with self.session() as session:
            row = session.scalar(select(LiveOrderModel).where(LiveOrderModel.client_order_id == client_order_id))
            if row is None:
                raise ValueError(f"live order not found: {client_order_id}")
            row.broker_order_id = broker_order_id
            row.status = "PENDING"
            row.updated_at = utcnow()

    def update_live_order(self, client_order_id: str, order: object) -> None:
        with self.session() as session:
            row = session.scalar(select(LiveOrderModel).where(LiveOrderModel.client_order_id == client_order_id))
            if row is None:
                raise ValueError(f"live order not found: {client_order_id}")
            row.status = str(getattr(order, "status"))
            row.filled_quantity = str(getattr(order, "filled_quantity"))
            row.average_filled_price = _optional_str(getattr(order, "average_filled_price"))
            row.filled_amount = _optional_str(getattr(order, "filled_amount"))
            row.commission = _optional_str(getattr(order, "commission"))
            row.filled_at = getattr(order, "filled_at")
            row.updated_at = utcnow()

    def live_orders(self, run_id: str) -> list[LiveOrderModel]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(LiveOrderModel).where(LiveOrderModel.run_id == run_id).order_by(LiveOrderModel.sequence)
                )
            )

    def list_runs(self, limit: int = 20) -> list[RebalanceRunModel]:
        with self._sessions() as session:
            return list(
                session.scalars(select(RebalanceRunModel).order_by(RebalanceRunModel.signal_month.desc()).limit(limit))
            )

    def get_run(self, run_id: str) -> RebalanceRunModel | None:
        with self._sessions() as session:
            row = session.scalar(select(RebalanceRunModel).where(RebalanceRunModel.id == run_id))
            if row is not None:
                _ = row.trades
            return row

    def pending_notifications(self, now: datetime | None = None, limit: int = 20) -> list[NotificationOutboxModel]:
        now = now or utcnow()
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(NotificationOutboxModel)
                    .where(NotificationOutboxModel.sent_at.is_(None), NotificationOutboxModel.next_attempt_at <= now)
                    .order_by(NotificationOutboxModel.id)
                    .limit(limit)
                )
            )

    def notification_sent(self, notification_id: int) -> None:
        with self.session() as session:
            row = session.get(NotificationOutboxModel, notification_id)
            if row:
                row.sent_at = utcnow()
                row.last_error = None

    def notification_failed(self, notification_id: int, error: str, next_attempt_at: datetime) -> None:
        with self.session() as session:
            row = session.get(NotificationOutboxModel, notification_id)
            if row:
                row.attempts += 1
                row.last_error = error[:1000]
                row.next_attempt_at = next_attempt_at


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_str(value: object | None) -> str | None:
    return str(value) if value is not None else None
