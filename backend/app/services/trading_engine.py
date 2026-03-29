"""
Trading Engine - orchestrates the 5-minute BTC trading cycle.
Uses regime-based adaptive strategy with dual-chart analysis.
Supports paper and live trading modes.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from .polymarket_client import PolymarketClient
from .x_sentiment import XSentimentAnalyzer
from .btc_price_feed import BTCPriceFeed
from ..strategies.regime import (
    TradingConfig, detect_regime, RiskManager, AutoTuner, make_regime_decision,
)
from ..strategies.signals import (
    generate_technical_signal, combine_dual_chart_signals,
    analyze_spot_vs_polymarket_divergence,
    analyze_book_pressure,
)
from ..models.trade import Trade, BotState, MarketSnapshot, SentimentLog
from ..core.config import settings

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """Simulates order execution and position management for paper trading."""

    def __init__(self, starting_balance: float = 10000.0):
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.positions = []
        self.closed_positions = []

    def place_order(self, side: str, price: float, size: float, market_name: str) -> dict:
        cost = price * size
        if side == "BUY" and cost > self.balance:
            size = self.balance / price * 0.95
            cost = price * size

        self.balance -= cost if side == "BUY" else 0

        position = {
            "order_id": f"paper_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "side": side,
            "entry_price": price,
            "size": size,
            "cost": cost,
            "market_name": market_name,
            "opened_at": datetime.utcnow(),
            "status": "filled",
        }
        self.positions.append(position)

        return {
            "order_id": position["order_id"],
            "status": "paper_filled",
            "side": side,
            "price": price,
            "size": size,
        }

    def check_exits(self, current_price: float, stop_loss: float = 0.05, take_profit: float = 0.10):
        """Check open positions for stop loss / take profit exits."""
        to_close = []
        for pos in self.positions:
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"]
            if pos["side"] == "SELL":
                pnl_pct = -pnl_pct

            if pnl_pct <= -stop_loss or pnl_pct >= take_profit:
                pnl = pnl_pct * pos["cost"]
                pos["exit_price"] = current_price
                pos["pnl"] = pnl
                pos["exit_reason"] = "stop_loss" if pnl_pct <= -stop_loss else "take_profit"
                self.balance += pos["cost"] + pnl
                to_close.append(pos)
            elif (datetime.utcnow() - pos["opened_at"]) > timedelta(minutes=30):
                pnl = pnl_pct * pos["cost"]
                pos["exit_price"] = current_price
                pos["pnl"] = pnl
                pos["exit_reason"] = "time_exit"
                self.balance += pos["cost"] + pnl
                to_close.append(pos)

        for pos in to_close:
            self.positions.remove(pos)
            self.closed_positions.append(pos)

        return to_close

    def get_summary(self) -> dict:
        total_pnl = sum(p.get("pnl", 0) for p in self.closed_positions)
        wins = sum(1 for p in self.closed_positions if p.get("pnl", 0) > 0)
        losses = sum(1 for p in self.closed_positions if p.get("pnl", 0) < 0)
        return {
            "balance": round(self.balance, 2),
            "starting_balance": self.starting_balance,
            "total_pnl": round(total_pnl, 2),
            "pnl_pct": round(total_pnl / self.starting_balance * 100, 2) if self.starting_balance else 0,
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_positions),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / (wins + losses) * 100, 2) if (wins + losses) > 0 else 0,
        }


class TradingEngine:
    def __init__(self, polymarket: PolymarketClient, sentiment: XSentimentAnalyzer,
                 price_feed: BTCPriceFeed = None):
        self.polymarket = polymarket
        self.sentiment = sentiment
        self.price_feed = price_feed or BTCPriceFeed()
        self.is_running = False
        self.last_signal = None
        self.selected_market = None

        # Regime-based strategy components
        self.trading_config = TradingConfig()
        self.risk_manager = RiskManager(self.trading_config)
        self.auto_tuner = AutoTuner(self.trading_config)

        # Paper trading engine
        self.paper_engine = PaperTradingEngine(settings.paper_starting_balance)
        self.trading_mode = settings.trading_mode  # "paper" or "live"

    def set_trading_mode(self, mode: str):
        if mode not in ("paper", "live"):
            raise ValueError("Mode must be 'paper' or 'live'")
        old_mode = self.trading_mode
        self.trading_mode = mode
        logger.info(f"Trading mode switched: {old_mode} -> {mode.upper()}")

    async def run_cycle(self, db: AsyncSession) -> dict:
        """Execute one full trading cycle using regime-based strategy."""
        cycle_start = datetime.utcnow()
        self.auto_tuner.tick()

        result = {
            "timestamp": cycle_start.isoformat(),
            "status": "completed",
            "trading_mode": self.trading_mode,
            "synthetic_market": False,
            "markets_scanned": 0,
            "regime": None,
            "signal": None,
            "trade": None,
            "risk": self.risk_manager.get_stats(),
            "errors": [],
        }

        try:
            # 0. Check cooldown
            if self.risk_manager.in_cooldown():
                result["status"] = "cooldown"
                result["errors"].append(
                    f"In cooldown until {self.risk_manager.cooldown_end.isoformat()}"
                )
                return result

            # 1. Get BTC spot price data from TradingView FIRST (always works)
            tv_data = await self.price_feed.get_tradingview_analysis(interval="5")
            candles = await self.price_feed.get_5m_candles(limit=50)
            spot_prices = self.price_feed.extract_prices(candles) if candles else []
            spot_volumes = self.price_feed.extract_volumes(candles) if candles else []

            if not spot_prices and tv_data.get("price"):
                spot_prices = [tv_data["price"]] * 30

            current_btc_price = spot_prices[-1] if spot_prices else tv_data.get("price", 0)

            # 2. Fetch BTC markets from Polymarket
            markets = await self.polymarket.get_btc_markets()
            result["markets_scanned"] = len(markets)

            # In paper mode, create a synthetic market if none found
            use_synthetic = False
            if not markets and self.trading_mode == "paper" and current_btc_price > 0:
                use_synthetic = True
                markets = [self._create_synthetic_market(current_btc_price)]
                logger.info(f"Paper mode: using synthetic BTC market (BTC=${current_btc_price:.0f})")

            if not markets:
                result["status"] = "no_markets"
                result["errors"].append("No active BTC markets found")
                return result

            result["synthetic_market"] = use_synthetic
            market = self._select_best_market(markets)
            self.selected_market = market
            logger.info(f"Selected market: {market['question']}")

            # 3. Get Polymarket price data (or generate synthetic from BTC price)
            token_id = market.get("yes_token")
            poly_prices = []

            if not use_synthetic and token_id:
                poly_history = await self.polymarket.get_price_history(token_id)
                poly_prices = [float(p.get("p", p.get("price", 0.5))) for p in poly_history if p]

                if len(poly_prices) < 5:
                    midpoint = await self.polymarket.get_midpoint(token_id)
                    poly_prices = [midpoint or market.get("yes_price", 0.5)] * 30

            if len(poly_prices) < 5 and spot_prices:
                # Derive synthetic odds from BTC price movement
                poly_prices = self._derive_synthetic_odds(spot_prices)
                logger.info(f"Using synthetic odds derived from BTC price ({len(poly_prices)} points)")

            # 4. Detect market regime
            regime = detect_regime(spot_prices) if len(spot_prices) >= 20 else {
                "regime": "UNKNOWN", "momentum": 0, "volatility": 0, "direction": 0
            }
            result["regime"] = regime

            # Check for bad conditions from risk manager
            if self.risk_manager.is_bad_condition(regime["momentum"], regime["volatility"]):
                result["status"] = "bad_conditions"
                result["errors"].append("Skipping: conditions match previous losing pattern")
                return result

            # 5. Regime-based decision
            current_price = spot_prices[-1] if spot_prices else tv_data.get("price", 0)
            previous_price = spot_prices[-6] if len(spot_prices) >= 6 else current_price
            regime_decision = make_regime_decision(regime, current_price, previous_price, self.trading_config)

            if regime_decision["action"] == "SKIP":
                result["status"] = "skipped"
                result["signal"] = regime_decision
                self.last_signal = regime_decision
                return result

            # 6. Dual-chart TA confirmation
            spot_signal = generate_technical_signal(spot_prices, volumes=spot_volumes, label="spot")
            poly_signal = generate_technical_signal(poly_prices, label="polymarket")

            # 7. Spot vs Polymarket divergence
            divergence = analyze_spot_vs_polymarket_divergence(spot_prices, poly_prices)

            # 8. X sentiment
            sentiment_result = await self.sentiment.analyze_btc_sentiment()
            sent_log = SentimentLog(
                source="twitter", keyword="BTC",
                score=sentiment_result["score"],
                tweet_count=sentiment_result["tweet_count"],
                bullish_count=sentiment_result["bullish"],
                bearish_count=sentiment_result["bearish"],
            )
            db.add(sent_log)

            # 9. Order book pressure (skip API for synthetic markets)
            orderbook = {}
            if token_id and not use_synthetic:
                orderbook = await self.polymarket.get_orderbook(token_id)
            book_data = {"buy_pressure": 0.5}
            if orderbook.get("bids") and orderbook.get("asks"):
                bid_vol = sum(float(b.get("size", 0)) for b in orderbook["bids"][:10])
                ask_vol = sum(float(a.get("size", 0)) for a in orderbook["asks"][:10])
                total = bid_vol + ask_vol
                book_data["buy_pressure"] = bid_vol / total if total > 0 else 0.5
            book_pressure = analyze_book_pressure(book_data)

            # 10. Combine all signals
            combined = combine_dual_chart_signals(
                spot_signal=spot_signal,
                poly_signal=poly_signal,
                divergence=divergence,
                sentiment=sentiment_result,
                book_pressure=book_pressure,
            )

            # Regime override: if regime is strong but TA says HOLD
            if regime_decision["confidence"] > 0.6 and combined["direction"] == "HOLD":
                combined["direction"] = regime_decision["direction"]
                combined["confidence"] = regime_decision["confidence"] * 0.8
                combined["reasons"].append(f"[REGIME] Override: {regime_decision['reason']}")

            # If combined disagrees with regime, reduce confidence
            if (combined["direction"] != "HOLD" and
                regime_decision["direction"] != "NONE" and
                combined["direction"] != regime_decision["direction"]):
                combined["confidence"] *= 0.5
                combined["reasons"].append("[REGIME] Warning: TA disagrees with regime")

            self.last_signal = combined
            result["signal"] = combined

            # Save snapshot
            snapshot = MarketSnapshot(
                market_id=market["id"],
                yes_price=market.get("yes_price", 0),
                no_price=market.get("no_price", 0),
                volume=market.get("volume", 0),
                liquidity=market.get("liquidity", 0),
                sentiment_score=sentiment_result["score"],
                technical_score=combined.get("combined_score", 0),
            )
            db.add(snapshot)

            # 11. Execute trade if confident enough
            min_confidence = 0.15 if self.trading_mode == "paper" else 0.25
            if combined["direction"] != "HOLD" and combined.get("confidence", 0) > min_confidence:
                trade_result = await self._execute_trade(db, market, combined, regime)
                result["trade"] = trade_result
            else:
                logger.info(
                    f"No trade - dir={combined['direction']}, "
                    f"conf={combined.get('confidence', 0):.3f}, regime={regime['regime']}"
                )

            # 12. Auto-tune
            if self.auto_tuner.can_tune() and self.auto_tuner.should_tune(self.risk_manager.pnl_history):
                self.auto_tuner.adjust_threshold(increase=True)

            # 13. Paper position exit checks (use odds price for exits)
            exit_check_price = market.get("yes_price", 0.5)
            if self.trading_mode == "paper" and exit_check_price > 0:
                exits = self.paper_engine.check_exits(
                    exit_check_price,
                    stop_loss=settings.stop_loss_pct,
                    take_profit=settings.take_profit_pct,
                )
                for exit_pos in exits:
                    self.risk_manager.update(exit_pos.get("pnl", 0), {
                        "momentum": regime["momentum"],
                        "volatility": regime["volatility"],
                        "regime": regime["regime"],
                    })

            # 14. Update bot state
            await self._update_bot_state(db)
            await db.commit()

        except Exception as e:
            logger.error(f"Trading cycle error: {e}", exc_info=True)
            result["status"] = "error"
            result["errors"].append(str(e))

        return result

    async def _execute_trade(self, db: AsyncSession, market: dict, signal: dict, regime: dict) -> dict:
        direction = signal["direction"]
        confidence = signal.get("confidence", 0.5)

        base_size = settings.max_position_size * settings.risk_per_trade
        size = base_size * (0.5 + confidence * 0.5)
        size = max(1.0, min(size, settings.max_position_size))

        if direction == "BUY":
            token_id = market.get("yes_token", "")
            price = market.get("yes_price", 0.5)
            limit_price = min(price + 0.01, 0.99)
        else:
            token_id = market.get("no_token") or market.get("yes_token", "")
            price = market.get("no_price", market.get("yes_price", 0.5))
            limit_price = min(price + 0.01, 0.99)

        if self.trading_mode == "paper":
            order_result = self.paper_engine.place_order(
                side=direction, price=limit_price, size=size,
                market_name=market.get("question", ""),
            )
            status = "paper_filled"
        else:
            order_result = await self.polymarket.place_order(
                token_id=token_id,
                side="BUY" if direction == "BUY" else "SELL",
                price=limit_price,
                size=size,
            )
            status = order_result.get("status", "submitted")

        trade = Trade(
            market_id=market.get("id", ""),
            market_name=market.get("question", ""),
            side=direction,
            token_id=token_id,
            price=limit_price,
            size=size,
            total_cost=limit_price * size,
            order_id=order_result.get("order_id", ""),
            status=status,
            strategy=f"regime_{regime['regime'].lower()}",
            signal_strength=confidence,
            notes=(
                f"Mode: {self.trading_mode} | Regime: {regime['regime']} | "
                f"Momentum: {regime['momentum']:.0f}bp | "
                f"Score: {signal.get('combined_score', 0):.3f}"
            ),
        )
        db.add(trade)

        logger.info(
            f"[{self.trading_mode.upper()}] {direction} {size:.2f}@{limit_price:.4f} "
            f"on {market.get('question', '')[:50]} (regime={regime['regime']})"
        )

        return {
            "mode": self.trading_mode,
            "side": direction,
            "price": limit_price,
            "size": size,
            "total_cost": limit_price * size,
            "order_id": trade.order_id,
            "status": status,
            "market": market.get("question", ""),
            "regime": regime["regime"],
            "confidence": confidence,
        }

    @staticmethod
    def _create_synthetic_market(btc_price: float) -> dict:
        """Create a synthetic BTC market for paper trading when Polymarket has none."""
        # Simulate a "Will BTC be above $X at end of hour?" market
        # yes_price derived from how close BTC is to a round number target
        round_target = round(btc_price / 1000) * 1000
        distance_pct = (btc_price - round_target) / round_target
        yes_price = max(0.10, min(0.90, 0.50 + distance_pct * 5))

        return {
            "id": f"synthetic_btc_{int(btc_price)}",
            "question": f"Will BTC be above ${round_target:,.0f} at end of hour?",
            "description": f"Synthetic paper-trading market. BTC spot: ${btc_price:,.2f}",
            "yes_token": f"syn_yes_{int(btc_price)}",
            "no_token": f"syn_no_{int(btc_price)}",
            "yes_price": round(yes_price, 4),
            "no_price": round(1 - yes_price, 4),
            "volume": 100000,
            "liquidity": 50000,
            "end_date": "",
            "active": True,
            "closed": False,
        }

    @staticmethod
    def _derive_synthetic_odds(spot_prices: list[float]) -> list[float]:
        """
        Convert BTC spot prices into synthetic Polymarket-style odds (0-1).
        Maps price position within recent range to a probability.
        """
        if len(spot_prices) < 5:
            return [0.5] * 30

        min_p = min(spot_prices)
        max_p = max(spot_prices)
        price_range = max_p - min_p

        if price_range == 0:
            return [0.5] * len(spot_prices)

        # Normalize prices to 0.20-0.80 range (typical odds range)
        odds = []
        for p in spot_prices:
            normalized = (p - min_p) / price_range  # 0 to 1
            odd = 0.20 + normalized * 0.60  # 0.20 to 0.80
            odds.append(round(odd, 4))

        return odds

    def _select_best_market(self, markets: list[dict]) -> dict:
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
        result = await db.execute(select(BotState).limit(1))
        state = result.scalar_one_or_none()

        trades_result = await db.execute(select(Trade))
        all_trades = trades_result.scalars().all()

        total_pnl = sum(t.pnl or 0 for t in all_trades)
        filled = [t for t in all_trades if t.status in ("filled", "paper_filled", "paper_trade")]
        wins = sum(1 for t in filled if (t.pnl or 0) > 0)
        win_rate = (wins / len(filled) * 100) if filled else 0

        paper_summary = self.paper_engine.get_summary() if self.trading_mode == "paper" else {}
        balance = paper_summary.get("balance", 0) if paper_summary else 0

        if state is None:
            state = BotState(
                is_running=self.is_running,
                last_run=datetime.utcnow(),
                total_trades=len(all_trades),
                total_pnl=total_pnl,
                win_rate=win_rate,
                current_balance=balance,
            )
            db.add(state)
        else:
            state.is_running = self.is_running
            state.last_run = datetime.utcnow()
            state.total_trades = len(all_trades)
            state.total_pnl = total_pnl
            state.win_rate = win_rate
            state.current_balance = balance

    async def get_portfolio_summary(self, db: AsyncSession) -> dict:
        trades_result = await db.execute(
            select(Trade).order_by(desc(Trade.timestamp)).limit(100)
        )
        trades = trades_result.scalars().all()

        total_invested = sum(t.total_cost for t in trades if t.side == "BUY")
        total_pnl = sum(t.pnl or 0 for t in trades)
        trade_count = len(trades)
        wins = sum(1 for t in trades if (t.pnl or 0) > 0)
        losses = sum(1 for t in trades if (t.pnl or 0) < 0)

        paper_summary = self.paper_engine.get_summary() if self.trading_mode == "paper" else {}

        return {
            "trading_mode": self.trading_mode,
            "total_trades": trade_count,
            "total_invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "pnl_pct": round((total_pnl / total_invested * 100) if total_invested > 0 else 0, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0, 2),
            "paper_trading": paper_summary,
            "risk_stats": self.risk_manager.get_stats(),
            "regime_config": {
                "threshold": self.trading_config.threshold,
                "max_loss_streak": self.trading_config.max_loss_streak,
                "cooldown_hours": self.trading_config.cooldown_hours,
            },
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
