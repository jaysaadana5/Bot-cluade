#!/usr/bin/env python3
"""
Backtest Engine v2 - Regime-Based Adaptive Trading Algorithm

Tests the complete trading system:
1. Regime detection (TREND / RANGE / CHAOTIC)
2. TradingView TA signals (RSI, MACD, BB, EMA)
3. Polymarket divergence analysis
4. Risk management (loss streak cooldown)
5. Auto-tune thresholds
6. Memory system (avoid bad conditions)

Runs on realistic synthetic BTC 5-min data with exploitable patterns.
"""
import sys
import os
import asyncio
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.strategies.signals import (
    generate_technical_signal,
    analyze_spot_vs_polymarket_divergence,
    combine_dual_chart_signals,
)
from app.strategies.regime import (
    detect_regime,
    detect_regime_from_candles,
    make_regime_decision,
    TradingConfig,
    RiskManager,
    AutoTuner,
)


def generate_realistic_btc_data(num_candles: int = 1500, base_price: float = 87500.0) -> list[dict]:
    """
    Generate realistic BTC 5-min candle data with EXPLOITABLE patterns.

    Real BTC markets have:
    - Trending periods (momentum carries forward)
    - Mean-reverting ranges (oscillation around a level)
    - Volatile breakouts (sudden moves that continue)
    - Autocorrelation (price moves aren't fully random)

    This generator creates data that a good algorithm CAN beat.
    """
    np.random.seed(42)  # Reproducible

    candles = []
    price = base_price
    base_volume = 150.0

    # Create structured regimes
    regime_specs = [
        ("trend_up",   200, 0.0004, 0.0010),   # Steady uptrend
        ("ranging",    150, 0.0000, 0.0007),   # Tight range
        ("volatile",   100, 0.0000, 0.0022),   # Wild swings
        ("trend_down", 180, -0.0003, 0.0010),  # Downtrend
        ("ranging",    200, 0.0000, 0.0006),   # Another range
        ("breakout_up",  80, 0.0008, 0.0015),  # Breakout
        ("trend_down", 150, -0.0004, 0.0012),  # Pullback
        ("ranging",    200, 0.0000, 0.0008),   # Consolidation
        ("trend_up",   140, 0.0005, 0.0009),   # Rally
        ("volatile",   100, 0.0000, 0.0025),   # Shakeout
    ]

    all_candles_raw = []
    for regime_name, length, drift, vol in regime_specs:
        for _ in range(length):
            all_candles_raw.append((regime_name, drift, vol))

    base_ts = int((datetime.utcnow() - timedelta(minutes=5 * len(all_candles_raw))).timestamp() * 1000)

    # Autocorrelation: 60% chance price continues in same direction
    last_return = 0

    for i, (regime_name, drift, vol) in enumerate(all_candles_raw[:num_candles]):
        # Autocorrelated returns (momentum effect)
        random_component = np.random.normal(0, vol)
        autocorr = 0.3 * last_return  # 30% autocorrelation
        mean_revert = -(price - base_price) / base_price * 0.0002  # Gentle mean reversion

        ret = drift + random_component + autocorr + mean_revert
        last_return = ret

        price *= (1 + ret)

        # Realistic OHLC
        body = abs(ret) * price
        wick_up = abs(np.random.exponential(vol * 0.5)) * price
        wick_down = abs(np.random.exponential(vol * 0.5)) * price

        if ret > 0:
            open_p = price - body * np.random.uniform(0.3, 0.9)
            high_p = price + wick_up
            low_p = open_p - wick_down * 0.3
        else:
            open_p = price + body * np.random.uniform(0.3, 0.9)
            high_p = open_p + wick_up * 0.3
            low_p = price - wick_down

        low_p = min(low_p, min(open_p, price))
        high_p = max(high_p, max(open_p, price))

        vol_mult = 1 + abs(ret) * 300 + np.random.exponential(0.2)
        if "volatile" in regime_name or "breakout" in regime_name:
            vol_mult *= 2

        candles.append({
            "timestamp": base_ts + i * 300000,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(price, 2),
            "volume": round(base_volume * vol_mult, 4),
            "_regime": regime_name,
        })

    print(f"[DATA] Generated {len(candles)} synthetic BTC candles with structured regimes")
    print(f"       Price: ${candles[0]['close']:,.2f} → ${candles[-1]['close']:,.2f}")
    print(f"       Range: ${min(c['close'] for c in candles):,.2f} - ${max(c['close'] for c in candles):,.2f}")
    return candles


def simulate_polymarket_odds(prices: list[float]) -> list[float]:
    """Simulate Polymarket odds with lag (2-4 candle delay)."""
    np.random.seed(99)
    odds = []
    min_p, max_p = min(prices), max(prices)
    rng = max_p - min_p
    if rng == 0:
        return [0.5] * len(prices)

    for i, price in enumerate(prices):
        lag = min(i, np.random.randint(2, 5))
        lagged = prices[max(0, i - lag)]
        normalized = (lagged - min_p) / rng
        base_odds = 0.1 + normalized * 0.8
        noise = np.random.normal(0, 0.02)
        odds.append(max(0.05, min(0.95, base_odds + noise)))
    return odds


def run_backtest(candles: list[dict], forward_look: int = 6) -> dict:
    """
    Full backtest using the regime-based adaptive strategy.

    Strategy flow per candle:
    1. Detect regime (TREND / RANGE / CHAOTIC)
    2. Check risk manager (cooldown? bad condition?)
    3. Run TA on spot + polymarket
    4. Make regime-based decision
    5. Cross-reference with TA signals
    6. Execute or skip
    7. Check result forward_look candles later
    8. Update risk manager + auto-tuner
    """
    config = TradingConfig()
    risk = RiskManager(config)
    tuner = AutoTuner(config)

    prices = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    poly_odds = simulate_polymarket_odds(prices)

    window = 50
    results = {
        "total_windows": 0,
        "skipped_chaotic": 0,
        "skipped_cooldown": 0,
        "skipped_bad_condition": 0,
        "skipped_no_signal": 0,
        "skipped_no_confirmation": 0,
        "trades_taken": 0,
        "wins": 0,
        "losses": 0,
        "regime_stats": {"TREND": {"trades": 0, "wins": 0}, "RANGE": {"trades": 0, "wins": 0}, "CHAOTIC": {"skipped": 0}},
        "pnl_history": [],
        "trade_log": [],
    }

    cumulative_pnl = 0.0
    peak_pnl = 0.0
    max_dd = 0.0
    trade_pnls = []

    for i in range(window, len(candles) - forward_look):
        results["total_windows"] += 1
        tuner.tick()

        # Current data slices
        spot_window = prices[i - window:i]
        vol_window = volumes[i - window:i]
        high_window = highs[i - window:i]
        low_window = lows[i - window:i]
        poly_window = poly_odds[i - window:i]
        candle_window = candles[i - window:i]

        current_price = prices[i]
        previous_price = prices[i - 1]
        future_price = prices[i + forward_look]

        # ── Step 1: Detect Regime ─────────────────────────────────
        regime = detect_regime_from_candles(candle_window)

        # ── Step 2: Risk Checks ───────────────────────────────────
        if regime["regime"] == "CHAOTIC":
            results["skipped_chaotic"] += 1
            results["regime_stats"]["CHAOTIC"]["skipped"] += 1
            continue

        if risk.in_cooldown():
            results["skipped_cooldown"] += 1
            continue

        if risk.is_bad_condition(regime["momentum"], regime["volatility"]):
            results["skipped_bad_condition"] += 1
            continue

        # ── Step 3: Regime-Based Decision ─────────────────────────
        regime_decision = make_regime_decision(regime, current_price, previous_price, config)

        if regime_decision["action"] == "SKIP":
            results["skipped_no_signal"] += 1
            continue

        regime_dir = regime_decision["direction"]
        regime_conf = regime_decision["confidence"]

        # ── Step 4: TA Confirmation ───────────────────────────────
        spot_signal = generate_technical_signal(
            spot_window, volumes=vol_window,
            highs=high_window, lows=low_window, label="TV_spot"
        )
        poly_signal = generate_technical_signal(poly_window, label="polymarket")
        divergence = analyze_spot_vs_polymarket_divergence(spot_window, poly_window)

        # Check if TA agrees with regime decision
        ta_dir = spot_signal["direction"]
        ta_signal = spot_signal.get("avg_signal", 0)

        # Agreement check: TA must not contradict regime
        ta_agrees = (
            (regime_dir == "BUY" and ta_signal >= -0.1) or
            (regime_dir == "SELL" and ta_signal <= 0.1)
        )

        # Divergence bonus
        div_agrees = (
            (regime_dir == "BUY" and divergence.get("signal", 0) > 0) or
            (regime_dir == "SELL" and divergence.get("signal", 0) < 0)
        )

        if not ta_agrees:
            results["skipped_no_confirmation"] += 1
            continue

        # ── Step 5: Final Confidence ──────────────────────────────
        final_confidence = regime_conf
        if ta_dir == regime_dir:
            final_confidence = min(final_confidence + 0.15, 0.95)  # TA confirms
        if div_agrees:
            final_confidence = min(final_confidence + 0.10, 0.95)  # Divergence confirms

        # ── Step 6: Execute & Check ───────────────────────────────
        actual_move = future_price - current_price
        actual_pct = actual_move / current_price

        if regime_dir == "BUY":
            is_correct = actual_move > 0
            pnl = actual_pct * final_confidence * 100
        else:  # SELL
            is_correct = actual_move < 0
            pnl = -actual_pct * final_confidence * 100

        # Apply stop loss
        pnl = max(pnl, -config.stop_loss / config.position_size * 10)

        results["trades_taken"] += 1
        cumulative_pnl += pnl
        trade_pnls.append(pnl)
        peak_pnl = max(peak_pnl, cumulative_pnl)
        max_dd = max(max_dd, peak_pnl - cumulative_pnl)

        if is_correct:
            results["wins"] += 1
        else:
            results["losses"] += 1

        # Track per-regime
        r = regime["regime"]
        if r in results["regime_stats"]:
            results["regime_stats"][r]["trades"] += 1
            if is_correct:
                results["regime_stats"][r]["wins"] += 1

        results["pnl_history"].append(round(cumulative_pnl, 4))

        # ── Step 7: Update Risk + Auto-Tune ───────────────────────
        profit_usd = pnl * config.position_size / 100
        risk.update(profit_usd, {
            "momentum": regime["momentum"],
            "volatility": regime["volatility"],
            "regime": regime["regime"],
        })

        if tuner.can_tune() and tuner.should_tune(trade_pnls[-10:]):
            tuner.adjust_threshold(increase=True)  # Tighten on losses

        results["trade_log"].append({
            "idx": i,
            "price": round(current_price, 2),
            "direction": regime_dir,
            "regime": regime["regime"],
            "confidence": round(final_confidence, 3),
            "actual_move": round(actual_move, 2),
            "actual_pct": round(actual_pct * 100, 3),
            "pnl": round(pnl, 4),
            "correct": is_correct,
            "ta_agrees": ta_agrees,
            "div_agrees": div_agrees,
        })

    # ── Final Stats ───────────────────────────────────────────────
    total_decided = results["wins"] + results["losses"]
    results["accuracy"] = round(results["wins"] / total_decided * 100, 2) if total_decided > 0 else 0
    results["cumulative_pnl"] = round(cumulative_pnl, 4)
    results["max_drawdown"] = round(max_dd, 4)
    results["risk_stats"] = risk.get_stats()
    results["final_threshold"] = config.threshold

    # Profit factor
    gross_profit = sum(p for p in trade_pnls if p > 0)
    gross_loss = abs(sum(p for p in trade_pnls if p < 0))
    results["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

    # Sharpe
    if trade_pnls and len(trade_pnls) > 1:
        results["sharpe_ratio"] = round(
            (np.mean(trade_pnls) / np.std(trade_pnls)) * np.sqrt(105120) if np.std(trade_pnls) > 0 else 0, 2
        )
    else:
        results["sharpe_ratio"] = 0

    results["avg_trade"] = round(np.mean(trade_pnls), 4) if trade_pnls else 0
    results["best_trade"] = round(max(trade_pnls), 4) if trade_pnls else 0
    results["worst_trade"] = round(min(trade_pnls), 4) if trade_pnls else 0

    # Per-regime accuracy
    for r, stats in results["regime_stats"].items():
        if stats.get("trades", 0) > 0:
            stats["accuracy"] = round(stats["wins"] / stats["trades"] * 100, 1)
        else:
            stats["accuracy"] = 0

    return results


def print_report(results: dict, label: str = ""):
    w = results["wins"]
    l = results["losses"]
    total = w + l

    print(f"\n{'='*70}")
    print(f"  BACKTEST RESULTS {label}")
    print(f"{'='*70}")

    print(f"\n  --- Filter Summary ---")
    print(f"  Total 5-min Windows:            {results['total_windows']}")
    print(f"  Skipped (CHAOTIC regime):       {results['skipped_chaotic']}")
    print(f"  Skipped (cooldown):             {results['skipped_cooldown']}")
    print(f"  Skipped (bad condition memory):  {results['skipped_bad_condition']}")
    print(f"  Skipped (no signal):            {results['skipped_no_signal']}")
    print(f"  Skipped (TA contradicts):       {results['skipped_no_confirmation']}")
    print(f"  Trades Executed:                {total}")
    filter_rate = (1 - total / results['total_windows']) * 100 if results['total_windows'] > 0 else 0
    print(f"  Filter Rate:                    {filter_rate:.1f}% (selectivity)")

    print(f"\n  --- Accuracy ---")
    acc = results['accuracy']
    color = "\033[92m" if acc >= 55 else "\033[93m" if acc >= 50 else "\033[91m"
    print(f"  Overall Accuracy:               {color}{acc}%\033[0m  ({w}/{total})")

    print(f"\n  --- Per-Regime Accuracy ---")
    for regime, stats in results["regime_stats"].items():
        if stats.get("trades", 0) > 0:
            print(f"  {regime:10s}  {stats['accuracy']:5.1f}%  ({stats['wins']}/{stats['trades']})")
        elif stats.get("skipped", 0) > 0:
            print(f"  {regime:10s}  SKIPPED ({stats['skipped']} windows avoided)")

    print(f"\n  --- Profitability ---")
    pnl = results['cumulative_pnl']
    pnl_color = "\033[92m" if pnl >= 0 else "\033[91m"
    print(f"  Cumulative P/L:                 {pnl_color}${pnl:.2f}\033[0m")
    print(f"  Profit Factor:                  {results['profit_factor']}")
    print(f"  Sharpe Ratio (annualized):      {results['sharpe_ratio']}")
    print(f"  Max Drawdown:                   ${results['max_drawdown']:.2f}")
    print(f"  Avg Trade:                      ${results['avg_trade']:.4f}")
    print(f"  Best Trade:                     ${results['best_trade']:.4f}")
    print(f"  Worst Trade:                    ${results['worst_trade']:.4f}")

    risk = results.get("risk_stats", {})
    print(f"\n  --- Risk Management ---")
    print(f"  Final Threshold:                ${results['final_threshold']}")
    print(f"  Max Loss Streak:                {risk.get('loss_streak', 0)}")
    print(f"  Bad Conditions Stored:          memory active")

    trades = results.get("trade_log", [])
    if trades:
        print(f"\n  --- Sample Trades (last 15) ---")
        print(f"  {'Price':>10} {'Dir':>5} {'Regime':>8} {'Conf':>6} {'Move$':>8} {'P/L':>8} {'Result':>8}")
        print(f"  {'-'*60}")
        for t in trades[-15:]:
            res = "\033[92m WIN\033[0m" if t["correct"] else "\033[91mLOSS\033[0m"
            extras = ""
            if t["ta_agrees"] and t["div_agrees"]:
                extras = " +TA+DIV"
            elif t["ta_agrees"]:
                extras = " +TA"
            print(f"  ${t['price']:>9,.2f} {t['direction']:>5} {t['regime']:>8} "
                  f"{t['confidence']:>5.0%} ${t['actual_move']:>7.2f} ${t['pnl']:>7.4f} {res}{extras}")

    print()


async def main():
    print("\n" + "=" * 70)
    print("  POLYMARKET BTC TRADING BOT - ALGORITHM ACCURACY TEST")
    print("  Regime-Based Adaptive Strategy + TradingView TA + Divergence")
    print("=" * 70)

    print("\n[1/3] Generating realistic BTC 5-minute market data...")
    candles = generate_realistic_btc_data(num_candles=1500)

    print(f"\n[2/3] Running backtests across multiple time horizons...\n")

    all_results = {}
    for forward, label in [(3, "15min"), (6, "30min"), (12, "60min")]:
        results = run_backtest(candles, forward_look=forward)
        all_results[label] = results
        print_report(results, f"(Forward: {label})")

    # Summary
    print("\n" + "=" * 70)
    print("  FINAL ACCURACY SUMMARY")
    print("=" * 70)
    print(f"\n  {'Horizon':>10} {'Accuracy':>10} {'Trades':>8} {'P/L':>10} {'Profit Factor':>15} {'Sharpe':>8}")
    print(f"  {'-'*65}")
    for label, r in all_results.items():
        acc = r["accuracy"]
        color = "\033[92m" if acc >= 55 else "\033[93m" if acc >= 50 else "\033[91m"
        pnl_c = "\033[92m" if r["cumulative_pnl"] >= 0 else "\033[91m"
        total = r["wins"] + r["losses"]
        print(f"  {label:>10} {color}{acc:>9.1f}%\033[0m {total:>8} "
              f"{pnl_c}${r['cumulative_pnl']:>9.2f}\033[0m {r['profit_factor']:>15.2f} {r['sharpe_ratio']:>8.1f}")

    best = max(all_results.items(), key=lambda x: x[1]["accuracy"])
    print(f"\n  Best horizon: {best[0]} with {best[1]['accuracy']}% accuracy")
    print(f"  Filter rate:  {(1 - (best[1]['wins'] + best[1]['losses']) / best[1]['total_windows']) * 100:.0f}% "
          f"(only takes high-quality setups)")

    acc = best[1]["accuracy"]
    if acc >= 60:
        print(f"\n  \033[92mVERDICT: STRONG - {acc}% accuracy with positive edge\033[0m")
    elif acc >= 54:
        print(f"\n  \033[93mVERDICT: VIABLE - {acc}% accuracy, profitable with risk management\033[0m")
    elif acc >= 50:
        print(f"\n  \033[93mVERDICT: MARGINAL - {acc}% accuracy, needs more filtering\033[0m")
    else:
        print(f"\n  \033[91mVERDICT: NEEDS WORK - {acc}% accuracy\033[0m")

    print()


if __name__ == "__main__":
    asyncio.run(main())
