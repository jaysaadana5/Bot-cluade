"""
Trading Engine - orchestrates the 5-minute BTC trading cycle.
Fetches market data, computes signals, executes trades, manages risk.
"""
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from .polymarket_client import PolymarketClient
from .x_sentiment import XSentimentAnalyzer
from ..strategies.signals import generate_technical_signal, combine_signals
from ..models.trade import Trade, BotState, MarketSnapshot, SentimentLog
from ..core.config import settings

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, polymarket: PolymarketClient, sentiment: XSentimentAnalyzer):
        self.polymarket = polymarket
        self.sentiment = sentiment
        self.is_running = False
        self.last_signal = None
        self.selected_market = None

    async def run_cycle(self, db: AsyncSession) -> dict:
        """Execute one full trading cycle."""
        cycle_start = datetime.utcnow()
        result = {
            "timestamp": cycle_start.isoformat(),
            "status": "completed",
            "markets_scanned": 0,
            "signal": None,
            "trade": None,
            "errors": [],
        }

        try:
            # 1. Fetch BTC markets
            markets = await self.polymarket.get_btc_markets()
            result["markets_scanned"] = len(markets)

            if not markets:
                result["status"] = "no_markets"
                result["errors"].append("No active BTC markets found")
                return result

            # Pick the best market (highest volume + liquidity)
            market = self._select_best_market(markets)
            self.selected_market = market
            logger.info(f"Selected market: {market['question']}")

            # 2. Get price data
            token_id = market["yes_token"]
            if not token_id:
                result["errors"].append("No token ID for selected market")
                return result

            price_history = await self.polymarket.get_price_history(token_id)
            prices = [float(p.get("p", p.get("price", 0.5))) for p in price_history if p]

            # If not enough history, use current price
            if len(prices) < 5:
                midpoint = await self.polymarket.get_midpoint(token_id)
                if midpoint:
                    prices = [midpoint] * 30  # pad for indicators
                else:
                    prices = [market["yes_price"]] * 30

            # 3. Get sentiment from X
            sentiment_result = await self.sentiment.analyze_btc_sentiment()

            # Save sentiment log
            sent_log = SentimentLog(
                source="twitter",
                keyword="BTC",
                score=sentiment_result["score"],
                tweet_count=sentiment_result["tweet_count"],
                bullish_count=sentiment_result["bullish"],
                bearish_count=sentiment_result["bearish"],
            )
            db.add(sent_log)

            # 4. Generate signals
            technical = generate_technical_signal(prices)
            combined = combine_signals(technical, sentiment_result)
            self.last_signal = combined
            result["signal"] = combined

            # Save market snapshot
            snapshot = MarketSnapshot(
                market_id=market["id"],
                yes_price=market["yes_price"],
                no_price=market["no_price"],
                volume=market["volume"],
                liquidity=market["liquidity"],
                sentiment_score=sentiment_result["score"],
                technical_score=technical.get("avg_signal", 0),
            )
            db.add(snapshot)

            # 5. Execute trade if signal is strong enough
            if combined["direction"] != "HOLD" and combined["confidence"] > 0.2:
                trade_result = await self._execute_trade(db, market, combined)
                result["trade"] = trade_result
            else:
                logger.info(f"No trade - direction={combined['direction']}, confidence={combined['confidence']}")

            # 6. Update bot state
            await self._update_bot_state(db)

            await db.commit()

        except Exception as e:
            logger.error(f"Trading cycle error: {e}", exc_info=True)
            result["status"] = "error"
            result["errors"].append(str(e))

        return result

    async def _execute_trade(self, db: AsyncSession, market: dict, signal: dict) -> dict:
        """Execute a trade based on the signal."""
        direction = signal["direction"]
        strength = signal["strength"]

        # Position sizing based on signal strength and risk settings
        base_size = settings.max_position_size * settings.risk_per_trade
        size = base_size * strength  # Scale by signal strength
        size = max(1.0, min(size, settings.max_position_size))

        # Determine which token to trade
        if direction == "BUY":
            token_id = market["yes_token"]
            price = market["yes_price"]
            # Buy slightly above market for fill probability
            limit_price = min(price + 0.01, 0.99)
        else:
            token_id = market["no_token"] if market["no_token"] else market["yes_token"]
            price = market["no_price"] if market["no_token"] else market["yes_price"]
            limit_price = max(price - 0.01, 0.01) if direction == "SELL" and not market["no_token"] else min(price + 0.01, 0.99)
            if not market["no_token"]:
                direction = "SELL"

        # Place order
        order_result = await self.polymarket.place_order(
            token_id=token_id,
            side="BUY" if direction == "BUY" else "SELL",
            price=limit_price,
            size=size,
        )

        # Record trade
        trade = Trade(
            market_id=market["id"],
            market_name=market["question"],
            side=direction,
            token_id=token_id,
            price=limit_price,
            size=size,
            total_cost=limit_price * size,
            order_id=order_result.get("order_id", order_result.get("orderID", "")),
            status=order_result.get("status", "submitted"),
            strategy="combined_ta_sentiment",
            signal_strength=signal["strength"],
            notes=f"Tech: {signal['tech_score']:.3f}, Sent: {signal['sent_score']:.3f}",
        )
        db.add(trade)

        logger.info(f"Trade executed: {direction} {size:.2f}@{limit_price:.4f} on {market['question'][:50]}")

        return {
            "side": direction,
            "price": limit_price,
            "size": size,
            "total_cost": limit_price * size,
            "order_id": trade.order_id,
            "status": trade.status,
            "market": market["question"],
        }

    def _select_best_market(self, markets: list[dict]) -> dict:
        """Select the best BTC market to trade based on volume and liquidity."""
        scored = []
        for m in markets:
            if m.get("closed") or not m.get("active"):
                continue
            if not m.get("yes_token"):
                continue
            score = (m.get("volume", 0) * 0.6) + (m.get("liquidity", 0) * 0.4)
            scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1] if scored else markets[0]

    async def _update_bot_state(self, db: AsyncSession):
        """Update the bot state record."""
        result = await db.execute(select(BotState).limit(1))
        state = result.scalar_one_or_none()

        # Calculate stats
        trades_result = await db.execute(select(Trade))
        all_trades = trades_result.scalars().all()

        total_pnl = sum(t.pnl or 0 for t in all_trades)
        filled_trades = [t for t in all_trades if t.status in ("filled", "paper_trade")]
        wins = sum(1 for t in filled_trades if (t.pnl or 0) > 0)
        win_rate = (wins / len(filled_trades) * 100) if filled_trades else 0

        if state is None:
            state = BotState(
                is_running=self.is_running,
                last_run=datetime.utcnow(),
                total_trades=len(all_trades),
                total_pnl=total_pnl,
                win_rate=win_rate,
            )
            db.add(state)
        else:
            state.is_running = self.is_running
            state.last_run = datetime.utcnow()
            state.total_trades = len(all_trades)
            state.total_pnl = total_pnl
            state.win_rate = win_rate

    async def get_portfolio_summary(self, db: AsyncSession) -> dict:
        """Get current portfolio summary."""
        trades_result = await db.execute(
            select(Trade).order_by(desc(Trade.timestamp)).limit(100)
        )
        trades = trades_result.scalars().all()

        total_invested = sum(t.total_cost for t in trades if t.side == "BUY")
        total_pnl = sum(t.pnl or 0 for t in trades)
        trade_count = len(trades)
        wins = sum(1 for t in trades if (t.pnl or 0) > 0)
        losses = sum(1 for t in trades if (t.pnl or 0) < 0)

        return {
            "total_trades": trade_count,
            "total_invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "pnl_pct": round((total_pnl / total_invested * 100) if total_invested > 0 else 0, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0, 2),
            "recent_trades": [
                {
                    "id": t.id,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else "",
                    "market": t.market_name,
                    "side": t.side,
                    "price": t.price,
                    "size": t.size,
                    "total_cost": t.total_cost,
                    "pnl": t.pnl,
                    "status": t.status,
                    "strategy": t.strategy,
                }
                for t in trades[:20]
            ],
        }
