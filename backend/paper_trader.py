#!/usr/bin/env python3
"""
Paper Trading Simulator - Runs the bot in real-time simulation mode.

Simulates a FULL 24-hour trading session with:
- Realistic BTC 5-min candles with trends, ranges, volatility shifts
- Simulated Polymarket odds that lag spot price
- Full regime detection + TA confirmation + divergence analysis
- Risk management: 3-loss cooldown, bad condition memory, auto-tune
- Position tracking: open/close trades, P/L per trade
- Detailed logging of every cycle + decision

This validates the algorithm works correctly before live deployment.
"""
import sys
import os
import time
import json
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.strategies.signals import (
    generate_technical_signal,
    analyze_spot_vs_polymarket_divergence,
    combine_dual_chart_signals,
)
from app.strategies.regime import (
    detect_regime_from_candles,
    make_regime_decision,
    TradingConfig,
    RiskManager,
    AutoTuner,
)


# ══════════════════════════════════════════════════════════════════════
#  MARKET DATA SIMULATOR (replaces live API in paper mode)
# ══════════════════════════════════════════════════════════════════════

class MarketSimulator:
    """
    Generates a realistic BTC price stream tick-by-tick.
    Simulates a full 24-hour trading day with different market phases.
    """

    def __init__(self, seed: int = 123):
        np.random.seed(seed)
        self.price = 87500.0
        self.candle_history = []
        self.poly_odds_history = []
        self.tick = 0
        self.last_return = 0

        # Build a 24h market schedule
        # Each phase: (name, duration_candles, drift, volatility)
        self.phases = [
            ("ASIA_SESSION_RANGE",    36,  0.00000, 0.0007),  # 3h range
            ("LONDON_OPEN_TREND_UP",  24,  0.00050, 0.0012),  # 2h trend
            ("CONSOLIDATION",         18,  0.00000, 0.0005),  # 1.5h tight range
            ("NEWS_SPIKE_UP",          6,  0.00200, 0.0030),  # 30m volatile spike
            ("PULLBACK",              12, -0.00030, 0.0015),  # 1h pullback
            ("US_OPEN_TREND_UP",      30,  0.00040, 0.0010),  # 2.5h trend
            ("MIDDAY_CHOP",           24,  0.00000, 0.0020),  # 2h chaotic
            ("AFTERNOON_TREND_DN",    24, -0.00035, 0.0011),  # 2h downtrend
            ("RECOVERY_RANGE",        18,  0.00010, 0.0008),  # 1.5h range
            ("EVENING_TREND_UP",      18,  0.00030, 0.0009),  # 1.5h trend
            ("OVERNIGHT_QUIET",       36,  0.00005, 0.0004),  # 3h quiet
            ("LATE_VOLATILITY",       12,  0.00000, 0.0025),  # 1h volatile
            ("END_OF_DAY_FADE",       30, -0.00010, 0.0006),  # 2.5h fade
        ]

        self.schedule = []
        for name, duration, drift, vol in self.phases:
            self.schedule.extend([(name, drift, vol)] * duration)

        self.total_candles = len(self.schedule)

    def next_candle(self) -> dict:
        """Generate the next 5-minute candle."""
        if self.tick >= self.total_candles:
            return None

        phase_name, drift, vol = self.schedule[self.tick]

        # Autocorrelated return (momentum effect)
        random_comp = np.random.normal(0, vol)
        autocorr = 0.25 * self.last_return
        mean_revert = -(self.price - 87500) / 87500 * 0.00015
        ret = drift + random_comp + autocorr + mean_revert
        self.last_return = ret

        prev_price = self.price
        self.price *= (1 + ret)

        # Build OHLC
        body = abs(ret) * self.price
        wick_u = abs(np.random.exponential(vol * 0.4)) * self.price
        wick_d = abs(np.random.exponential(vol * 0.4)) * self.price

        if ret > 0:
            o = prev_price
            c = self.price
            h = max(o, c) + wick_u
            l = min(o, c) - wick_d * 0.3
        else:
            o = prev_price
            c = self.price
            h = max(o, c) + wick_u * 0.3
            l = min(o, c) - wick_d

        l = min(l, min(o, c))
        h = max(h, max(o, c))

        vol_mult = 1 + abs(ret) * 300 + np.random.exponential(0.2)
        volume = 150.0 * vol_mult

        candle = {
            "timestamp": int((datetime.utcnow() - timedelta(minutes=5 * (self.total_candles - self.tick))).timestamp() * 1000),
            "time_str": (datetime.utcnow() - timedelta(minutes=5 * (self.total_candles - self.tick))).strftime("%H:%M"),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": round(volume, 2),
            "_phase": phase_name,
        }
        self.candle_history.append(candle)

        # Simulate Polymarket odds (lagged)
        min_p = min(cc["close"] for cc in self.candle_history[-50:]) if len(self.candle_history) > 5 else self.price - 500
        max_p = max(cc["close"] for cc in self.candle_history[-50:]) if len(self.candle_history) > 5 else self.price + 500
        rng = max_p - min_p
        if rng > 0:
            lag = min(self.tick, np.random.randint(2, 5))
            lagged_idx = max(0, len(self.candle_history) - 1 - lag)
            lagged_p = self.candle_history[lagged_idx]["close"]
            odds = 0.1 + ((lagged_p - min_p) / rng) * 0.8 + np.random.normal(0, 0.015)
            odds = max(0.05, min(0.95, odds))
        else:
            odds = 0.5
        self.poly_odds_history.append(odds)

        self.tick += 1
        return candle


# ══════════════════════════════════════════════════════════════════════
#  PAPER TRADING ENGINE
# ══════════════════════════════════════════════════════════════════════

class PaperTrader:
    def __init__(self, starting_balance: float = 1000.0):
        self.config = TradingConfig()
        self.config.position_size = 50  # $50 per trade for paper
        self.risk = RiskManager(self.config)
        self.tuner = AutoTuner(self.config)

        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.open_positions = []
        self.closed_trades = []
        self.cycle_log = []

    def run_session(self, market: MarketSimulator):
        """Run a full paper trading session."""
        window = 50  # Need 50 candles of history before trading

        print(f"\n{'═'*74}")
        print(f"  PAPER TRADING SESSION")
        print(f"  Starting Balance: ${self.starting_balance:,.2f}")
        print(f"  Position Size:    ${self.config.position_size}")
        print(f"  Threshold:        ${self.config.threshold}")
        print(f"  Stop Loss:        ${self.config.stop_loss}")
        print(f"{'═'*74}\n")

        # Warm up: collect initial candles
        print(f"  [WARMUP] Collecting {window} candles of history...")
        for _ in range(window):
            candle = market.next_candle()
            if candle is None:
                print("  [ERROR] Not enough data")
                return

        print(f"  [WARMUP] Done. BTC price: ${market.price:,.2f}")
        print(f"  [START]  Paper trading begins.\n")

        header = (f"  {'Time':>5} │ {'Price':>10} │ {'Phase':>20} │ {'Regime':>8} │ "
                  f"{'Action':>6} │ {'Dir':>4} │ {'Conf':>5} │ {'P/L':>8} │ {'Bal':>10} │ Reason")
        print(header)
        print(f"  {'─'*145}")

        trade_count = 0

        while True:
            candle = market.next_candle()
            if candle is None:
                break

            self.tuner.tick()
            idx = len(market.candle_history)
            candle_window = market.candle_history[-window:]
            prices = [c["close"] for c in candle_window]
            volumes = [c["volume"] for c in candle_window]
            highs = [c["high"] for c in candle_window]
            lows = [c["low"] for c in candle_window]
            poly_window = market.poly_odds_history[-window:]

            current_price = candle["close"]
            prev_price = market.candle_history[-2]["close"]
            phase = candle.get("_phase", "")

            # ── Check open positions for close ────────────────────
            self._check_positions(current_price)

            # ── Step 1: Regime Detection ──────────────────────────
            regime = detect_regime_from_candles(candle_window)

            # ── Step 2: Risk Checks ───────────────────────────────
            action = "SKIP"
            direction = "---"
            confidence = 0
            reason = ""
            pnl_str = ""

            if regime["regime"] == "CHAOTIC":
                reason = "CHAOTIC - sitting out"
            elif self.risk.in_cooldown():
                reason = f"COOLDOWN (streak={self.risk.loss_streak})"
            elif self.risk.is_bad_condition(regime["momentum"], regime["volatility"]):
                reason = "BAD CONDITION (memory)"
            else:
                # ── Step 3: Regime Decision ───────────────────────
                decision = make_regime_decision(regime, current_price, prev_price, self.config)

                if decision["action"] == "SKIP":
                    reason = decision["reason"][:60]
                else:
                    # ── Step 4: TA Confirmation ───────────────────
                    spot_signal = generate_technical_signal(
                        prices, volumes=volumes, highs=highs, lows=lows, label="spot"
                    )
                    poly_signal = generate_technical_signal(poly_window, label="poly")
                    divergence = analyze_spot_vs_polymarket_divergence(prices, poly_window)

                    ta_signal = spot_signal.get("avg_signal", 0)
                    regime_dir = decision["direction"]

                    ta_agrees = (
                        (regime_dir == "BUY" and ta_signal >= -0.1) or
                        (regime_dir == "SELL" and ta_signal <= 0.1)
                    )

                    if not ta_agrees:
                        reason = f"TA contradicts ({regime_dir} vs ta={ta_signal:.2f})"
                    else:
                        # ── Step 5: Execute Paper Trade ───────────
                        conf = decision["confidence"]
                        div_agrees = (
                            (regime_dir == "BUY" and divergence.get("signal", 0) > 0) or
                            (regime_dir == "SELL" and divergence.get("signal", 0) < 0)
                        )
                        if spot_signal["direction"] == regime_dir:
                            conf = min(conf + 0.15, 0.95)
                        if div_agrees:
                            conf = min(conf + 0.10, 0.95)

                        action = "TRADE"
                        direction = regime_dir
                        confidence = conf
                        reason = decision["reason"][:60]

                        # Open position
                        pos = {
                            "entry_price": current_price,
                            "direction": regime_dir,
                            "size": self.config.position_size * conf,
                            "confidence": conf,
                            "entry_time": candle["time_str"],
                            "entry_idx": idx,
                            "stop_loss": self.config.stop_loss,
                            "take_profit": self.config.stop_loss * 2,
                            "regime": regime["regime"],
                            "momentum": regime["momentum"],
                            "volatility": regime["volatility"],
                        }
                        self.open_positions.append(pos)
                        trade_count += 1

            # ── Print cycle row ───────────────────────────────────
            # Only print when something happens (trade, close, or regime change)
            if action == "TRADE" or (idx % 12 == 0):
                action_color = "\033[92m" if action == "TRADE" else "\033[90m"
                dir_color = "\033[92m" if direction == "BUY" else "\033[91m" if direction == "SELL" else "\033[90m"
                regime_color = (
                    "\033[96m" if regime["regime"] == "TREND"
                    else "\033[93m" if regime["regime"] == "RANGE"
                    else "\033[91m" if regime["regime"] == "CHAOTIC"
                    else "\033[90m"
                )

                print(
                    f"  {candle['time_str']:>5} │ "
                    f"${current_price:>9,.2f} │ "
                    f"{phase:>20} │ "
                    f"{regime_color}{regime['regime']:>8}\033[0m │ "
                    f"{action_color}{action:>6}\033[0m │ "
                    f"{dir_color}{direction:>4}\033[0m │ "
                    f"{confidence:>4.0%} │ "
                    f"{'':>8} │ "
                    f"${self.balance:>9,.2f} │ "
                    f"{reason[:55]}"
                )

        # Close any remaining open positions
        final_price = market.candle_history[-1]["close"]
        self._close_all_positions(final_price, "SESSION_END")

        # Final report
        self._print_report(market)

    def _check_positions(self, current_price: float):
        """Check open positions for stop loss / take profit / time-based exit."""
        still_open = []
        for pos in self.open_positions:
            entry = pos["entry_price"]
            direction = pos["direction"]
            size = pos["size"]

            if direction == "BUY":
                pnl_pct = (current_price - entry) / entry
            else:
                pnl_pct = (entry - current_price) / entry

            pnl_usd = pnl_pct * size

            # Check stop loss
            if pnl_usd <= -pos["stop_loss"]:
                self._close_position(pos, current_price, pnl_usd, "STOP_LOSS")
                continue

            # Check take profit
            if pnl_usd >= pos["take_profit"]:
                self._close_position(pos, current_price, pnl_usd, "TAKE_PROFIT")
                continue

            # Time-based exit: close after 6 candles (30 min)
            candle_age = self.tuner.current_cycle - pos.get("entry_cycle", self.tuner.current_cycle - 1)
            if candle_age is None:
                pos["entry_cycle"] = self.tuner.current_cycle
            elif self.tuner.current_cycle - pos.get("entry_cycle", self.tuner.current_cycle) >= 6:
                self._close_position(pos, current_price, pnl_usd, "TIME_EXIT")
                continue

            pos.setdefault("entry_cycle", self.tuner.current_cycle)
            still_open.append(pos)

        self.open_positions = still_open

    def _close_position(self, pos: dict, exit_price: float, pnl_usd: float, reason: str):
        """Close a position and update stats."""
        self.balance += pnl_usd
        self.risk.update(pnl_usd, {
            "momentum": pos.get("momentum", 0),
            "volatility": pos.get("volatility", 0),
            "regime": pos.get("regime", ""),
        })

        trade = {
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "direction": pos["direction"],
            "size": pos["size"],
            "pnl": round(pnl_usd, 2),
            "pnl_pct": round((exit_price - pos["entry_price"]) / pos["entry_price"] * 100, 3),
            "confidence": pos["confidence"],
            "regime": pos.get("regime", ""),
            "entry_time": pos.get("entry_time", ""),
            "exit_reason": reason,
            "win": pnl_usd > 0,
        }
        self.closed_trades.append(trade)

        result_color = "\033[92m" if pnl_usd > 0 else "\033[91m"
        print(
            f"  {'':>5} │ ${exit_price:>9,.2f} │ "
            f"{'>>> CLOSE TRADE':>20} │ {'':>8} │ "
            f"{'CLOSE':>6} │ {pos['direction']:>4} │ "
            f"{'':>5} │ "
            f"{result_color}${pnl_usd:>+7.2f}\033[0m │ "
            f"${self.balance:>9,.2f} │ "
            f"{reason} (entry ${pos['entry_price']:,.2f})"
        )

        # Auto-tune check
        if self.tuner.can_tune():
            recent_pnls = [t["pnl"] for t in self.closed_trades[-10:]]
            if self.tuner.should_tune(recent_pnls):
                self.tuner.adjust_threshold(increase=True)
                print(f"  {'':>5} │ {'':>10} │ {'>>> AUTO-TUNE':>20} │ {'':>8} │ "
                      f"{'':>6} │ {'':>4} │ {'':>5} │ {'':>8} │ {'':>10} │ "
                      f"Threshold → ${self.config.threshold}")

    def _close_all_positions(self, price: float, reason: str):
        """Close all open positions at session end."""
        for pos in self.open_positions:
            direction = pos["direction"]
            if direction == "BUY":
                pnl_pct = (price - pos["entry_price"]) / pos["entry_price"]
            else:
                pnl_pct = (pos["entry_price"] - price) / pos["entry_price"]
            pnl_usd = pnl_pct * pos["size"]
            self._close_position(pos, price, pnl_usd, reason)
        self.open_positions = []

    def _print_report(self, market: MarketSimulator):
        """Print comprehensive paper trading report."""
        trades = self.closed_trades
        wins = [t for t in trades if t["win"]]
        losses = [t for t in trades if not t["win"]]
        total = len(trades)

        net_pnl = self.balance - self.starting_balance
        win_rate = len(wins) / total * 100 if total > 0 else 0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Max drawdown
        peak = self.starting_balance
        max_dd = 0
        running = self.starting_balance
        for t in trades:
            running += t["pnl"]
            peak = max(peak, running)
            max_dd = max(max_dd, peak - running)

        # Per-regime breakdown
        regime_stats = {}
        for t in trades:
            r = t.get("regime", "UNKNOWN")
            if r not in regime_stats:
                regime_stats[r] = {"wins": 0, "losses": 0, "pnl": 0}
            if t["win"]:
                regime_stats[r]["wins"] += 1
            else:
                regime_stats[r]["losses"] += 1
            regime_stats[r]["pnl"] += t["pnl"]

        # Per exit-reason breakdown
        exit_stats = {}
        for t in trades:
            r = t["exit_reason"]
            if r not in exit_stats:
                exit_stats[r] = {"count": 0, "wins": 0, "pnl": 0}
            exit_stats[r]["count"] += 1
            if t["win"]:
                exit_stats[r]["wins"] += 1
            exit_stats[r]["pnl"] += t["pnl"]

        print(f"\n{'═'*74}")
        print(f"  PAPER TRADING SESSION REPORT")
        print(f"{'═'*74}")

        print(f"\n  ── Account ──────────────────────────────────────────")
        print(f"  Starting Balance:    ${self.starting_balance:>10,.2f}")
        pnl_c = "\033[92m" if net_pnl >= 0 else "\033[91m"
        print(f"  Ending Balance:      ${self.balance:>10,.2f}")
        print(f"  Net P/L:             {pnl_c}${net_pnl:>+10.2f}\033[0m")
        print(f"  Return:              {pnl_c}{net_pnl / self.starting_balance * 100:>+9.2f}%\033[0m")
        print(f"  Max Drawdown:        ${max_dd:>10.2f}")

        print(f"\n  ── Trade Stats ──────────────────────────────────────")
        print(f"  Total Trades:        {total}")
        print(f"  Wins:                {len(wins)}")
        print(f"  Losses:              {len(losses)}")
        wr_c = "\033[92m" if win_rate >= 55 else "\033[93m" if win_rate >= 50 else "\033[91m"
        print(f"  Win Rate:            {wr_c}{win_rate:.1f}%\033[0m")
        print(f"  Profit Factor:       {profit_factor:.2f}")
        print(f"  Avg Win:             ${gross_profit / len(wins):.2f}" if wins else "  Avg Win:             N/A")
        print(f"  Avg Loss:            ${-gross_loss / len(losses):.2f}" if losses else "  Avg Loss:            N/A")
        print(f"  Best Trade:          ${max(t['pnl'] for t in trades):.2f}" if trades else "")
        print(f"  Worst Trade:         ${min(t['pnl'] for t in trades):.2f}" if trades else "")

        print(f"\n  ── Per Regime ────────────────────────────────────────")
        print(f"  {'Regime':>10}  {'Wins':>5}  {'Losses':>6}  {'Win%':>6}  {'P/L':>10}")
        for r, s in sorted(regime_stats.items()):
            total_r = s["wins"] + s["losses"]
            wr_r = s["wins"] / total_r * 100 if total_r > 0 else 0
            pc = "\033[92m" if s["pnl"] >= 0 else "\033[91m"
            print(f"  {r:>10}  {s['wins']:>5}  {s['losses']:>6}  {wr_r:>5.1f}%  {pc}${s['pnl']:>+9.2f}\033[0m")

        print(f"\n  ── Exit Reasons ─────────────────────────────────────")
        print(f"  {'Reason':>15}  {'Count':>5}  {'Wins':>5}  {'Win%':>6}  {'P/L':>10}")
        for r, s in sorted(exit_stats.items()):
            wr_r = s["wins"] / s["count"] * 100 if s["count"] > 0 else 0
            pc = "\033[92m" if s["pnl"] >= 0 else "\033[91m"
            print(f"  {r:>15}  {s['count']:>5}  {s['wins']:>5}  {wr_r:>5.1f}%  {pc}${s['pnl']:>+9.2f}\033[0m")

        print(f"\n  ── Risk Management ──────────────────────────────────")
        risk_stats = self.risk.get_stats()
        print(f"  Max Loss Streak:     {risk_stats['loss_streak']}")
        print(f"  Final Threshold:     ${self.config.threshold}")
        print(f"  Bad Conditions:      {len(self.risk.bad_conditions)} stored")

        print(f"\n  ── All Trades Detail ────────────────────────────────")
        print(f"  {'#':>3}  {'Time':>5}  {'Dir':>4}  {'Entry':>10}  {'Exit':>10}  {'P/L':>8}  {'Conf':>5}  {'Regime':>8}  {'Exit Reason':>12}")
        print(f"  {'─'*82}")
        for i, t in enumerate(trades):
            rc = "\033[92m" if t["win"] else "\033[91m"
            print(
                f"  {i+1:>3}  {t['entry_time']:>5}  {t['direction']:>4}  "
                f"${t['entry_price']:>9,.2f}  ${t['exit_price']:>9,.2f}  "
                f"{rc}${t['pnl']:>+7.2f}\033[0m  {t['confidence']:>4.0%}  "
                f"{t['regime']:>8}  {t['exit_reason']:>12}"
            )

        # VERDICT
        print(f"\n{'═'*74}")
        if win_rate >= 60 and net_pnl > 0:
            print(f"  \033[92mVERDICT: READY FOR LIVE\033[0m")
            print(f"  Win rate {win_rate:.1f}% with ${net_pnl:+.2f} P/L. Algorithm validated.")
            print(f"  Recommended: Deploy with ${self.config.position_size} positions, monitor first 24h.")
        elif win_rate >= 52 and net_pnl > 0:
            print(f"  \033[93mVERDICT: CAUTIOUSLY READY\033[0m")
            print(f"  Win rate {win_rate:.1f}% is marginal but profitable. Run 1 more paper session.")
        elif net_pnl > 0:
            print(f"  \033[93mVERDICT: PROFITABLE BUT RISKY\033[0m")
            print(f"  P/L is positive (${net_pnl:+.2f}) but win rate {win_rate:.1f}% is low.")
            print(f"  Big winners carry the P/L. Increase threshold to filter more.")
        else:
            print(f"  \033[91mVERDICT: NOT READY\033[0m")
            print(f"  ${net_pnl:.2f} loss. Review the losing trades and adjust thresholds.")
        print(f"{'═'*74}\n")


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 74)
    print("  POLYMARKET BTC BOT - PAPER TRADING SESSION")
    print("  Simulating 24 hours of live trading with paper money")
    print("  Algorithm: Regime Detection + TradingView TA + Divergence")
    print("═" * 74)

    # Run 3 sessions with different market conditions
    sessions = [
        (123, "Session 1: Standard Day (trends + ranges + volatility)"),
        (456, "Session 2: Volatile Day (more spikes & chop)"),
        (789, "Session 3: Trendy Day (strong directional moves)"),
    ]

    all_results = []

    for seed, label in sessions:
        print(f"\n\n{'▓'*74}")
        print(f"  {label}")
        print(f"{'▓'*74}")

        market = MarketSimulator(seed=seed)
        trader = PaperTrader(starting_balance=1000.0)
        trader.run_session(market)

        total = len(trader.closed_trades)
        wins = sum(1 for t in trader.closed_trades if t["win"])
        net_pnl = trader.balance - trader.starting_balance

        all_results.append({
            "label": label.split(":")[0],
            "trades": total,
            "wins": wins,
            "win_rate": wins / total * 100 if total > 0 else 0,
            "pnl": net_pnl,
            "balance": trader.balance,
        })

    # Aggregate summary
    print(f"\n\n{'═'*74}")
    print(f"  AGGREGATE PAPER TRADING RESULTS (3 Sessions)")
    print(f"{'═'*74}")
    print(f"\n  {'Session':>12}  {'Trades':>7}  {'Wins':>5}  {'Win Rate':>9}  {'Net P/L':>10}  {'Balance':>12}")
    print(f"  {'─'*65}")

    total_trades = 0
    total_wins = 0
    total_pnl = 0

    for r in all_results:
        wrc = "\033[92m" if r["win_rate"] >= 55 else "\033[93m" if r["win_rate"] >= 50 else "\033[91m"
        pnlc = "\033[92m" if r["pnl"] >= 0 else "\033[91m"
        print(
            f"  {r['label']:>12}  {r['trades']:>7}  {r['wins']:>5}  "
            f"{wrc}{r['win_rate']:>8.1f}%\033[0m  "
            f"{pnlc}${r['pnl']:>+9.2f}\033[0m  ${r['balance']:>11,.2f}"
        )
        total_trades += r["trades"]
        total_wins += r["wins"]
        total_pnl += r["pnl"]

    overall_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    wrc = "\033[92m" if overall_wr >= 55 else "\033[93m" if overall_wr >= 50 else "\033[91m"
    pnlc = "\033[92m" if total_pnl >= 0 else "\033[91m"
    print(f"  {'─'*65}")
    print(
        f"  {'TOTAL':>12}  {total_trades:>7}  {total_wins:>5}  "
        f"{wrc}{overall_wr:>8.1f}%\033[0m  "
        f"{pnlc}${total_pnl:>+9.2f}\033[0m  "
    )

    print(f"\n{'═'*74}")
    if overall_wr >= 58 and total_pnl > 0:
        print(f"  \033[92mFINAL: ALGORITHM VALIDATED - Ready for live trading\033[0m")
    elif overall_wr >= 52 and total_pnl > 0:
        print(f"  \033[93mFINAL: ALGORITHM VIABLE - Start with small positions\033[0m")
    else:
        print(f"  \033[91mFINAL: NEEDS MORE TUNING - Continue paper trading\033[0m")
    print(f"{'═'*74}\n")


if __name__ == "__main__":
    main()
