"""
Main FastAPI application - Polymarket BTC Trading Bot
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .core.database import init_db
from .services.polymarket_client import PolymarketClient
from .services.cointelegraph_sentiment import CoinTelegraphSentiment
from .services.btc_price_feed import BTCPriceFeed
from .services.trading_engine import TradingEngine
from .services.bot_runner import BotRunner
from .api.routes import router, set_dependencies

# Configure logging - stdout only (no file logging to avoid Docker volume issues)
log_handlers = [logging.StreamHandler()]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=log_handlers,
)
logger = logging.getLogger(__name__)

# Global instances
polymarket_client = None
sentiment_analyzer = None
price_feed = None
trading_engine = None
bot_runner_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polymarket_client, sentiment_analyzer, price_feed, trading_engine, bot_runner_instance

    try:
        logger.info("Starting Polymarket BTC Trading Bot...")

        # Init database
        await init_db()

        # Init services
        polymarket_client = PolymarketClient(
            api_key=settings.polymarket_api_key,
            secret=settings.polymarket_secret,
            passphrase=settings.polymarket_passphrase,
            funder=settings.polymarket_funder,
            private_key=settings.polymarket_private_key,
        )
        sentiment_analyzer = CoinTelegraphSentiment()
        price_feed = BTCPriceFeed()
        trading_engine = TradingEngine(polymarket_client, sentiment_analyzer, price_feed)
        bot_runner_instance = BotRunner(trading_engine)

        # Wire up API routes
        set_dependencies(bot_runner_instance, polymarket_client, sentiment_analyzer)

        logger.info("All services initialized")
        logger.info(f"Trading Mode: {settings.trading_mode.upper()}")
        logger.info(f"Trade Amount: ${settings.min_trade_amount}-${settings.max_trade_amount}")
        logger.info("Market: BTC 5min UP/DOWN")
        logger.info("Sentiment: CoinTelegraph RSS (no API key needed)")

    except Exception as e:
        logger.error(f"Startup error: {e}", exc_info=True)
        # Still yield so the app starts (health endpoint works for debugging)

    yield

    # Shutdown
    logger.info("Shutting down...")
    try:
        if bot_runner_instance and bot_runner_instance.is_running:
            bot_runner_instance.stop()
        if polymarket_client:
            await polymarket_client.close()
        if sentiment_analyzer:
            await sentiment_analyzer.close()
        if price_feed:
            await price_feed.close()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


app = FastAPI(
    title="Polymarket BTC Trading Bot",
    description="Automated BTC prediction market trader with CoinTelegraph sentiment",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router)

# Serve frontend build if it exists
frontend_build = os.path.join(os.path.dirname(__file__), "../../frontend/build")
if os.path.isdir(frontend_build):
    app.mount("/", StaticFiles(directory=frontend_build, html=True), name="frontend")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bot_running": bot_runner_instance.is_running if bot_runner_instance else False,
    }
