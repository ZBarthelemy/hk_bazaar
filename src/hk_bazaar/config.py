"""Application configuration via environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "hk_bazaar.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="HK_BAZAAR_",
        extra="ignore",
    )

    database_url: str = Field(
        default=f"sqlite:///{DEFAULT_DB_PATH}",
        description="SQLAlchemy database URL",
    )
    request_delay_seconds: float = Field(default=1.5, ge=0.0)
    max_retries: int = Field(default=3, ge=1)
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    )
    playwright_headless: bool = True
    playwright_timeout_ms: int = Field(default=30_000, ge=1_000)
    facebook_enabled: bool = False
    facebook_storage_state: Path = Field(default=Path("playwright-state/facebook.json"))
    deal_recent_days: int = Field(default=7, ge=1)
    deal_price_percentile: float = Field(default=25.0, ge=0.0, le=100.0)
    bluebook_catalog_path: Path = Field(default=PROJECT_ROOT / "data" / "bluebook" / "catalog.yaml")

    # Outreach & bidding (conservative defaults — dry-run on)
    outreach_dry_run: bool = True
    outreach_auto_approve: bool = False
    outreach_max_daily: int = Field(default=6, ge=1, le=50)
    outreach_cooldown_days: int = Field(default=7, ge=1)
    outreach_bid_discount: float = Field(default=0.95, gt=0.0, le=1.0)
    outreach_platforms: str = "all"
    carousell_storage_state: Path = Field(default=Path("playwright-state/carousell.json"))
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    asiaxpat_base_url: str = "https://hongkong.asiaxpat.com"
    carousell_base_url: str = "https://www.carousell.com.hk"
    facebook_marketplace_url: str = "https://www.facebook.com/marketplace/hongkong/"


def get_settings() -> Settings:
    return Settings()