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
    await bot_runner.start()
    return {"status": "started", "message": "Trading bot started - first cycle running now"}


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


# ── Trading Mode ──────────────────────────────────────────────────────

@router.get("/trading-mode")
async def get_trading_mode():
    if bot_runner is None:
        return {"mode": "paper", "message": "Bot not initialized"}
    return {
        "mode": bot_runner.engine.trading_mode,
        "paper_summary": bot_runner.engine.paper_engine.get_summary() if bot_runner.engine.trading_mode == "paper" else None,
    }


@router.post("/trading-mode/{mode}")
async def set_trading_mode(mode: str):
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    if mode not in ("paper", "live"):
        raise HTTPException(400, "Mode must be 'paper' or 'live'")
    if mode == "live" and not bot_runner.engine.polymarket.is_live_ready:
        raise HTTPException(400, "Cannot switch to live mode - Polymarket API not fully configured. Generate API keys first.")
    bot_runner.engine.set_trading_mode(mode)
    return {
        "status": "ok",
        "mode": mode,
        "message": f"Trading mode switched to {mode.upper()}",
    }


# ── Risk / Regime Stats ─────────────────────────────────────────────

@router.get("/risk-stats")
async def get_risk_stats():
    if bot_runner is None:
        raise HTTPException(500, "Bot not initialized")
    return {
        "risk": bot_runner.engine.risk_manager.get_stats(),
        "regime_config": {
            "threshold": bot_runner.engine.trading_config.threshold,
            "max_loss_streak": bot_runner.engine.trading_config.max_loss_streak,
            "cooldown_hours": bot_runner.engine.trading_config.cooldown_hours,
        },
    }


# ── Settings ──────────────────────────────────────────────────────────

@router.get("/settings")
async def get_settings():
    from ..core.config import settings
    return {
        "trading_mode": bot_runner.engine.trading_mode if bot_runner else settings.trading_mode,
        "interval_seconds": settings.bot_interval_seconds,
        "min_trade_amount": settings.min_trade_amount,
        "max_trade_amount": settings.max_trade_amount,
        "max_position_size": settings.max_position_size,
        "risk_per_trade": settings.risk_per_trade,
        "stop_loss_pct": settings.stop_loss_pct,
        "take_profit_pct": settings.take_profit_pct,
        "has_polymarket_key": bool(settings.polymarket_api_key),
        "has_private_key": bool(settings.polymarket_private_key),
        "polymarket_live_ready": polymarket_client.is_live_ready if polymarket_client else False,
        "polymarket_funder": settings.polymarket_funder or "",
        "sentiment_source": "cointelegraph",
        "paper_starting_balance": settings.paper_starting_balance,
    }


@router.post("/settings/trade-amounts")
async def update_trade_amounts(min_amount: float = 2.0, max_amount: float = 5.0):
    """Update min/max trade amounts (persists until restart)."""
    from ..core.config import settings
    if min_amount < 0.5 or max_amount > 100:
        raise HTTPException(400, "Trade amount must be between $0.50 and $100")
    if min_amount > max_amount:
        raise HTTPException(400, "Min amount cannot exceed max amount")
    settings.min_trade_amount = round(min_amount, 2)
    settings.max_trade_amount = round(max_amount, 2)
    return {
        "status": "ok",
        "min_trade_amount": settings.min_trade_amount,
        "max_trade_amount": settings.max_trade_amount,
    }


@router.get("/bot/history")
async def get_bot_history():
    if bot_runner is None:
        return {"history": []}
    return {"history": bot_runner.history[-20:]}


# ── Polymarket API Management ────────────────────────────────────────

@router.get("/polymarket/status")
async def polymarket_status():
    """Get Polymarket API connection status."""
    if polymarket_client is None:
        return {"status": "not_initialized", "live_ready": False}
    return {
        "status": "connected" if polymarket_client.is_live_ready else "paper_only",
        "live_ready": polymarket_client.is_live_ready,
        "has_api_key": bool(polymarket_client.api_key),
        "has_private_key": bool(polymarket_client.private_key),
        "funder": polymarket_client.funder or "",
    }


@router.post("/polymarket/derive-credentials")
async def derive_credentials():
    """
    Generate Polymarket API credentials from the configured private key.
    The private key must be set in the .env file as POLYMARKET_PRIVATE_KEY.
    """
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    if not polymarket_client.private_key:
        raise HTTPException(400, "No private key configured. Set POLYMARKET_PRIVATE_KEY in .env")

    result = await polymarket_client.derive_api_credentials()
    if "error" in result:
        raise HTTPException(500, result["error"])

    # Return credentials (user can save to .env)
    return {
        "status": "ok",
        "message": "API credentials generated. Add these to your .env file for persistence.",
        "credentials": {
            "POLYMARKET_API_KEY": result["api_key"],
            "POLYMARKET_SECRET": result["api_secret"],
            "POLYMARKET_PASSPHRASE": result["api_passphrase"],
        },
        "live_ready": polymarket_client.is_live_ready,
    }


@router.get("/polymarket/balance")
async def get_polymarket_balance():
    """Get USDC balance on Polymarket."""
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    return await polymarket_client.get_balance()


@router.get("/polymarket/positions")
async def get_polymarket_positions():
    """Get current Polymarket positions."""
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    positions = await polymarket_client.get_positions()
    return {"positions": positions}


@router.get("/polymarket/open-orders")
async def get_open_orders():
    """Get open orders on Polymarket."""
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    orders = await polymarket_client.get_open_orders()
    return {"orders": orders}


@router.post("/polymarket/cancel-all")
async def cancel_all_orders():
    """Cancel all open Polymarket orders."""
    if polymarket_client is None:
        raise HTTPException(500, "Polymarket client not initialized")
    if not polymarket_client.is_live_ready:
        raise HTTPException(400, "Not in live mode - no orders to cancel")
    return await polymarket_client.cancel_all_orders()
