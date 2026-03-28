"""
Regime Detection + Adaptive Trading Strategy

Based on the AI Adaptive Trading system design:
- Detect market regime (TREND / RANGE / CHAOTIC)
- Skip chaotic markets entirely
- Use $100 threshold logic for entries
- 3-loss streak cooldown
- Auto-tune thresholds based on results
"""
import numpy as np
from typing import Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────

class TradingConfig:
    def __init__(self):
        self.threshold = 100         # Min BTC move to consider ($)
        self.min_threshold = 80
        self.max_threshold = 150
        self.threshold_step = 5
        self.tune_cooldown_cycles = 2

        self.momentum_limit = 30     # Max momentum to stay in RANGE
        self.volatility_limit = 70   # Max volatility for non-CHAOTIC

        self.position_size = 100     # $ per trade
        self.stop_loss = 15          # $ stop loss
        self.max_loss_streak = 3
        self.cooldown_hours = 3

        self.entry_second = 35       # Enter at 35th second of candle


# ── Regime Detection ──────────────────────────────────────────────────

def detect_regime(prices: list[float], window: int = 20) -> dict:
    """
    Classify current market into TREND / RANGE / CHAOTIC.

    Uses:
    - Momentum: rate of price change
    - Volatility: standard deviation of returns
    - ADX-like directional index
    """
    if len(prices) < window:
        return {"regime": "UNKNOWN", "momentum": 0, "volatility": 0, "direction": 0}

    recent = prices[-window:]
    returns = np.diff(recent) / recent[:-1]

    # Momentum: net directional move
    momentum = (recent[-1] - recent[0]) / recent[0] * 10000  # basis points

    # Volatility: std of returns (annualized-ish)
    volatility = np.std(returns) * 10000

    # Trend strength: ratio of net move to total path traveled
    total_path = sum(abs(r) for r in returns)
    net_move = abs(recent[-1] - recent[0]) / recent[0]
    trend_efficiency = net_move / total_path if total_path > 0 else 0

    # Direction: +1 bullish, -1 bearish, 0 neutral
    if momentum > 15:
        direction = 1
    elif momentum < -15:
        direction = -1
    else:
        direction = 0

    # Classify
    if volatility > 70:
        regime = "CHAOTIC"
    elif trend_efficiency > 0.3 and abs(momentum) > 20:
        regime = "TREND"
    elif volatility < 30 and abs(momentum) < 15:
        regime = "RANGE"
    else:
        regime = "RANGE"  # Default to range

    return {
        "regime": regime,
        "momentum": round(float(momentum), 2),
        "volatility": round(float(volatility), 2),
        "trend_efficiency": round(float(trend_efficiency), 4),
        "direction": direction,
    }


def detect_regime_from_candles(candles: list[dict], window: int = 20) -> dict:
    """Detect regime from OHLCV candle data (richer signal)."""
    if len(candles) < window:
        return detect_regime([c["close"] for c in candles], window)

    recent = candles[-window:]
    closes = [c["close"] for c in recent]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    volumes = [c["volume"] for c in recent]

    base = detect_regime(closes, window)

    # Enhance with candle body analysis
    bodies = [abs(c["close"] - c["open"]) for c in recent]
    wicks = [c["high"] - c["low"] for c in recent]
    avg_body = np.mean(bodies)
    avg_wick = np.mean(wicks)

    # Large wicks relative to body = indecision/chaotic
    wick_body_ratio = avg_wick / avg_body if avg_body > 0 else 1
    if wick_body_ratio > 3.0 and base["volatility"] > 40:
        base["regime"] = "CHAOTIC"

    # Volume analysis: declining volume in range = breakout coming
    vol_trend = np.polyfit(range(len(volumes)), volumes, 1)[0]
    base["volume_trend"] = "declining" if vol_trend < 0 else "rising"
    base["wick_body_ratio"] = round(wick_body_ratio, 2)

    return base


# ── Risk Management ───────────────────────────────────────────────────

class RiskManager:
    def __init__(self, config: TradingConfig):
        self.config = config
        self.loss_streak = 0
        self.win_streak = 0
        self.cooldown_end = None
        self.total_trades = 0
        self.total_wins = 0
        self.total_losses = 0
        self.pnl_history = []
        self.bad_conditions = []

    def in_cooldown(self) -> bool:
        if self.cooldown_end is None:
            return False
        return datetime.utcnow() < self.cooldown_end

    def trigger_cooldown(self):
        self.cooldown_end = datetime.utcnow() + timedelta(hours=self.config.cooldown_hours)
        logger.warning(f"Cooldown triggered for {self.config.cooldown_hours}h after {self.loss_streak} losses")

    def update(self, profit: float, trade_context: dict = None):
        self.total_trades += 1
        self.pnl_history.append(profit)

        if profit > 0:
            self.total_wins += 1
            self.win_streak += 1
            self.loss_streak = 0
        elif profit < 0:
            self.total_losses += 1
            self.loss_streak += 1
            self.win_streak = 0

            # Store bad condition to avoid repeating
            if trade_context:
                self.bad_conditions.append({
                    "momentum": trade_context.get("momentum", 0),
                    "volatility": trade_context.get("volatility", 0),
                    "regime": trade_context.get("regime", ""),
                })
                # Keep last 20
                self.bad_conditions = self.bad_conditions[-20:]

        # Trigger cooldown on loss streak
        if self.loss_streak >= self.config.max_loss_streak:
            self.trigger_cooldown()

    def is_bad_condition(self, momentum: float, volatility: float) -> bool:
        """Check if current conditions match previous losing patterns."""
        for bad in self.bad_conditions:
            if (abs(bad["momentum"] - momentum) < 10 and
                abs(bad["volatility"] - volatility) < 10):
                return True
        return False

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0
        return self.total_wins / self.total_trades * 100

    def get_stats(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.total_wins,
            "losses": self.total_losses,
            "win_rate": round(self.win_rate, 2),
            "loss_streak": self.loss_streak,
            "win_streak": self.win_streak,
            "in_cooldown": self.in_cooldown(),
            "cumulative_pnl": round(sum(self.pnl_history), 2),
        }


# ── Auto-Tune ─────────────────────────────────────────────────────────

class AutoTuner:
    def __init__(self, config: TradingConfig):
        self.config = config
        self.last_tuned_cycle = -10
        self.current_cycle = 0

    def can_tune(self) -> bool:
        return (self.current_cycle - self.last_tuned_cycle) >= self.config.tune_cooldown_cycles

    def should_tune(self, recent_trades: list[float]) -> bool:
        """Only tune if we see a clear pattern of losses (noise filter)."""
        losses = [t for t in recent_trades[-5:] if t < 0]
        if len(losses) < 3:
            return False
        avg_loss = sum(abs(t) for t in losses) / len(losses)
        return avg_loss > 8  # Significant average loss

    def adjust_threshold(self, increase: bool):
        step = self.config.threshold_step
        if increase:
            new_val = self.config.threshold + step
        else:
            new_val = self.config.threshold - step

        self.config.threshold = max(
            self.config.min_threshold,
            min(new_val, self.config.max_threshold)
        )
        self.last_tuned_cycle = self.current_cycle
        logger.info(f"Auto-tune: threshold → ${self.config.threshold} ({'up' if increase else 'down'})")

    def tick(self):
        self.current_cycle += 1


# ── Regime-Based Trade Decision ───────────────────────────────────────

def make_regime_decision(
    regime: dict,
    current_price: float,
    previous_price: float,
    config: TradingConfig,
) -> dict:
    """
    Core decision engine based on regime + price movement.

    Returns: {action, direction, confidence, reason}
    """
    regime_type = regime["regime"]
    momentum = regime["momentum"]
    volatility = regime["volatility"]
    direction = regime["direction"]
    price_move = current_price - previous_price

    # 1. SKIP chaotic markets
    if regime_type == "CHAOTIC":
        return {
            "action": "SKIP",
            "direction": "NONE",
            "confidence": 0,
            "reason": f"Chaotic market (vol={volatility:.0f}bps) - sitting out",
        }

    # 2. RANGE trading: fade extremes
    if regime_type == "RANGE":
        if abs(price_move) < config.threshold * 0.8:
            return {
                "action": "SKIP",
                "direction": "NONE",
                "confidence": 0,
                "reason": f"Range-bound, move ${price_move:.0f} < threshold ${config.threshold}",
            }

        # In range, fade the move (mean reversion)
        if price_move > config.threshold:
            return {
                "action": "TRADE",
                "direction": "SELL",
                "confidence": min(0.4 + abs(price_move) / config.threshold * 0.2, 0.8),
                "reason": f"Range fade: price up ${price_move:.0f} in range → SELL (mean reversion)",
            }
        elif price_move < -config.threshold:
            return {
                "action": "TRADE",
                "direction": "BUY",
                "confidence": min(0.4 + abs(price_move) / config.threshold * 0.2, 0.8),
                "reason": f"Range fade: price down ${price_move:.0f} in range → BUY (mean reversion)",
            }

    # 3. TREND following
    if regime_type == "TREND":
        if abs(price_move) < config.threshold * 0.5:
            return {
                "action": "SKIP",
                "direction": "NONE",
                "confidence": 0,
                "reason": f"Trend, but move ${price_move:.0f} too small",
            }

        trend_efficiency = regime.get("trend_efficiency", 0)

        if direction > 0:
            return {
                "action": "TRADE",
                "direction": "BUY",
                "confidence": min(0.5 + trend_efficiency * 0.5, 0.9),
                "reason": f"Trend follow: bullish trend (eff={trend_efficiency:.2f}) → BUY",
            }
        elif direction < 0:
            return {
                "action": "TRADE",
                "direction": "SELL",
                "confidence": min(0.5 + trend_efficiency * 0.5, 0.9),
                "reason": f"Trend follow: bearish trend (eff={trend_efficiency:.2f}) → SELL",
            }

    return {
        "action": "SKIP",
        "direction": "NONE",
        "confidence": 0,
        "reason": "No clear setup",
    }
