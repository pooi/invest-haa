from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

import typer
from pydantic import ValidationError

from .config import Settings, TossConnectionSettings
from .daemon import HaaDaemon
from .db import Repository
from .lock import ProcessLock
from .logging_config import configure_logging
from .notification import SlackNotifier
from .service import HaaService
from .strategy import month_end
from .toss import TossClient

app = typer.Typer(help="HAA Toss OpenAPI dry-run planner", no_args_is_help=True)


def _settings() -> Settings:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        typer.echo(f"Configuration error:\n{exc}", err=True)
        raise typer.Exit(2) from exc
    configure_logging(settings.log_level)
    return settings


def _connection_settings() -> TossConnectionSettings:
    try:
        settings = TossConnectionSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        typer.echo(f"Configuration error:\n{exc}", err=True)
        raise typer.Exit(2) from exc
    configure_logging(settings.log_level)
    return settings


def _repository(settings: Settings) -> Repository:
    repository = Repository(settings.database_url)
    repository.create_schema()
    return repository


@contextmanager
def _api_context() -> Iterator[tuple[Settings, Repository, TossClient]]:
    settings = _settings()
    repository = _repository(settings)
    with ProcessLock(settings.lock_path), TossClient(settings) as client:
        yield settings, repository, client


@app.command()
def accounts() -> None:
    """List accessible account sequence values without requiring account configuration."""
    settings = _connection_settings()
    with ProcessLock(settings.lock_path), TossClient(settings) as client:
        payload = [{"accountSeq": item["accountSeq"], "accountType": item["accountType"]} for item in client.accounts()]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def validate() -> None:
    """Validate configuration, account, symbols, and local market data."""
    with _api_context() as (settings, repository, client):
        result = HaaService(settings, client, repository).validate()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ready"]:
            raise typer.Exit(1)


@app.command("sync-prices")
def sync_prices() -> None:
    """Refresh the latest 400 adjusted daily candles for all HAA symbols."""
    with _api_context() as (_, repository, client):
        from .market_data import MarketDataService

        result = MarketDataService(client, repository).sync_all()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def plan(
    signal_month: str = typer.Option(..., help="Signal month in YYYY-MM form"),
    late: bool = typer.Option(False, help="Mark this manually generated plan as late"),
) -> None:
    """Create and persist a read-only rebalance plan."""
    try:
        month_end(signal_month)
    except (ValueError, IndexError) as exc:
        raise typer.BadParameter("signal-month must be YYYY-MM") from exc
    with _api_context() as (settings, repository, client):
        service = HaaService(settings, client, repository)
        run_id, strategy, portfolio_plan = service.create_plan(signal_month, late=late)
        notifier = SlackNotifier(settings, repository)
        try:
            sent, failed = notifier.flush()
        finally:
            notifier.close()
        typer.echo(
            json.dumps(
                {
                    "runId": run_id,
                    "signalMonth": strategy.signal_month,
                    "riskOn": strategy.risk_on,
                    "targetWeights": {key: str(value) for key, value in strategy.target_weights.items()},
                    "investableCapital": str(portfolio_plan.investable_capital),
                    "plannedTrades": len(portfolio_plan.trades),
                    "notificationsSent": sent,
                    "notificationsFailed": failed,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


@app.command()
def daemon() -> None:
    """Run the single-instance monthly planning daemon."""
    settings = _settings()
    repository = _repository(settings)
    with ProcessLock(settings.lock_path), TossClient(settings) as client:
        notifier = SlackNotifier(settings, repository)
        try:
            HaaDaemon(settings, client, repository, notifier).run()
        finally:
            notifier.close()


@app.command()
def runs(limit: int = typer.Option(20, min=1, max=100)) -> None:
    """List persisted dry-run executions without calling Toss API."""
    settings = _settings()
    repository = _repository(settings)
    payload = [
        {
            "id": row.id,
            "signalMonth": row.signal_month,
            "status": row.status,
            "late": row.late,
            "riskOn": row.risk_on,
            "investableCapital": row.investable_capital,
        }
        for row in repository.list_runs(limit)
    ]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("show-run")
def show_run(run_id: str) -> None:
    """Show one persisted dry-run and its ordered virtual trades."""
    settings = _settings()
    repository = _repository(settings)
    row = repository.get_run(run_id)
    if row is None:
        typer.echo(f"run not found: {run_id}", err=True)
        raise typer.Exit(1)
    payload = {
        "id": row.id,
        "signalMonth": row.signal_month,
        "signalDate": row.signal_date.isoformat(),
        "mode": row.mode,
        "status": row.status,
        "late": row.late,
        "riskOn": row.risk_on,
        "bestDefensive": row.best_defensive,
        "grossCapital": row.gross_capital,
        "cashBuffer": row.cash_buffer,
        "investableCapital": row.investable_capital,
        "tolerance": row.tolerance,
        "trades": [
            {
                "sequence": trade.sequence,
                "symbol": trade.symbol,
                "side": trade.side,
                "quantity": trade.quantity,
                "orderAmount": trade.order_amount,
                "deltaValue": trade.delta_value,
            }
            for trade in sorted(row.trades, key=lambda trade: trade.sequence)
        ],
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
