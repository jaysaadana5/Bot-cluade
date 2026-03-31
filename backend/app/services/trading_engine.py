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
from .polymarket_sentiment import PolymarketSentiment
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
    def __init__(self, polymarket: PolymarketClient, sentiment: PolymarketSentiment,
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
        Threshold Breakout Sniper strategy on Polymarket BTC 5min UP/DOWN.

        Logic:
        1. Find BTC 5min market on CLOB /books
        2. Extract threshold price from market question (e.g. "from 68400")
        3. Get current BTC price from Binance
        4. Compare: price_diff = current_price - threshold_price
        5. If diff >= +100 → BUY YES (UP), if diff <= -100 → BUY NO (DOWN)
        6. Safety: |diff| must be between 100 and 500, check liquidity + spread

        This runs at the last 60 seconds of each 5-min window.
        """
        cycle_start = datetime.utcnow()
        self.auto_tuner.tick()

        result = {
            "timestamp": cycle_start.isoformat(),
            "status": "completed",
            "trading_mode": "paper",
            "polymarket_market": None,
            "threshold_price": None,
            "current_btc_price": None,
            "price_diff": None,
            "signal": None,
            "trade": None,
            "risk": self.risk_manager.get_stats(),
            "errors": [],
        }

        try:
            # 1. Find BTC 5min market from CLOB /books (real-time, not Gamma)
            poly_market = None
            try:
                poly_market = await self.polymarket.get_btc_5min_market()
            except Exception as e:
                logger.warning(f"CLOB market search failed: {e}")

            if not poly_market:
                result["status"] = "no_market"
                result["errors"].append("No BTC 5min UP/DOWN market found on Polymarket CLOB")
                logger.error("[SNIPER] No BTC 5min market found")
                return result

            market_id = poly_market.get("id", "")
            question = poly_market.get("question", "")
            threshold_price = poly_market.get("threshold_price")
            result["polymarket_market"] = question
            result["threshold_price"] = threshold_price
            self.selected_market = poly_market

            logger.info(f"[SNIPER] Market: {question} | Threshold: ${threshold_price or '?'}")

            # 2. One trade per market - skip if already traded
            if self.polymarket.already_traded(market_id):
                result["status"] = "already_traded"
                result["errors"].append(f"Already traded this market: {question}")
                logger.info(f"[SNIPER] Skip - already traded {market_id}")
                return result

            # 3. Get current BTC price from Binance
            current_btc_price = 0
            try:
                candles = await self.price_feed.get_5m_candles(limit=5) or []
                if candles:
                    current_btc_price = candles[-1]["close"]
            except Exception as e:
                logger.warning(f"Binance price fetch failed: {e}")

            if current_btc_price == 0:
                try:
                    tv_data = await self.price_feed.get_tradingview_analysis(interval="5") or {}
                    current_btc_price = tv_data.get("price", 0)
                except Exception:
                    pass

            if current_btc_price == 0:
                result["status"] = "error"
                result["errors"].append("Could not fetch BTC price")
                return result

            result["current_btc_price"] = current_btc_price

            # 4. Get orderbook from CLOB for liquidity/spread check
            poly_data = {}
            yes_price = poly_market.get("yes_price", 0.5)
            no_price = poly_market.get("no_price", 0.5)

            if poly_market.get("yes_token"):
                try:
                    poly_data = await self.polymarket.get_market_orderbook_analysis(
                        poly_market["yes_token"],
                        poly_market.get("no_token", ""),
                    )
                    yes_price = poly_data.get("yes_price", 0.5)
                    no_price = poly_data.get("no_price", 0.5)
                except Exception as e:
                    logger.warning(f"Orderbook fetch failed: {e}")

            spread = poly_data.get("spread", 0)
            has_liquidity = poly_data.get("has_liquidity", False)
            buy_pressure = poly_data.get("buy_pressure", 0.5)

            # 5. CORE DECISION: Compare BTC price vs threshold
            trade_direction = None  # "YES" (UP) or "NO" (DOWN)
            trade_confidence = 0
            trade_reasons = []
            price_diff = 0

            if threshold_price and threshold_price > 0:
                price_diff = current_btc_price - threshold_price
                result["price_diff"] = round(price_diff, 2)
                abs_diff = abs(price_diff)

                logger.info(
                    f"[SNIPER] BTC=${current_btc_price:,.2f} | Threshold=${threshold_price:,.2f} | "
                    f"Diff={price_diff:+.2f} | YES={yes_price:.3f} Spread={spread:.4f}"
                )

                # Valid range: between $100 and $500
                if abs_diff >= 100 and abs_diff <= 500:
                    if price_diff >= 100:
                        trade_direction = "YES"
                        trade_confidence = min(0.4 + (abs_diff - 100) / 800, 0.9)
                        trade_reasons.append(
                            f"[BREAKOUT] BTC ${current_btc_price:,.0f} is +${price_diff:,.0f} above "
                            f"threshold ${threshold_price:,.0f} → BUY YES (UP)"
                        )
                    elif price_diff <= -100:
                        trade_direction = "NO"
                        trade_confidence = min(0.4 + (abs_diff - 100) / 800, 0.9)
                        trade_reasons.append(
                            f"[BREAKOUT] BTC ${current_btc_price:,.0f} is -${abs_diff:,.0f} below "
                            f"threshold ${threshold_price:,.0f} → BUY NO (DOWN)"
                        )
                elif abs_diff < 100:
                    result["status"] = "no_breakout"
                    trade_reasons.append(
                        f"[SKIP] Diff ${price_diff:+,.0f} too small (need ±$100). "
                        f"BTC=${current_btc_price:,.0f} vs threshold=${threshold_price:,.0f}"
                    )
                    logger.info(f"[SNIPER] No breakout: diff=${price_diff:+.0f} (need ±100)")
                else:
                    result["status"] = "diff_too_large"
                    trade_reasons.append(
                        f"[SKIP] Diff ${price_diff:+,.0f} too large (max ±$500) - risky"
                    )
                    logger.info(f"[SNIPER] Diff too large: ${price_diff:+.0f}")
            else:
                # No threshold found - use orderbook + YES price as fallback
                logger.warning("[SNIPER] No threshold in market question, using price fallback")
                if yes_price > 0.60:
                    trade_direction = "YES"
                    trade_confidence = 0.3 + (yes_price - 0.50)
                    trade_reasons.append(f"[ODDS] YES={yes_price:.3f} > 0.60 → BUY YES")
                elif no_price > 0.60:
                    trade_direction = "NO"
                    trade_confidence = 0.3 + (no_price - 0.50)
                    trade_reasons.append(f"[ODDS] NO={no_price:.3f} > 0.60 → BUY NO")

            # 6. SAFETY FILTERS
            if trade_direction:
                # Liquidity check
                if not has_liquidity and poly_market.get("yes_token"):
                    trade_reasons.append("[SKIP] No liquidity in orderbook")
                    logger.warning("[SNIPER] Skipping - no liquidity")
                    trade_direction = None

                # Spread check
                if trade_direction and spread > 0.05:
                    trade_reasons.append(f"[SKIP] Spread {spread:.4f} > 0.05 too wide")
                    logger.warning(f"[SNIPER] Skipping - spread {spread:.4f} too wide")
                    trade_direction = None

            # Build signal for display
            combined_signal = {
                "direction": "BUY" if trade_direction == "YES" else "SELL" if trade_direction == "NO" else "HOLD",
                "action": trade_direction,  # YES or NO or None
                "confidence": round(trade_confidence, 4),
                "combined_score": round(price_diff, 2) if price_diff else 0,
                "strength": round(trade_confidence, 4),
                "reasons": trade_reasons,
                "scores": {
                    "price_diff": round(price_diff, 2) if price_diff else 0,
                    "threshold": threshold_price,
                    "btc_price": round(current_btc_price, 2),
                    "polymarket_yes": round(yes_price, 4),
                    "polymarket_no": round(no_price, 4),
                    "buy_pressure": round(buy_pressure, 4),
                    "spread": round(spread, 4),
                },
                "polymarket": {
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "buy_pressure": buy_pressure,
                    "market": question,
                    "threshold": threshold_price,
                },
            }
            self.last_signal = combined_signal
            result["signal"] = combined_signal

            # 7. SETTLE PREVIOUS TRADES
            regime = {"regime": "SNIPER", "momentum": 0, "volatility": 0, "direction": 0}
            try:
                unsettled = await db.execute(
                    select(Trade).where(Trade.status == "paper_filled")
                )
                for old_trade in unsettled.scalars().all():
                    entry_price = old_trade.price
                    if entry_price > 100 and current_btc_price > 100:
                        pct_change = (current_btc_price - entry_price) / entry_price
                        if old_trade.side == "NO":
                            pct_change = -pct_change
                        trade_amt = old_trade.total_cost or old_trade.size or 2.0
                        pnl = round(trade_amt * pct_change * 100, 2)
                        old_trade.pnl = pnl
                        old_trade.status = "settled"
                        old_trade.notes = (old_trade.notes or "") + f" | Exit: ${current_btc_price:,.2f} P&L: ${pnl:+.2f}"
                        self.paper_engine.balance += pnl
                        self.risk_manager.update(pnl, regime)
                    elif entry_price <= 100:
                        old_trade.status = "settled"
                        old_trade.pnl = 0
            except Exception as e:
                logger.warning(f"P&L settlement error: {e}")

            # 8. EXECUTE TRADE (only if we have a direction)
            if trade_direction:
                poly_market["btc_entry_price"] = current_btc_price
                trade_result = await self._execute_trade(
                    db, poly_market,
                    {**combined_signal, "direction": trade_direction, "confidence": trade_confidence},
                    regime,
                )
                result["trade"] = trade_result

                # Mark this market as traded
                self.polymarket.mark_traded(market_id)

                logger.info(
                    f"[SNIPER TRADE] BUY {trade_direction} ${trade_result.get('amount', 0):.2f} | "
                    f"BTC=${current_btc_price:,.2f} vs threshold=${threshold_price:,.2f} | "
                    f"Diff={price_diff:+.0f} | {trade_reasons[-1] if trade_reasons else ''}"
                )
            else:
                logger.info(f"[SNIPER] No trade this cycle. {trade_reasons[-1] if trade_reasons else 'No signal'}")

            # Save snapshot
            try:
                db.add(MarketSnapshot(
                    market_id=market_id or "btc_5min",
                    yes_price=yes_price,
                    no_price=no_price,
                    volume=poly_market.get("volume", 0),
                    liquidity=poly_market.get("liquidity", 0),
                    sentiment_score=price_diff or 0,
                    technical_score=trade_confidence,
                ))
            except Exception:
                pass

            await self._update_bot_state(db)
            await db.commit()

        except Exception as e:
            logger.error(f"Sniper cycle error: {e}", exc_info=True)
            result["status"] = "error"
            result["errors"].append(str(e))
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

            # 7. Sentiment from Polymarket odds (not CoinTelegraph)
            sentiment_result = await self.sentiment.analyze_btc_sentiment()
            sent_log = SentimentLog(
                source="polymarket", keyword="BTC",
                score=sentiment_result["score"],
                tweet_count=sentiment_result.get("tweet_count", 0),
                bullish_count=sentiment_result.get("bullish", 0),
                bearish_count=sentiment_result.get("bearish", 0),
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
        direction = signal["direction"]  # "YES" (UP) or "NO" (DOWN) or legacy "BUY"/"SELL"
        confidence = signal.get("confidence", 0.5)

        # Trade amount: scale between min ($2) and max ($5) based on confidence
        min_amt = settings.min_trade_amount
        max_amt = settings.max_trade_amount
        trade_amount = min_amt + (max_amt - min_amt) * confidence
        trade_amount = round(max(min_amt, min(trade_amount, max_amt)), 2)

        # BTC entry price for P&L tracking
        btc_entry = market.get("btc_entry_price", 0)

        # Determine token_id and price based on YES/NO direction
        # YES = buy yes_token (UP), NO = buy no_token (DOWN)
        if direction in ("YES", "BUY"):
            token_id = market.get("yes_token", "")
            price = market.get("yes_price", 0.5)
            trade_label = "BUY YES (UP)"
        elif direction in ("NO", "SELL"):
            token_id = market.get("no_token") or market.get("yes_token", "")
            price = market.get("no_price", market.get("yes_price", 0.5))
            trade_label = "BUY NO (DOWN)"
        else:
            token_id = market.get("yes_token", "")
            price = market.get("yes_price", 0.5)
            trade_label = f"BUY {direction}"

        # Size = trade_amount / price (number of contracts/shares)
        limit_price = min(price + 0.01, 0.99) if price > 0 else 0.50
        size = round(trade_amount / limit_price, 2) if limit_price > 0 else trade_amount

        if self.trading_mode == "paper":
            order_result = self.paper_engine.place_order(
                side=direction, price=limit_price, size=size,
                market_name=market.get("question", ""),
            )
            status = "paper_filled"
        else:
            # Live mode: always BUY the selected token (YES or NO token)
            order_result = await self.polymarket.place_order(
                token_id=token_id,
                side="BUY",
                price=limit_price,
                size=size,
            )
            status = order_result.get("status", "submitted")

        trade = Trade(
            market_id=market.get("id", ""),
            market_name=f"BTC 5min {trade_label}",
            side=direction,
            token_id=token_id,
            price=btc_entry if btc_entry > 0 else limit_price,
            size=trade_amount,
            total_cost=trade_amount,
            order_id=order_result.get("order_id", ""),
            status=status,
            strategy="threshold_breakout_sniper",
            signal_strength=confidence,
            notes=(
                f"{trade_label} | BTC: ${btc_entry:,.2f} | Amount: ${trade_amount:.2f} | "
                f"Diff: {signal.get('combined_score', 0):+.0f} | "
                f"Conf: {confidence:.2f}"
            ),
        )
        db.add(trade)

        logger.info(
            f"[{self.trading_mode.upper()}] {trade_label} ${trade_amount:.2f} "
            f"BTC@${btc_entry:,.2f} (conf={confidence:.2f})"
        )

        return {
            "mode": self.trading_mode,
            "side": direction,
            "action": trade_label,
            "btc_price": btc_entry,
            "amount": trade_amount,
            "price": limit_price,
            "size": size,
            "total_cost": trade_amount,
            "order_id": trade.order_id,
            "status": status,
            "market": f"BTC 5min {trade_label}",
            "regime": regime.get("regime", "?"),
            "confidence": confidence,
        }

    @staticmethod
    def _create_synthetic_market(btc_price: float) -> dict:
        """Create a BTC 5min UP/DOWN market for paper trading."""
        return {
            "id": f"btc_5min_{int(btc_price)}",
            "question": f"BTC 5min UP/DOWN",
            "description": f"BTC 5-minute direction signal. Spot: ${btc_price:,.2f}",
            "yes_token": f"btc5m_up_{int(btc_price)}",
            "no_token": f"btc5m_down_{int(btc_price)}",
            "yes_price": 0.50,
            "no_price": 0.50,
            "btc_entry_price": btc_price,
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
        if not markets:
            return self._create_synthetic_market(0)
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
