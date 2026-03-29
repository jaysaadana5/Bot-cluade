"""
Bot Runner - manages the 5-minute trading loop using APScheduler.
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .trading_engine import TradingEngine
from ..core.database import async_session
from ..core.config import settings

logger = logging.getLogger(__name__)


class BotRunner:
    def __init__(self, engine: TradingEngine):
        self.engine = engine
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.last_result = None
        self.cycle_count = 0
        self.history = []

    async def _run_cycle(self):
        """Internal cycle runner."""
        self.cycle_count += 1
        logger.info(f"=== Trading Cycle #{self.cycle_count} @ {datetime.utcnow().isoformat()} ===")

        try:
            async with async_session() as db:
                result = await self.engine.run_cycle(db)
                self.last_result = result
                self.history.append(result)
                if len(self.history) > 50:
                    self.history = self.history[-50:]

                if result.get("trade"):
                    logger.info(f"Trade executed: {result['trade']}")
                else:
                    signal = result.get("signal") or {}
                    logger.info(
                        f"No trade this cycle. Status: {result.get('status', 'N/A')}, "
                        f"Signal: {signal.get('direction', 'N/A')}"
                    )
        except Exception as e:
            logger.error(f"Cycle error: {e}", exc_info=True)
            self.last_result = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "error",
                "errors": [str(e)],
            }

        return self.last_result

    async def start(self):
        """Start the bot scheduler and run first cycle immediately."""
        if self.is_running:
            logger.warning("Bot is already running")
            return

        self.is_running = True
        self.engine.is_running = True

        # Run first cycle immediately in background
        asyncio.create_task(self._run_cycle())

        # Then schedule repeating cycles
        interval = settings.bot_interval_seconds
        if not self.scheduler.running:
            self.scheduler.start()

        self.scheduler.add_job(
            self._run_cycle,
            "interval",
            seconds=interval,
            id="trading_cycle",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"Bot started - first cycle running now, then every {interval}s")

    def stop(self):
        """Stop the bot scheduler."""
        if not self.is_running:
            logger.warning("Bot is not running")
            return

        try:
            self.scheduler.remove_job("trading_cycle")
        except Exception:
            pass
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.engine.is_running = False
        logger.info("Bot stopped")

    async def run_once(self) -> dict:
        """Run a single trading cycle manually."""
        return await self._run_cycle()

    def get_status(self) -> dict:
        return {
            "is_running": self.is_running,
            "trading_mode": self.engine.trading_mode,
            "cycle_count": self.cycle_count,
            "interval_seconds": settings.bot_interval_seconds,
            "last_result": self.last_result,
            "last_signal": self.engine.last_signal,
            "selected_market": self.engine.selected_market,
            "risk_stats": self.engine.risk_manager.get_stats(),
            "paper_summary": self.engine.paper_engine.get_summary() if self.engine.trading_mode == "paper" else None,
        }
