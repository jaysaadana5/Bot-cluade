from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from ..core.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    market_id = Column(String(255), nullable=False)
    market_name = Column(String(500), nullable=True)
    side = Column(String(10), nullable=False)  # BUY or SELL
    token_id = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)
    order_id = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")  # pending, filled, cancelled, failed
    pnl = Column(Float, default=0.0)
    strategy = Column(String(100), nullable=True)
    signal_strength = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)


class BotState(Base):
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    is_running = Column(Boolean, default=False)
    last_run = Column(DateTime, nullable=True)
    total_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    current_balance = Column(Float, default=0.0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    market_id = Column(String(255), nullable=False)
    yes_price = Column(Float, nullable=True)
    no_price = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    liquidity = Column(Float, nullable=True)
    sentiment_score = Column(Float, nullable=True)
    technical_score = Column(Float, nullable=True)


class SentimentLog(Base):
    __tablename__ = "sentiment_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now(), nullable=False)
    source = Column(String(50), nullable=False)  # twitter, aggregated
    keyword = Column(String(255), nullable=True)
    score = Column(Float, nullable=False)  # -1.0 to 1.0
    tweet_count = Column(Integer, default=0)
    bullish_count = Column(Integer, default=0)
    bearish_count = Column(Integer, default=0)
    raw_data = Column(Text, nullable=True)
