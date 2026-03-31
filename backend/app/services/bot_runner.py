"""
Bot Runner - manages trading aligned to Polymarket 5-minute windows.

Timing:
- Polymarket BTC 5min markets run on wall-clock 5-min boundaries:
  :00, :05, :10, :15, :20, :25, :30, :35, :40, :45, :50, :55
- Bot trades at the 4:00 mark of each window (last 60 seconds before close):
  :04:00, :09:00, :14:00, :19:00, :24:00, :29:00, etc.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .trading_engine import TradingEngine
from ..core.database import async_session
from ..core.config import settings

logger = logging.getLogger(__name__)

# Trade at 4 minutes into each 5-minute window
# This means 60 seconds (last minute) before the window closes
TRADE_OFFSET_SECONDS = 240  # 4 * 60 = 240 seconds into the 5-min window
WINDOW_SECONDS = 300  # 5 minutes


def _get_current_window_start() -> datetime:
    """Get the start of the current 5-minute window (aligned to wall clock)."""
    now = datetime.utcnow()
    # Floor to nearest 5-minute boundary
    minute = now.minute - (now.minute % 5)
    return now.replace(minute=minute, second=0, microsecond=0)


def _get_next_trade_time() -> datetime:
    """
    Calculate the next trade execution time.
    Trade at 4:00 into each 5-min window (last 60 seconds before close).
    """
    now = datetime.utcnow()
    window_start = _get_current_window_start()
    trade_time = window_start + timedelta(seconds=TRADE_OFFSET_SECONDS)

    if now >= trade_time:
        # Already past trade time for this window, schedule for next window
        trade_time += timedelta(seconds=WINDOW_SECONDS)

    return trade_time


def _get_window_end() -> datetime:
    """Get the end of the current 5-minute window."""
    return _get_current_window_start() + timedelta(seconds=WINDOW_SECONDS)


class BotRunner:
    def __init__(self, engine: TradingEngine):
        self.engine = engine
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.last_result = None
        self.cycle_count = 0
        self.history = []
        self.last_cycle_at = None
        self.next_cycle_at = None
        self._schedule_task = None

    async def _run_cycle(self):
        """Internal cycle runner - never raises, always returns a result."""
        self.cycle_count += 1
        self.last_cycle_at = datetime.utcnow()

        window_start = _get_current_window_start()
        window_end = _get_window_end()
        time_left = (window_end - self.last_cycle_at).total_seconds()

        logger.info(
            f"=== Trading Cycle #{self.cycle_count} @ {self.last_cycle_at.strftime('%H:%M:%S')} | "
            f"Window {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')} | "
            f"{time_left:.0f}s until close ==="
        )

        # Schedule next trade time
        self.next_cycle_at = _get_next_trade_time()

        try:
            async with async_session() as db:
                try:
                    result = await self.engine.run_cycle(db)
                except Exception as inner_e:
                    logger.error(f"Engine cycle error: {inner_e}", exc_info=True)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    result = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "status": "error",
                        "errors": [str(inner_e)],
                    }

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
            logger.error(f"Cycle error (outer): {e}", exc_info=True)
            self.last_result = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "error",
                "errors": [str(e)],
            }

        return self.last_result

    async def _schedule_loop(self):
        """
        Main scheduling loop - waits until the 4:00 mark of each 5-min window,
        then runs a trading cycle. This ensures trades happen in the last 60 seconds.
        """
        while self.is_running:
            try:
                next_trade = _get_next_trade_time()
                self.next_cycle_at = next_trade
                now = datetime.utcnow()
                wait_seconds = max(0, (next_trade - now).total_seconds())

                if wait_seconds > 0:
                    logger.info(
                        f"Next trade at {next_trade.strftime('%H:%M:%S')} UTC "
                        f"({wait_seconds:.0f}s away, last 60s before window close)"
                    )
                    await asyncio.sleep(wait_seconds)

                if not self.is_running:
                    break

                await self._run_cycle()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Schedule loop error: {e}", exc_info=True)
                await asyncio.sleep(10)  # Brief pause on error

    async def start(self):
        """Start the bot, synced to Polymarket 5-minute windows."""
        if self.is_running:
            logger.warning("Bot is already running")
            return

        self.is_running = True
        self.engine.is_running = True

        next_trade = _get_next_trade_time()
        now = datetime.utcnow()
        wait_seconds = (next_trade - now).total_seconds()
        window_end = _get_window_end()
        time_to_close = (window_end - now).total_seconds()

        logger.info(
            f"Bot started! Synced to Polymarket 5-min windows. "
            f"Current window closes in {time_to_close:.0f}s. "
            f"Next trade at {next_trade.strftime('%H:%M:%S')} ({wait_seconds:.0f}s away)"
        )

        # If we're close enough to the trade time (within 30s), run immediately
        if wait_seconds <= 30:
            logger.info("Within 30s of trade time - running first cycle now")
            asyncio.create_task(self._safe_first_then_loop())
        else:
            # Start the scheduling loop
            self._schedule_task = asyncio.create_task(self._schedule_loop())

        self.next_cycle_at = next_trade

    async def _safe_first_then_loop(self):
        """Run first cycle immediately, then enter the scheduling loop."""
        try:
            await self._run_cycle()
        except Exception as e:
            logger.error(f"First cycle failed: {e}", exc_info=True)
        # Continue with normal scheduling
        if self.is_running:
            self._schedule_task = asyncio.create_task(self._schedule_loop())

    def stop(self):
        """Stop the bot."""
        if not self.is_running:
            logger.warning("Bot is not running")
            return

        self.is_running = False
        self.engine.is_running = False

        if self._schedule_task and not self._schedule_task.done():
            self._schedule_task.cancel()
            self._schedule_task = None

        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
                self.scheduler = AsyncIOScheduler()
        except Exception:
            pass

        logger.info("Bot stopped")

    async def run_once(self) -> dict:
        """Run a single trading cycle manually (ignores timing)."""
        return await self._run_cycle()

    def get_status(self) -> dict:
        now = datetime.utcnow()
        window_start = _get_current_window_start()
        window_end = _get_window_end()
        seconds_in_window = (now - window_start).total_seconds()
        seconds_until_close = max(0, (window_end - now).total_seconds())

        seconds_until_next = 0
        if self.next_cycle_at and self.is_running:
            seconds_until_next = max(0, int((self.next_cycle_at - now).total_seconds()))

        return {
            "is_running": self.is_running,
            "trading_mode": self.engine.trading_mode,
            "cycle_count": self.cycle_count,
            "interval_seconds": WINDOW_SECONDS,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "next_cycle_at": self.next_cycle_at.isoformat() if self.next_cycle_at else None,
            "seconds_until_next": seconds_until_next,
            "window_start": window_start.strftime("%H:%M:%S"),
            "window_end": window_end.strftime("%H:%M:%S"),
            "seconds_in_window": int(seconds_in_window),
            "seconds_until_close": int(seconds_until_close),
            "trade_at": "4:00 mark (last 60 sec before close)",
            "min_trade_amount": settings.min_trade_amount,
            "max_trade_amount": settings.max_trade_amount,
            "last_result": self.last_result,
            "last_signal": self.engine.last_signal,
            "selected_market": self.engine.selected_market,
            "risk_stats": self.engine.risk_manager.get_stats(),
            "paper_summary": self.engine.paper_engine.get_summary() if self.engine.trading_mode == "paper" else None,
        }
