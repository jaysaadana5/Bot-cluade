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
from .services.x_sentiment import XSentimentAnalyzer
from .services.trading_engine import TradingEngine
from .services.bot_runner import BotRunner
from .api.routes import router, set_dependencies

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# Global instances
polymarket_client = None
sentiment_analyzer = None
trading_engine = None
bot_runner_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polymarket_client, sentiment_analyzer, trading_engine, bot_runner_instance

    logger.info("Starting Polymarket BTC Trading Bot...")

    # Init database
    await init_db()

    # Init services
    polymarket_client = PolymarketClient(
        api_key=settings.polymarket_api_key,
        secret=settings.polymarket_secret,
        passphrase=settings.polymarket_passphrase,
        funder=settings.polymarket_funder,
    )
    sentiment_analyzer = XSentimentAnalyzer(bearer_token=settings.x_bearer_token)
    trading_engine = TradingEngine(polymarket_client, sentiment_analyzer)
    bot_runner_instance = BotRunner(trading_engine)

    # Wire up API routes
    set_dependencies(bot_runner_instance, polymarket_client, sentiment_analyzer)

    logger.info("All services initialized")
    logger.info(f"Polymarket API: {'configured' if settings.polymarket_api_key else 'PAPER TRADING MODE'}")
    logger.info(f"X Sentiment: {'configured' if settings.x_bearer_token else 'disabled (no token)'}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if bot_runner_instance.is_running:
        bot_runner_instance.stop()
    await polymarket_client.close()
    await sentiment_analyzer.close()


app = FastAPI(
    title="Polymarket BTC Trading Bot",
    description="Automated BTC prediction market trader with X sentiment analysis",
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
