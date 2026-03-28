"""
Trading signal generators - dual-chart analysis engine.

Analyzes TWO data sources simultaneously:
1. BTC Spot (Binance 5m candles) - real BTC price action (same as TradingView)
2. Polymarket odds (5m price history) - prediction market probability

Cross-references both to find the best trade:
- If BTC spot is pumping but Polymarket odds haven't caught up → BUY opportunity
- If BTC spot is dumping but Polymarket odds are still high → SELL opportunity
- If both agree on direction → strong confirmation signal
- Divergence between spot and odds = highest alpha opportunities
"""
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── Core Indicators ───────────────────────────────────────────────────

def compute_rsi(prices: list[float], period: int = 14) -> Optional[float]:
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
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [np.mean(prices[:period])]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def compute_macd(prices: list[float]) -> dict:
    if len(prices) < 26:
        return {"macd": 0, "signal": 0, "histogram": 0}
    ema12 = compute_ema(prices, 12)
    ema26 = compute_ema(prices, 26)
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


def compute_vwap(prices: list[float], volumes: list[float]) -> Optional[float]:
    """Volume Weighted Average Price."""
    if len(prices) < 2 or len(volumes) < 2:
        return None
    n = min(len(prices), len(volumes))
    prices = prices[-n:]
    volumes = volumes[-n:]
    total_vol = sum(volumes)
    if total_vol == 0:
        return None
    return sum(p * v for p, v in zip(prices, volumes)) / total_vol


def compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    """Average True Range - measures volatility."""
    if len(highs) < period + 1:
        return None
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return np.mean(trs[-period:])


def compute_stoch_rsi(prices: list[float], period: int = 14) -> Optional[dict]:
    """Stochastic RSI - momentum oscillator."""
    if len(prices) < period + 14:
        return None
    rsi_values = []
    for i in range(period, len(prices)):
        rsi = compute_rsi(prices[:i + 1], period)
        if rsi is not None:
            rsi_values.append(rsi)

    if len(rsi_values) < 14:
        return None

    recent = rsi_values[-14:]
    min_rsi = min(recent)
    max_rsi = max(recent)
    rng = max_rsi - min_rsi

    if rng == 0:
        return {"k": 50, "d": 50}

    k = ((rsi_values[-1] - min_rsi) / rng) * 100
    d = np.mean([((r - min_rsi) / rng) * 100 for r in rsi_values[-3:]])
    return {"k": round(k, 2), "d": round(d, 2)}


# ── Single Chart TA ───────────────────────────────────────────────────

def generate_technical_signal(prices: list[float], volumes: list[float] = None,
                              highs: list[float] = None, lows: list[float] = None,
                              label: str = "spot") -> dict:
    """
    Full TA on a single price series.
    Uses a CONFIRMATION-BASED approach: only trades when multiple
    indicators agree. Single indicators are not enough.
    """
    if len(prices) < 30:
        return {"direction": "HOLD", "strength": 0, "avg_signal": 0,
                "reasons": [f"[{label}] Insufficient data ({len(prices)} points)"],
                "indicators": {}, "label": label}

    bullish_confirmations = 0
    bearish_confirmations = 0
    signals = []
    reasons = []

    # ── 1. RSI (only extreme zones count as confirmation) ─────────
    rsi = compute_rsi(prices)
    if rsi is not None:
        if rsi < 25:
            bullish_confirmations += 1
            signals.append(0.8)
            reasons.append(f"[{label}] RSI strongly oversold ({rsi:.1f})")
        elif rsi > 75:
            bearish_confirmations += 1
            signals.append(-0.8)
            reasons.append(f"[{label}] RSI strongly overbought ({rsi:.1f})")
        elif rsi < 35:
            signals.append(0.3)
            reasons.append(f"[{label}] RSI oversold zone ({rsi:.1f})")
        elif rsi > 65:
            signals.append(-0.3)
            reasons.append(f"[{label}] RSI overbought zone ({rsi:.1f})")

    # ── 2. MACD (only fresh crossovers count) ─────────────────────
    macd = compute_macd(prices)
    macd_prev = compute_macd(prices[:-1]) if len(prices) > 27 else {"histogram": 0}

    # Fresh crossover = histogram changed sign
    fresh_bull_cross = macd["histogram"] > 0 and macd_prev.get("histogram", 0) <= 0
    fresh_bear_cross = macd["histogram"] < 0 and macd_prev.get("histogram", 0) >= 0

    if fresh_bull_cross:
        bullish_confirmations += 1
        signals.append(0.7)
        reasons.append(f"[{label}] MACD fresh bullish crossover")
    elif fresh_bear_cross:
        bearish_confirmations += 1
        signals.append(-0.7)
        reasons.append(f"[{label}] MACD fresh bearish crossover")
    elif macd["histogram"] > 0 and macd["macd"] > 0:
        signals.append(0.2)
    elif macd["histogram"] < 0 and macd["macd"] < 0:
        signals.append(-0.2)

    # ── 3. Bollinger Bands (only extreme + reversal) ──────────────
    bb = compute_bollinger_bands(prices)
    if bb["pct_b"] < 0.05:
        # At lower band AND price starting to bounce
        if len(prices) >= 3 and prices[-1] > prices[-2]:
            bullish_confirmations += 1
            signals.append(0.8)
            reasons.append(f"[{label}] BB lower band bounce (pct_b={bb['pct_b']:.2f})")
        else:
            signals.append(0.3)
            reasons.append(f"[{label}] At lower BB, waiting for bounce")
    elif bb["pct_b"] > 0.95:
        if len(prices) >= 3 and prices[-1] < prices[-2]:
            bearish_confirmations += 1
            signals.append(-0.8)
            reasons.append(f"[{label}] BB upper band rejection (pct_b={bb['pct_b']:.2f})")
        else:
            signals.append(-0.3)
            reasons.append(f"[{label}] At upper BB, waiting for rejection")

    # ── 4. EMA crossover (trend direction) ────────────────────────
    ema5 = compute_ema(prices, 5)
    ema20 = compute_ema(prices, 20)
    ema_trend = None
    if ema5 and ema20 and len(ema5) >= 2 and len(ema20) >= 2:
        # Fresh crossover
        curr_above = ema5[-1] > ema20[-1]
        prev_above = ema5[-2] > ema20[-2]
        if curr_above and not prev_above:
            bullish_confirmations += 1
            signals.append(0.6)
            ema_trend = "bullish_cross"
            reasons.append(f"[{label}] EMA 5/20 bullish crossover")
        elif not curr_above and prev_above:
            bearish_confirmations += 1
            signals.append(-0.6)
            ema_trend = "bearish_cross"
            reasons.append(f"[{label}] EMA 5/20 bearish crossover")
        elif curr_above:
            signals.append(0.15)
            ema_trend = "bullish"
        else:
            signals.append(-0.15)
            ema_trend = "bearish"

    # ── 5. Momentum (strong moves only) ───────────────────────────
    if len(prices) >= 10:
        mom_5 = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] != 0 else 0
        mom_10 = (prices[-1] - prices[-10]) / prices[-10] if prices[-10] != 0 else 0

        # Only strong momentum counts
        if mom_5 > 0.003 and mom_10 > 0.005:
            bullish_confirmations += 1
            signals.append(0.5)
            reasons.append(f"[{label}] Strong upward momentum ({mom_5:.2%}/{mom_10:.2%})")
        elif mom_5 < -0.003 and mom_10 < -0.005:
            bearish_confirmations += 1
            signals.append(-0.5)
            reasons.append(f"[{label}] Strong downward momentum ({mom_5:.2%}/{mom_10:.2%})")

    # ── 6. Stochastic RSI ─────────────────────────────────────────
    stoch = compute_stoch_rsi(prices)
    if stoch:
        if stoch["k"] < 15 and stoch["d"] < 20:
            bullish_confirmations += 1
            signals.append(0.5)
            reasons.append(f"[{label}] StochRSI deeply oversold (K={stoch['k']:.0f})")
        elif stoch["k"] > 85 and stoch["d"] > 80:
            bearish_confirmations += 1
            signals.append(-0.5)
            reasons.append(f"[{label}] StochRSI deeply overbought (K={stoch['k']:.0f})")

    # ── 7. Volume confirmation ────────────────────────────────────
    vol_confirmed = False
    if volumes and len(volumes) >= 20:
        avg_vol = np.mean(volumes[-20:])
        recent_vol = np.mean(volumes[-3:])
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio > 1.5:
            vol_confirmed = True
            if len(signals) > 0:
                dir_so_far = 1 if np.mean(signals) > 0 else -1
                signals.append(dir_so_far * 0.3)
                reasons.append(f"[{label}] Volume confirms ({vol_ratio:.1f}x avg)")

    # ── 8. VWAP ───────────────────────────────────────────────────
    if volumes and len(volumes) >= 10:
        vwap = compute_vwap(prices, volumes)
        if vwap and prices[-1] > vwap * 1.003:
            signals.append(0.15)
        elif vwap and prices[-1] < vwap * 0.997:
            signals.append(-0.15)

    # ATR
    atr = None
    if highs and lows and len(highs) >= 15:
        atr = compute_atr(highs, lows, prices)

    # ── DECISION: Require MULTIPLE confirmations ──────────────────
    if not signals:
        return {"direction": "HOLD", "strength": 0, "avg_signal": 0,
                "reasons": [f"[{label}] No signals"], "indicators": {}, "label": label}

    avg_signal = float(np.mean(signals))
    strength = min(abs(avg_signal), 1.0)

    # KEY FILTER: Require at least 2 confirmations to trade
    min_confirmations = 2

    if bullish_confirmations >= min_confirmations and avg_signal > 0.1:
        direction = "BUY"
        # Boost strength based on number of confirmations
        strength = min(strength * (1 + (bullish_confirmations - 2) * 0.2), 1.0)
    elif bearish_confirmations >= min_confirmations and avg_signal < -0.1:
        direction = "SELL"
        strength = min(strength * (1 + (bearish_confirmations - 2) * 0.2), 1.0)
    else:
        direction = "HOLD"
        reasons.append(f"[{label}] Insufficient confirmations (bull={bullish_confirmations}, bear={bearish_confirmations}, need={min_confirmations})")

    return {
        "direction": direction,
        "strength": round(strength, 4),
        "avg_signal": round(avg_signal, 4),
        "reasons": reasons,
        "label": label,
        "confirmations": {"bullish": bullish_confirmations, "bearish": bearish_confirmations},
        "indicators": {
            "rsi": round(rsi, 2) if rsi else None,
            "macd": {k: round(v, 6) for k, v in macd.items()},
            "macd_fresh_cross": fresh_bull_cross or fresh_bear_cross,
            "bollinger_pct_b": round(bb["pct_b"], 4),
            "ema_trend": ema_trend,
            "stoch_rsi": stoch,
            "atr": round(atr, 2) if atr else None,
            "volume_confirmed": vol_confirmed,
        },
    }


# ── Dual-Chart Analysis ──────────────────────────────────────────────

def analyze_spot_vs_polymarket_divergence(
    spot_prices: list[float],
    poly_prices: list[float],
    lookback: int = 20,
) -> dict:
    """
    Detect divergence between BTC spot price trend and Polymarket odds trend.

    Divergence = highest-alpha signal:
    - Spot rising + Poly flat/falling = Poly hasn't priced in the move → BUY poly
    - Spot falling + Poly flat/rising = Poly is overpriced → SELL poly
    - Both moving same direction = confirmation (lower alpha but safer)
    """
    if len(spot_prices) < lookback or len(poly_prices) < lookback:
        return {"divergence": 0, "type": "insufficient_data", "signal": 0, "reason": "Not enough data"}

    # Normalize both to percentage change over lookback
    spot_recent = spot_prices[-lookback:]
    poly_recent = poly_prices[-lookback:]

    spot_change = (spot_recent[-1] - spot_recent[0]) / spot_recent[0] if spot_recent[0] != 0 else 0
    poly_change = (poly_recent[-1] - poly_recent[0]) / poly_recent[0] if poly_recent[0] != 0 else 0

    # Also check short-term (last 5 candles)
    spot_short = spot_prices[-5:]
    poly_short = poly_prices[-5:]
    spot_short_change = (spot_short[-1] - spot_short[0]) / spot_short[0] if spot_short[0] != 0 else 0
    poly_short_change = (poly_short[-1] - poly_short[0]) / poly_short[0] if poly_short[0] != 0 else 0

    # Correlation between the two series
    if len(spot_recent) == len(poly_recent):
        spot_norm = np.array(spot_recent) / spot_recent[0]
        poly_norm = np.array(poly_recent) / poly_recent[0]
        correlation = float(np.corrcoef(spot_norm, poly_norm)[0, 1]) if len(spot_norm) > 1 else 0
    else:
        correlation = 0

    # Detect divergence - use BOTH medium-term and short-term
    divergence_score = 0
    div_type = "none"
    reason = ""

    # Medium-term divergence (higher confidence)
    if spot_change > 0.004 and poly_change < spot_change * 0.3:
        divergence_score = min(abs(spot_change - poly_change) * 15, 1.0)
        div_type = "bullish_divergence"
        reason = f"BTC spot up {spot_change:.2%}, Poly lagging {poly_change:.2%} → BUY"

    elif spot_change < -0.004 and poly_change > spot_change * 0.3:
        divergence_score = min(abs(poly_change - spot_change) * 15, 1.0)
        div_type = "bearish_divergence"
        reason = f"BTC spot down {spot_change:.2%}, Poly lagging {poly_change:.2%} → SELL"

    # Short-term divergence (faster signal, lower confidence)
    elif spot_short_change > 0.003 and poly_short_change < spot_short_change * 0.2:
        divergence_score = min(abs(spot_short_change - poly_short_change) * 20, 0.7)
        div_type = "bullish_divergence_fast"
        reason = f"Short-term: spot up {spot_short_change:.2%}, Poly flat {poly_short_change:.2%} → BUY"

    elif spot_short_change < -0.003 and poly_short_change > spot_short_change * 0.2:
        divergence_score = min(abs(poly_short_change - spot_short_change) * 20, 0.7)
        div_type = "bearish_divergence_fast"
        reason = f"Short-term: spot down {spot_short_change:.2%}, Poly flat {poly_short_change:.2%} → SELL"

    # Both moving same direction = confirmation (only if strong)
    elif spot_change > 0.005 and poly_change > 0.003:
        divergence_score = 0
        div_type = "bullish_confirmation"
        reason = f"Both spot ({spot_change:.2%}) & Poly ({poly_change:.2%}) bullish → CONFIRMED"

    elif spot_change < -0.005 and poly_change < -0.003:
        divergence_score = 0
        div_type = "bearish_confirmation"
        reason = f"Both spot ({spot_change:.2%}) & Poly ({poly_change:.2%}) bearish → CONFIRMED"

    # Short-term divergence metric
    short_div = spot_short_change - poly_short_change

    signal = 0
    if "bullish_divergence" in div_type:
        signal = min(divergence_score * 0.9, 0.9)
    elif "bearish_divergence" in div_type:
        signal = -min(divergence_score * 0.9, 0.9)
    elif div_type == "bullish_confirmation":
        signal = 0.5
    elif div_type == "bearish_confirmation":
        signal = -0.5

    return {
        "divergence": round(divergence_score, 4),
        "type": div_type,
        "signal": round(signal, 4),
        "reason": reason,
        "spot_change": round(spot_change, 6),
        "poly_change": round(poly_change, 6),
        "spot_short_change": round(spot_short_change, 6),
        "poly_short_change": round(poly_short_change, 6),
        "short_divergence": round(short_div, 6),
        "correlation": round(correlation, 4),
    }


def analyze_order_flow_signal(order_flow: dict) -> dict:
    """Convert BTC order flow data into a trading signal."""
    buy_ratio = order_flow.get("buy_ratio", 0.5)
    net_flow = order_flow.get("net_flow", 0)
    whale_bias = order_flow.get("whale_bias", "neutral")

    signal = 0
    reasons = []

    # Net buy/sell flow
    if buy_ratio > 0.6:
        signal += 0.4
        reasons.append(f"Strong buy flow ({buy_ratio:.0%} buys)")
    elif buy_ratio > 0.55:
        signal += 0.2
        reasons.append(f"Moderate buy flow ({buy_ratio:.0%} buys)")
    elif buy_ratio < 0.4:
        signal -= 0.4
        reasons.append(f"Strong sell flow ({buy_ratio:.0%} buys)")
    elif buy_ratio < 0.45:
        signal -= 0.2
        reasons.append(f"Moderate sell flow ({buy_ratio:.0%} buys)")

    # Whale activity
    if whale_bias == "bullish":
        signal += 0.3
        reasons.append(f"Whale bias bullish ({order_flow.get('large_buys', 0)} large buys)")
    elif whale_bias == "bearish":
        signal -= 0.3
        reasons.append(f"Whale bias bearish ({order_flow.get('large_sells', 0)} large sells)")

    return {
        "signal": round(max(-1, min(1, signal)), 4),
        "reasons": reasons,
        "buy_ratio": buy_ratio,
        "whale_bias": whale_bias,
    }


def analyze_book_pressure(book_data: dict) -> dict:
    """Convert order book depth into a signal."""
    buy_pressure = book_data.get("buy_pressure", 0.5)
    signal = (buy_pressure - 0.5) * 2  # -1 to 1

    reason = ""
    if buy_pressure > 0.6:
        reason = f"Order book buy-heavy ({buy_pressure:.0%} bids)"
    elif buy_pressure < 0.4:
        reason = f"Order book sell-heavy ({buy_pressure:.0%} bids)"
    else:
        reason = "Order book balanced"

    return {
        "signal": round(max(-1, min(1, signal)), 4),
        "reason": reason,
        "buy_pressure": buy_pressure,
    }


# ── Master Signal Combiner ───────────────────────────────────────────

def combine_dual_chart_signals(
    spot_signal: dict,
    poly_signal: dict,
    divergence: dict,
    sentiment: dict,
    order_flow: dict = None,
    book_pressure: dict = None,
) -> dict:
    """
    Master signal combiner - fuses all data sources:

    Weights:
    - BTC Spot TA (TradingView):  30%  → Real price action
    - Polymarket TA:              20%  → Market odds movement
    - Spot/Poly Divergence:       25%  → Highest alpha signal
    - X Sentiment:                10%  → Social signal
    - Order Flow:                 10%  → Buy/sell pressure
    - Book Pressure:               5%  → Order book imbalance
    """
    weights = {
        "spot_ta": 0.30,
        "poly_ta": 0.20,
        "divergence": 0.25,
        "sentiment": 0.10,
        "order_flow": 0.10,
        "book_pressure": 0.05,
    }

    scores = {}
    all_reasons = []

    # 1. Spot TA
    spot_score = spot_signal.get("avg_signal", 0)
    scores["spot_ta"] = spot_score * weights["spot_ta"]
    all_reasons.extend(spot_signal.get("reasons", []))

    # 2. Polymarket TA
    poly_score = poly_signal.get("avg_signal", 0)
    scores["poly_ta"] = poly_score * weights["poly_ta"]
    all_reasons.extend(poly_signal.get("reasons", []))

    # 3. Divergence (the money-maker)
    div_score = divergence.get("signal", 0)
    scores["divergence"] = div_score * weights["divergence"]
    if divergence.get("reason"):
        all_reasons.append(f"[DIVERGENCE] {divergence['reason']}")

    # 4. Sentiment
    sent_score = sentiment.get("score", 0)
    scores["sentiment"] = sent_score * weights["sentiment"]

    # 5. Order flow
    if order_flow:
        flow_score = order_flow.get("signal", 0)
        scores["order_flow"] = flow_score * weights["order_flow"]
        all_reasons.extend([f"[FLOW] {r}" for r in order_flow.get("reasons", [])])
    else:
        scores["order_flow"] = 0

    # 6. Book pressure
    if book_pressure:
        book_score = book_pressure.get("signal", 0)
        scores["book_pressure"] = book_score * weights["book_pressure"]
        if book_pressure.get("reason"):
            all_reasons.append(f"[BOOK] {book_pressure['reason']}")
    else:
        scores["book_pressure"] = 0

    # Combined score
    combined = sum(scores.values())
    strength = min(abs(combined), 1.0)

    # Determine direction - require higher threshold
    if combined > 0.15:
        direction = "BUY"
    elif combined < -0.15:
        direction = "SELL"
    else:
        direction = "HOLD"

    # Agreement scoring across all sources
    source_directions = []
    if spot_score > 0.1: source_directions.append(1)
    elif spot_score < -0.1: source_directions.append(-1)
    else: source_directions.append(0)

    if poly_score > 0.1: source_directions.append(1)
    elif poly_score < -0.1: source_directions.append(-1)
    else: source_directions.append(0)

    if div_score > 0.1: source_directions.append(1)
    elif div_score < -0.1: source_directions.append(-1)
    else: source_directions.append(0)

    if sent_score > 0.1: source_directions.append(1)
    elif sent_score < -0.1: source_directions.append(-1)
    else: source_directions.append(0)

    # Count how many sources agree on the direction
    bullish_sources = sum(1 for s in source_directions if s > 0)
    bearish_sources = sum(1 for s in source_directions if s < 0)
    active_sources = sum(1 for s in source_directions if s != 0)

    if active_sources > 0:
        agreement = max(bullish_sources, bearish_sources) / active_sources
    else:
        agreement = 0

    confidence = (strength * 0.4 + agreement * 0.6)

    # KEY FILTER: Override to HOLD if sources disagree
    # At least 2 sources must point same direction
    if direction == "BUY" and bullish_sources < 2:
        direction = "HOLD"
        all_reasons.append("[FILTER] BUY cancelled - insufficient source agreement")
    elif direction == "SELL" and bearish_sources < 2:
        direction = "HOLD"
        all_reasons.append("[FILTER] SELL cancelled - insufficient source agreement")

    # Boost confidence if divergence is strong (that's our edge)
    if abs(div_score) > 0.3:
        confidence = min(confidence * 1.3, 1.0)

    # Spot TA confirmations carry weight
    spot_confs = spot_signal.get("confirmations", {})
    if direction == "BUY" and spot_confs.get("bullish", 0) >= 2:
        confidence = min(confidence * 1.2, 1.0)
    elif direction == "SELL" and spot_confs.get("bearish", 0) >= 2:
        confidence = min(confidence * 1.2, 1.0)

    return {
        "direction": direction,
        "strength": round(strength, 4),
        "combined_score": round(combined, 4),
        "confidence": round(confidence, 4),
        "agreement": round(agreement, 4),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "spot_ta": spot_signal,
        "poly_ta": poly_signal,
        "divergence": divergence,
        "sentiment": {
            "score": sentiment.get("score", 0),
            "tweet_count": sentiment.get("tweet_count", 0),
            "confidence": sentiment.get("confidence", 0),
        },
        "order_flow": order_flow,
        "book_pressure": book_pressure,
        "reasons": all_reasons,
    }


# ── Legacy wrapper for backward compat ───────────────────────────────

def combine_signals(technical: dict, sentiment: dict, tech_weight: float = 0.6, sent_weight: float = 0.4) -> dict:
    """Legacy combiner - used when only single chart data is available."""
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
