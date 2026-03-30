from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Polymarket
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_funder: str = ""
    polymarket_private_key: str = ""

    # Trading
    trading_mode: str = "paper"  # "paper" or "live"
    bot_interval_seconds: int = 300
    min_trade_amount: float = 2.0    # Minimum $ per trade
    max_trade_amount: float = 5.0    # Maximum $ per trade
    max_position_size: float = 100.0
    risk_per_trade: float = 0.02
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    paper_starting_balance: float = 10000.0

    # Database
    database_url: str = "sqlite:///./data/trading_bot.db"

    # App
    app_name: str = "Polymarket BTC Trading Bot"
    debug: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
