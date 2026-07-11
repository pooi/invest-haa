from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TossConnectionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    toss_client_id: str
    toss_client_secret: SecretStr
    database_url: str = "sqlite:///data/haa.sqlite3"
    log_level: str = "INFO"
    toss_base_url: str = "https://openapi.tossinvest.com"
    request_timeout_seconds: float = Field(default=15.0, gt=0)
    max_api_attempts: int = Field(default=4, ge=1, le=8)
    max_quote_age_seconds: int = Field(default=900, ge=60)

    @field_validator("toss_client_id")
    @classmethod
    def non_placeholder_client_id(cls, value: str) -> str:
        if not value.strip() or value == "PLACEHOLDER":
            raise ValueError("TOSS_CLIENT_ID must be configured")
        return value

    @field_validator("toss_client_secret")
    @classmethod
    def non_placeholder_client_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip() or value.get_secret_value() == "PLACEHOLDER":
            raise ValueError("TOSS_CLIENT_SECRET must be configured")
        return value

    @property
    def sqlite_path(self) -> Path | None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        return Path(self.database_url.removeprefix(prefix))

    @property
    def lock_path(self) -> Path:
        database_path = self.sqlite_path
        return (database_path.parent if database_path else Path("data")) / "haa.lock"


class Settings(TossConnectionSettings):
    toss_account_seq: int = Field(gt=0)
    capital_ceiling_usd: Decimal = Field(gt=0)
    slack_webhook_url: SecretStr

    poll_interval_seconds: int = Field(default=300, ge=60)
    live_trading: bool = False
    live_trading_account_seq: int | None = Field(default=None, gt=0)
    max_single_order_usd: Decimal = Field(default=Decimal("1000"), gt=0)
    order_fill_timeout_seconds: int = Field(default=120, ge=10, le=900)
    order_status_poll_seconds: float = Field(default=2, ge=0.5, le=30)

    @field_validator("live_trading_account_seq", mode="before")
    @classmethod
    def empty_live_account_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def trading_safety(self) -> "Settings":
        if self.live_trading and self.live_trading_account_seq != self.toss_account_seq:
            raise ValueError(
                "LIVE_TRADING=true requires LIVE_TRADING_ACCOUNT_SEQ to exactly match TOSS_ACCOUNT_SEQ"
            )
        if not self.slack_webhook_url.get_secret_value().startswith("https://hooks.slack.com/"):
            raise ValueError("SLACK_WEBHOOK_URL must be an HTTPS Slack incoming webhook URL")
        return self
