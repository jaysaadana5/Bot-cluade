"""
Trading signal generators - technical analysis + sentiment fusion.
Each function returns a signal dict with direction, strength, and reason.
"""
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def compute_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Compute RSI from a list of prices."""
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(prices: list[float], period: int) -> list[float]:
    """Compute EMA for given period."""
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [np.mean(prices[:period])]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def compute_macd(prices: list[float]) -> dict:
    """Compute MACD (12,26,9)."""
    if len(prices) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0}

    ema12 = compute_ema(prices, 12)
    ema26 = compute_ema(prices, 26)

    # Align EMAs
    diff = len(ema12) - len(ema26)
    ema12 = ema12[diff:]

    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_line = compute_ema(macd_line, 9) if len(macd_line) >= 9 else [0]

    return {
        "macd": macd_line[-1] if macd_line else 0,
        "signal": signal_line[-1] if signal_line else 0,
        "histogram": (macd_line[-1] - signal_line[-1]) if macd_line and signal_line else 0,
    }


def compute_bollinger_bands(prices: list[float], period: int = 20, std_dev: float = 2.0) -> dict:
    """Compute Bollinger Bands."""
    if len(prices) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "pct_b": 0.5}

    recent = prices[-period:]
    middle = np.mean(recent)
    std = np.std(recent)
    upper = middle + std_dev * std
    lower = middle - std_dev * std

    current = prices[-1]
    band_width = upper - lower
    pct_b = (current - lower) / band_width if band_width > 0 else 0.5

    return {"upper": upper, "middle": middle, "lower": lower, "pct_b": pct_b}


def compute_volume_signal(volumes: list[float], window: int = 20) -> dict:
    """Analyze volume trends."""
    if len(volumes) < window:
        return {"trend": "neutral", "ratio": 1.0}

    avg_vol = np.mean(volumes[-window:])
    recent_vol = np.mean(volumes[-3:]) if len(volumes) >= 3 else volumes[-1]
    ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0

    if ratio > 1.5:
        trend = "high"
    elif ratio < 0.5:
        trend = "low"
    else:
        trend = "neutral"

    return {"trend": trend, "ratio": round(ratio, 2)}


def generate_technical_signal(prices: list[float], volumes: list[float] = None) -> dict:
    """
    Generate a combined technical analysis signal.
    Returns: {direction: 'BUY'|'SELL'|'HOLD', strength: 0-1, reasons: [...]}
    """
    if len(prices) < 26:
        return {"direction": "HOLD", "strength": 0, "reasons": ["Insufficient price data"]}

    signals = []
    reasons = []

    # RSI
    rsi = compute_rsi(prices)
    if rsi is not None:
        if rsi < 30:
            signals.append(1.0)
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi > 70:
            signals.append(-1.0)
            reasons.append(f"RSI overbought ({rsi:.1f})")
        elif rsi < 45:
            signals.append(0.3)
            reasons.append(f"RSI leaning bullish ({rsi:.1f})")
        elif rsi > 55:
            signals.append(-0.3)
            reasons.append(f"RSI leaning bearish ({rsi:.1f})")
        else:
            signals.append(0)

    # MACD
    macd = compute_macd(prices)
    if macd["histogram"] > 0:
        signals.append(0.5 if macd["macd"] > macd["signal"] else 0.2)
        reasons.append("MACD bullish crossover" if macd["macd"] > macd["signal"] else "MACD positive")
    elif macd["histogram"] < 0:
        signals.append(-0.5 if macd["macd"] < macd["signal"] else -0.2)
        reasons.append("MACD bearish crossover" if macd["macd"] < macd["signal"] else "MACD negative")

    # Bollinger Bands
    bb = compute_bollinger_bands(prices)
    if bb["pct_b"] < 0.1:
        signals.append(0.7)
        reasons.append("Price near lower Bollinger Band (oversold)")
    elif bb["pct_b"] > 0.9:
        signals.append(-0.7)
        reasons.append("Price near upper Bollinger Band (overbought)")

    # EMA crossover (short 5 vs long 20)
    ema5 = compute_ema(prices, 5)
    ema20 = compute_ema(prices, 20)
    if ema5 and ema20:
        if ema5[-1] > ema20[-1]:
            signals.append(0.4)
            reasons.append("EMA 5 > EMA 20 (bullish trend)")
        else:
            signals.append(-0.4)
            reasons.append("EMA 5 < EMA 20 (bearish trend)")

    # Momentum (price change over last 5 periods)
    if len(prices) >= 5:
        momentum = (prices[-1] - prices[-5]) / prices[-5]
        if momentum > 0.02:
            signals.append(0.3)
            reasons.append(f"Positive momentum ({momentum:.1%})")
        elif momentum < -0.02:
            signals.append(-0.3)
            reasons.append(f"Negative momentum ({momentum:.1%})")

    if not signals:
        return {"direction": "HOLD", "strength": 0, "reasons": ["No clear signals"]}

    avg_signal = np.mean(signals)
    strength = min(abs(avg_signal), 1.0)

    if avg_signal > 0.15:
        direction = "BUY"
    elif avg_signal < -0.15:
        direction = "SELL"
    else:
        direction = "HOLD"

    return {
        "direction": direction,
        "strength": round(strength, 4),
        "avg_signal": round(avg_signal, 4),
        "reasons": reasons,
        "indicators": {
            "rsi": round(rsi, 2) if rsi else None,
            "macd": {k: round(v, 6) for k, v in macd.items()},
            "bollinger_pct_b": round(bb["pct_b"], 4),
        },
    }


def combine_signals(technical: dict, sentiment: dict, tech_weight: float = 0.6, sent_weight: float = 0.4) -> dict:
    """
    Combine technical and sentiment signals into a final trading decision.
    """
    tech_score = technical.get("avg_signal", 0) * tech_weight
    sent_score = sentiment.get("score", 0) * sent_weight
    combined = tech_score + sent_score

    strength = min(abs(combined), 1.0)
    if combined > 0.15:
        direction = "BUY"
    elif combined < -0.15:
        direction = "SELL"
    else:
        direction = "HOLD"

    confidence = (technical.get("strength", 0) + sentiment.get("confidence", 0)) / 2

    return {
        "direction": direction,
        "strength": round(strength, 4),
        "combined_score": round(combined, 4),
        "tech_score": round(tech_score, 4),
        "sent_score": round(sent_score, 4),
        "confidence": round(confidence, 4),
        "technical": technical,
        "sentiment": {
            "score": sentiment.get("score", 0),
            "tweet_count": sentiment.get("tweet_count", 0),
            "confidence": sentiment.get("confidence", 0),
        },
    }
