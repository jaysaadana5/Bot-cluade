"""
Trading Engine - orchestrates the 5-minute BTC trading cycle.
Uses regime-based adaptive strategy with dual-chart analysis.
Supports paper and live trading modes.

Paper mode is intentionally more aggressive to generate trades
for algorithm testing. Live mode uses strict filters.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from .polymarket_client import PolymarketClient
from .cointelegraph_sentiment import CoinTelegraphSentiment
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
            "order_id": f"paper_{datetime.utcnow().strftime('%Y%m%d%H%M%S_%f')}",
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
            if pos["entry_price"] == 0:
                continue
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
    def __init__(self, polymarket: PolymarketClient, sentiment: CoinTelegraphSentiment,
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

        # Paper mode uses lower thresholds for active trading
        self._paper_config = TradingConfig()
        self._paper_config.threshold = 15       # $15 instead of $100
        self._paper_config.min_threshold = 10
        self._paper_config.max_threshold = 50

    def set_trading_mode(self, mode: str):
        if mode not in ("paper", "live"):
            raise ValueError("Mode must be 'paper' or 'live'")
        old_mode = self.trading_mode
        self.trading_mode = mode
        logger.info(f"Trading mode switched: {old_mode} -> {mode.upper()}")

    async def run_cycle(self, db: AsyncSession) -> dict:
        """Execute one full trading cycle."""
        if self.trading_mode == "paper":
            return await self._run_paper_cycle(db)
        else:
            return await self._run_live_cycle(db)

    async def _run_paper_cycle(self, db: AsyncSession) -> dict:
        """
        Paper mode cycle - ALWAYS places a trade every cycle for testing.
        Uses TradingView pre-computed indicators as primary signal source.
        """
        cycle_start = datetime.utcnow()
        self.auto_tuner.tick()

        result = {
            "timestamp": cycle_start.isoformat(),
            "status": "completed",
            "trading_mode": "paper",
            "synthetic_market": False,
            "markets_scanned": 0,
            "regime": None,
            "signal": None,
            "trade": None,
            "risk": self.risk_manager.get_stats(),
            "errors": [],
        }

        try:
            # 0. Skip cooldown in paper mode - we always want to see trades
            # (cooldown only matters for live)

            # 1. Get BTC data from TradingView scanner (always works)
            tv_data = {}
            try:
                tv_data = await self.price_feed.get_tradingview_analysis(interval="5") or {}
            except Exception as e:
                logger.warning(f"TradingView scanner failed: {e}")

            # 2. Get candle data from Binance (always works, no key needed)
            candles = []
            spot_prices = []
            spot_volumes = []
            try:
                candles = await self.price_feed.get_5m_candles(limit=50) or []
                spot_prices = self.price_feed.extract_prices(candles) if candles else []
                spot_volumes = self.price_feed.extract_volumes(candles) if candles else []
            except Exception as e:
                logger.warning(f"Candle fetch failed: {e}")

            # Determine BTC price from best available source
            current_btc_price = 0
            if spot_prices:
                current_btc_price = spot_prices[-1]
            elif tv_data.get("price"):
                current_btc_price = tv_data["price"]
                # Build minimal price series from scanner snapshot
                spot_prices = [current_btc_price] * 30

            if current_btc_price == 0:
                result["status"] = "error"
                result["errors"].append("Could not fetch BTC price from any source")
                logger.error("[PAPER] No BTC price available from TradingView or Binance")
                return result

            logger.info(f"[PAPER] BTC=${current_btc_price:.2f}, candles={len(candles)}")

            # 3. Create synthetic market (always works in paper mode)
            use_synthetic = True
            markets = []
            try:
                markets = await self.polymarket.get_btc_markets()
            except Exception:
                pass

            result["markets_scanned"] = len(markets)

            if not markets:
                markets = [self._create_synthetic_market(current_btc_price)]
            else:
                use_synthetic = False

            result["synthetic_market"] = use_synthetic
            market = self._select_best_market(markets)
            self.selected_market = market

            # 4. Poly prices (synthetic from spot data)
            poly_prices = self._derive_synthetic_odds(spot_prices) if spot_prices else [0.5] * 30

            # 5. Detect regime
            regime = detect_regime(spot_prices) if len(spot_prices) >= 20 else {
                "regime": "RANGE", "momentum": 0, "volatility": 0,
                "direction": 0, "trend_efficiency": 0,
            }
            result["regime"] = regime

            # 6. Sentiment (non-blocking)
            sentiment_result = {"score": 0, "tweet_count": 0, "bullish": 0, "bearish": 0, "confidence": 0}
            try:
                sentiment_result = await self.sentiment.analyze_btc_sentiment()
            except Exception as e:
                logger.warning(f"Sentiment fetch failed: {e}")

            try:
                db.add(SentimentLog(
                    source="cointelegraph", keyword="BTC",
                    score=sentiment_result.get("score", 0),
                    tweet_count=sentiment_result.get("tweet_count", 0),
                    bullish_count=sentiment_result.get("bullish", 0),
                    bearish_count=sentiment_result.get("bearish", 0),
                ))
            except Exception:
                pass

            # 7. Determine trade direction using TradingView's PRE-COMPUTED indicators
            #    These are calculated by TradingView from ALL their indicators - always reliable
            tv_rec = tv_data.get("recommend_all") or 0
            tv_rsi = tv_data.get("rsi") or 50
            tv_macd = tv_data.get("macd") or 0
            tv_macd_signal = tv_data.get("macd_signal") or 0
            tv_rec_ma = tv_data.get("recommend_ma") or 0
            tv_rec_osc = tv_data.get("recommend_oscillators") or 0
            tv_momentum = tv_data.get("momentum") or 0
            tv_stoch_k = tv_data.get("stoch_k") or 50
            tv_change = tv_data.get("change") or 0

            logger.info(
                f"[PAPER] TV: rec={tv_rec:.3f} rsi={tv_rsi:.1f} macd={tv_macd:.1f} "
                f"stoch={tv_stoch_k:.1f} mom={tv_momentum:.1f} chg={tv_change:.3f}%"
            )

            trade_direction = None
            trade_confidence = 0
            trade_reasons = []

            # --- Signal cascade: try each until one triggers ---

            # 1. TV recommendation (works even at low values for paper mode)
            if not trade_direction and tv_rec != 0:
                if tv_rec > 0.05:
                    trade_direction = "BUY"
                    trade_confidence = min(0.3 + abs(tv_rec), 0.9)
                    trade_reasons.append(
                        f"[TV] Recommend BUY (all={tv_rec:.3f}, MA={tv_rec_ma:.3f}, osc={tv_rec_osc:.3f})"
                    )
                elif tv_rec < -0.05:
                    trade_direction = "SELL"
                    trade_confidence = min(0.3 + abs(tv_rec), 0.9)
                    trade_reasons.append(
                        f"[TV] Recommend SELL (all={tv_rec:.3f}, MA={tv_rec_ma:.3f}, osc={tv_rec_osc:.3f})"
                    )

            # 2. RSI (wider range for paper)
            if not trade_direction:
                if tv_rsi < 45:
                    trade_direction = "BUY"
                    trade_confidence = 0.3 + (45 - tv_rsi) / 90
                    trade_reasons.append(f"[RSI] Oversold zone RSI={tv_rsi:.1f} → BUY")
                elif tv_rsi > 55:
                    trade_direction = "SELL"
                    trade_confidence = 0.3 + (tv_rsi - 55) / 90
                    trade_reasons.append(f"[RSI] Overbought zone RSI={tv_rsi:.1f} → SELL")

            # 3. MACD
            if not trade_direction:
                macd_diff = tv_macd - tv_macd_signal
                if macd_diff != 0:
                    trade_direction = "BUY" if macd_diff > 0 else "SELL"
                    trade_confidence = min(0.3 + abs(macd_diff) / 500, 0.7)
                    trade_reasons.append(
                        f"[MACD] {'Bullish' if macd_diff > 0 else 'Bearish'} "
                        f"(MACD={tv_macd:.1f}, Signal={tv_macd_signal:.1f})"
                    )

            # 4. Momentum / price change
            if not trade_direction:
                if tv_change > 0:
                    trade_direction = "BUY"
                    trade_confidence = min(0.25 + abs(tv_change) * 10, 0.6)
                    trade_reasons.append(f"[MOM] Positive momentum, change={tv_change:.3f}%")
                elif tv_change < 0:
                    trade_direction = "SELL"
                    trade_confidence = min(0.25 + abs(tv_change) * 10, 0.6)
                    trade_reasons.append(f"[MOM] Negative momentum, change={tv_change:.3f}%")

            # 5. GUARANTEED FALLBACK: if nothing else works, pick based on RSI vs 50
            if not trade_direction:
                trade_direction = "BUY" if tv_rsi <= 50 else "SELL"
                trade_confidence = 0.2
                trade_reasons.append(
                    f"[FALLBACK] RSI={tv_rsi:.1f} {'<=' if tv_rsi <= 50 else '>'} 50 → {trade_direction}"
                )

            logger.info(f"[PAPER] Decision: {trade_direction} conf={trade_confidence:.3f} reason={trade_reasons[-1]}")

            # Build signal for display
            combined_signal = {
                "direction": trade_direction,
                "confidence": round(trade_confidence, 4),
                "combined_score": round(tv_rec, 4),
                "strength": round(trade_confidence, 4),
                "reasons": trade_reasons,
                "scores": {
                    "tv_recommendation": round(tv_rec, 4),
                    "tv_rsi": round(tv_rsi, 2),
                    "tv_macd": round(tv_macd, 2),
                    "sentiment": round(sentiment_result.get("score", 0), 4),
                },
                "spot_ta": {"direction": trade_direction, "avg_signal": round(tv_rec, 4), "reasons": trade_reasons},
                "sentiment": {"score": sentiment_result.get("score", 0), "tweet_count": sentiment_result.get("tweet_count", 0)},
            }
            self.last_signal = combined_signal
            result["signal"] = combined_signal

            # Save snapshot
            try:
                db.add(MarketSnapshot(
                    market_id=market["id"],
                    yes_price=market.get("yes_price", 0),
                    no_price=market.get("no_price", 0),
                    volume=market.get("volume", 0),
                    liquidity=market.get("liquidity", 0),
                    sentiment_score=sentiment_result.get("score", 0),
                    technical_score=tv_rec,
                ))
            except Exception:
                pass

            # 8. EXECUTE PAPER TRADE (guaranteed to happen)
            trade_result = await self._execute_trade(
                db, market,
                {**combined_signal, "direction": trade_direction, "confidence": trade_confidence},
                regime,
            )
            result["trade"] = trade_result
            logger.info(
                f"[PAPER TRADE] {trade_direction} {trade_result.get('size', 0):.2f}"
                f"@{trade_result.get('price', 0):.4f} | {trade_reasons[-1]}"
            )

            # 9. Check paper position exits
            exit_price = poly_prices[-1] if poly_prices else market.get("yes_price", 0.5)
            if exit_price > 0:
                exits = self.paper_engine.check_exits(
                    exit_price,
                    stop_loss=settings.stop_loss_pct,
                    take_profit=settings.take_profit_pct,
                )
                for exit_pos in exits:
                    pnl = exit_pos.get("pnl", 0)
                    self.risk_manager.update(pnl, {
                        "momentum": regime.get("momentum", 0),
                        "volatility": regime.get("volatility", 0),
                        "regime": regime.get("regime", "UNKNOWN"),
                    })

            # 10. Update bot state and COMMIT
            await self._update_bot_state(db)
            await db.commit()
            logger.info("[PAPER] Cycle complete - trade committed to database")

        except Exception as e:
            logger.error(f"Paper trading cycle error: {e}", exc_info=True)
            result["status"] = "error"
            result["errors"].append(str(e))
            # Try to commit whatever we have
            try:
                await db.commit()
            except Exception:
                await db.rollback()

        return result

    async def _run_live_cycle(self, db: AsyncSession) -> dict:
        """Live mode cycle - strict filters, real money at stake."""
        cycle_start = datetime.utcnow()
        self.auto_tuner.tick()

        result = {
            "timestamp": cycle_start.isoformat(),
            "status": "completed",
            "trading_mode": "live",
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

            # 1. Get BTC price data
            tv_data = await self.price_feed.get_tradingview_analysis(interval="5")
            candles = await self.price_feed.get_5m_candles(limit=50)
            spot_prices = self.price_feed.extract_prices(candles) if candles else []
            spot_volumes = self.price_feed.extract_volumes(candles) if candles else []

            if not spot_prices and tv_data.get("price"):
                spot_prices = [tv_data["price"]] * 30

            # 2. Fetch real BTC markets (no synthetic in live mode)
            markets = await self.polymarket.get_btc_markets()
            result["markets_scanned"] = len(markets)

            if not markets:
                result["status"] = "no_markets"
                result["errors"].append("No active BTC markets found on Polymarket")
                return result

            market = self._select_best_market(markets)
            self.selected_market = market
            logger.info(f"Selected market: {market['question']}")

            # 3. Polymarket price data
            token_id = market.get("yes_token")
            poly_history = await self.polymarket.get_price_history(token_id) if token_id else []
            poly_prices = [float(p.get("p", p.get("price", 0.5))) for p in poly_history if p]

            if len(poly_prices) < 5:
                midpoint = await self.polymarket.get_midpoint(token_id) if token_id else None
                poly_prices = [midpoint or market.get("yes_price", 0.5)] * 30

            # 4. Detect regime
            regime = detect_regime(spot_prices) if len(spot_prices) >= 20 else {
                "regime": "UNKNOWN", "momentum": 0, "volatility": 0, "direction": 0,
            }
            result["regime"] = regime

            # Check bad conditions
            if self.risk_manager.is_bad_condition(regime["momentum"], regime["volatility"]):
                result["status"] = "bad_conditions"
                result["errors"].append("Skipping: conditions match previous losing pattern")
                return result

            # 5. Regime decision (strict threshold)
            current_price = spot_prices[-1] if spot_prices else tv_data.get("price", 0)
            previous_price = spot_prices[-6] if len(spot_prices) >= 6 else current_price
            regime_decision = make_regime_decision(
                regime, current_price, previous_price, self.trading_config
            )

            if regime_decision["action"] == "SKIP":
                result["status"] = "skipped"
                result["signal"] = regime_decision
                self.last_signal = regime_decision
                return result

            # 6. Full TA pipeline
            spot_signal = generate_technical_signal(spot_prices, volumes=spot_volumes, label="spot")
            poly_signal = generate_technical_signal(poly_prices, label="polymarket")
            divergence = analyze_spot_vs_polymarket_divergence(spot_prices, poly_prices)

            # 7. Sentiment
            sentiment_result = await self.sentiment.analyze_btc_sentiment()
            sent_log = SentimentLog(
                source="cointelegraph", keyword="BTC",
                score=sentiment_result["score"],
                tweet_count=sentiment_result["tweet_count"],
                bullish_count=sentiment_result["bullish"],
                bearish_count=sentiment_result["bearish"],
            )
            db.add(sent_log)

            # 8. Order book
            orderbook = await self.polymarket.get_orderbook(token_id) if token_id else {}
            book_data = {"buy_pressure": 0.5}
            if orderbook.get("bids") and orderbook.get("asks"):
                bid_vol = sum(float(b.get("size", 0)) for b in orderbook["bids"][:10])
                ask_vol = sum(float(a.get("size", 0)) for a in orderbook["asks"][:10])
                total = bid_vol + ask_vol
                book_data["buy_pressure"] = bid_vol / total if total > 0 else 0.5
            book_pressure = analyze_book_pressure(book_data)

            # 9. Combine
            combined = combine_dual_chart_signals(
                spot_signal=spot_signal,
                poly_signal=poly_signal,
                divergence=divergence,
                sentiment=sentiment_result,
                book_pressure=book_pressure,
            )

            # Regime override
            if regime_decision["confidence"] > 0.6 and combined["direction"] == "HOLD":
                combined["direction"] = regime_decision["direction"]
                combined["confidence"] = regime_decision["confidence"] * 0.8
                combined["reasons"].append(f"[REGIME] Override: {regime_decision['reason']}")

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

            # 10. Execute trade (strict confidence threshold)
            min_confidence = 0.25
            if combined["direction"] != "HOLD" and combined.get("confidence", 0) > min_confidence:
                trade_result = await self._execute_trade(db, market, combined, regime)
                result["trade"] = trade_result
            else:
                logger.info(
                    f"No trade - dir={combined['direction']}, "
                    f"conf={combined.get('confidence', 0):.3f}, regime={regime['regime']}"
                )

            # 11. Auto-tune
            if self.auto_tuner.can_tune() and self.auto_tuner.should_tune(self.risk_manager.pnl_history):
                self.auto_tuner.adjust_threshold(increase=True)

            # 12. Update bot state
            await self._update_bot_state(db)
            await db.commit()

        except Exception as e:
            logger.error(f"Live trading cycle error: {e}", exc_info=True)
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
            strategy=f"regime_{regime.get('regime', 'unknown').lower()}",
            signal_strength=confidence,
            notes=(
                f"Mode: {self.trading_mode} | Regime: {regime.get('regime', '?')} | "
                f"Momentum: {regime.get('momentum', 0):.0f}bp | "
                f"Score: {signal.get('combined_score', 0):.3f}"
            ),
        )
        db.add(trade)

        logger.info(
            f"[{self.trading_mode.upper()}] {direction} {size:.2f}@{limit_price:.4f} "
            f"on {market.get('question', '')[:50]} (regime={regime.get('regime', '?')})"
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
            "regime": regime.get("regime", "?"),
            "confidence": confidence,
        }

    @staticmethod
    def _create_synthetic_market(btc_price: float) -> dict:
        """Create a synthetic BTC market for paper trading."""
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
        """Convert BTC spot prices into synthetic odds (0-1)."""
        if len(spot_prices) < 5:
            return [0.5] * 30

        min_p = min(spot_prices)
        max_p = max(spot_prices)
        price_range = max_p - min_p

        if price_range == 0:
            return [0.5] * len(spot_prices)

        odds = []
        for p in spot_prices:
            normalized = (p - min_p) / price_range
            odd = 0.20 + normalized * 0.60
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
