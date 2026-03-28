"""
API Routes - REST endpoints for the trading bot dashboard.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from ..core.database import get_db
from ..models.trade import Trade, MarketSnapshot, SentimentLog

router = APIRouter(prefix="/api", tags=["trading"])

# These will be set by main.py after initialization
bot_runner = None
polymarket_client = None
sentiment_analyzer = None


def set_dependencies(runner, poly_client, sentiment):
    global bot_runner, polymarket_client, sentiment_analyzer
    bot_runner = runner
    polymarket_client = poly_client
    sentiment_analyzer = sentiment


# ── Bot Control ───────────────────────────────────────────────────────

@router.post("/bot/start")
async def start_bot():
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    bot_runner.start()
    return {"status": "started", "message": "Trading bot started"}


@router.post("/bot/stop")
async def stop_bot():
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    bot_runner.stop()
    return {"status": "stopped", "message": "Trading bot stopped"}


@router.get("/bot/status")
async def bot_status():
    if bot_runner is None:
        return {"is_running": False, "message": "Bot not initialized"}
    return bot_runner.get_status()


@router.post("/bot/run-once")
async def run_once():
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    result = await bot_runner.run_once()
    return result


# ── Markets ───────────────────────────────────────────────────────────

@router.get("/markets")
async def get_markets():
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    markets = await polymarket_client.get_btc_markets()
    return {"markets": markets, "count": len(markets)}


@router.get("/markets/{market_id}")
async def get_market(market_id: str):
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    market = await polymarket_client.get_market(market_id)
    if not market:
        raise HTTPException(404, "Market not found")
    return market


@router.get("/markets/{token_id}/orderbook")
async def get_orderbook(token_id: str):
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    return await polymarket_client.get_orderbook(token_id)


@router.get("/markets/{token_id}/price-history")
async def get_price_history(token_id: str, fidelity: int = 5):
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    history = await polymarket_client.get_price_history(token_id, fidelity)
    return {"history": history}


# ── Sentiment ─────────────────────────────────────────────────────────

@router.get("/sentiment")
async def get_sentiment():
    if sentiment_analyzer is None:
        raise HTTPException(500, "Sentiment analyzer not initialized")
    return await sentiment_analyzer.analyze_btc_sentiment()


@router.get("/sentiment/history")
async def get_sentiment_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SentimentLog).order_by(desc(SentimentLog.timestamp)).limit(limit)
    )
    logs = result.scalars().all()
    return {
        "history": [
            {
                "timestamp": l.timestamp.isoformat() if l.timestamp else "",
                "score": l.score,
                "tweet_count": l.tweet_count,
                "bullish": l.bullish_count,
                "bearish": l.bearish_count,
            }
            for l in logs
        ]
    }


@router.get("/sentiment/trending")
async def get_trending():
    if sentiment_analyzer is None:
        raise HTTPException(500, "Sentiment analyzer not initialized")
    topics = await sentiment_analyzer.get_trending_btc_topics()
    return {"trending": topics}


# ── Portfolio / P&L ──────────────────────────────────────────────────

@router.get("/portfolio")
async def get_portfolio(db: AsyncSession = Depends(get_db)):
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    return await bot_runner.engine.get_portfolio_summary(db)


@router.get("/trades")
async def get_trades(limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Trade).order_by(desc(Trade.timestamp)).offset(offset).limit(limit)
    )
    trades = result.scalars().all()
    return {
        "trades": [
            {
                "id": t.id,
                "timestamp": t.timestamp.isoformat() if t.timestamp else "",
                "market_name": t.market_name,
                "side": t.side,
                "price": t.price,
                "size": t.size,
                "total_cost": t.total_cost,
                "pnl": t.pnl,
                "status": t.status,
                "strategy": t.strategy,
                "signal_strength": t.signal_strength,
            }
            for t in trades
        ],
        "count": len(trades),
    }


# ── Snapshots ────────────────────────────────────────────────────────

@router.get("/snapshots")
async def get_snapshots(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MarketSnapshot).order_by(desc(MarketSnapshot.timestamp)).limit(limit)
    )
    snapshots = result.scalars().all()
    return {
        "snapshots": [
            {
                "timestamp": s.timestamp.isoformat() if s.timestamp else "",
                "market_id": s.market_id,
                "yes_price": s.yes_price,
                "no_price": s.no_price,
                "volume": s.volume,
                "sentiment_score": s.sentiment_score,
                "technical_score": s.technical_score,
            }
            for s in snapshots
        ]
    }


# ── Settings ──────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    from ..core.config import settings
    return {
        "interval_seconds": settings.bot_interval_seconds,
        "max_position_size": settings.max_position_size,
        "risk_per_trade": settings.risk_per_trade,
        "stop_loss_pct": settings.stop_loss_pct,
        "take_profit_pct": settings.take_profit_pct,
        "has_polymarket_key": bool(settings.polymarket_api_key),
        "has_x_token": bool(settings.x_bearer_token),
    }


@router.get("/bot/history")
async def get_bot_history():
    if bot_runner is None:
        return {"history": []}
    return {"history": bot_runner.history[-20:]}
