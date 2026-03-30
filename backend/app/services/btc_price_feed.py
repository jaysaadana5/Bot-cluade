"""
BTC Price Feed via TradingView Scanner API + Binance public klines.

Two data sources:
1. TradingView Scanner: Real-time indicators (RSI, MACD, BB, EMA, recommendations)
2. Binance Public API: 5-minute OHLCV candle history (no API key needed)

This gives the bot both pre-computed indicators AND raw price data for custom TA.
"""
import httpx
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

TV_SCANNER_URL = "https://scanner.tradingview.com/crypto/scan"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Columns we request from TradingView's scanner
TV_COLUMNS_REALTIME = [
    # Price
    "close", "open", "high", "low", "volume", "change", "change_abs",
    # TradingView Recommendations (computed from all their indicators)
    "Recommend.All", "Recommend.MA", "Recommend.Other",
    # Oscillators
    "RSI", "RSI[1]", "Stoch.K", "Stoch.D", "Stoch.K[1]", "Stoch.D[1]",
    "CCI20", "CCI20[1]", "ADX", "ADX+DI", "ADX-DI", "ADX+DI[1]", "ADX-DI[1]",
    "AO", "AO[1]", "AO[2]", "Mom", "Mom[1]",
    "MACD.macd", "MACD.signal",
    # Moving Averages
    "EMA5", "EMA10", "EMA20", "EMA50", "EMA100", "EMA200",
    "SMA5", "SMA10", "SMA20", "SMA50", "SMA100", "SMA200",
    # Bollinger / Ichimoku / VWAP
    "BB.upper", "BB.lower", "Ichimoku.BLine",
    "VWAP", "P.SAR",
    # Pivots
    "Pivot.M.Classic.R1", "Pivot.M.Classic.S1",
]

# 5-minute interval columns (append |5| for 5m timeframe)
TV_COLUMNS_5M = [f"{col}|5" for col in TV_COLUMNS_REALTIME]


class BTCPriceFeed:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.last_data = {}
        self.last_5m_data = {}
        self.last_candles = []

    async def close(self):
        await self.client.aclose()

    async def get_tradingview_analysis(self, interval: str = "5") -> dict:
        """
        Fetch TradingView's full technical analysis for BTCUSDT.

        interval: "1", "5", "15", "60", "240", "1D", "1W", "1M"
        Returns all indicators + TradingView's BUY/SELL recommendation.
        """
        if interval == "5":
            columns = TV_COLUMNS_5M
        else:
            columns = TV_COLUMNS_REALTIME

        payload = {
            "symbols": {
                "tickers": ["BINANCE:BTCUSDT"],
                "query": {"types": []},
            },
            "columns": columns,
        }

        try:
            resp = await self.client.post(TV_SCANNER_URL, json=payload)
            resp.raise_for_status()
            result = resp.json()

            if not result.get("data") or not result["data"][0].get("d"):
                logger.warning("TradingView returned empty data")
                return self.last_5m_data if interval == "5" else self.last_data

            values = result["data"][0]["d"]
            col_names = columns

            # Map column names to values
            raw = {}
            for name, val in zip(col_names, values):
                clean = name.replace("|5", "").replace("|15", "").replace("|60", "")
                raw[clean] = val

            data = self._parse_tv_data(raw)
            data["interval"] = interval
            data["timestamp"] = datetime.utcnow().isoformat()
            data["source"] = "tradingview"

            if interval == "5":
                self.last_5m_data = data
            else:
                self.last_data = data

            logger.info(
                f"TradingView {interval}m: BTC ${data['price']:.2f} | "
                f"Rec: {data['recommendation']} | RSI: {data['rsi']:.1f}"
            )
            return data

        except Exception as e:
            logger.error(f"TradingView scanner error: {e}")
            return self.last_5m_data if interval == "5" else self.last_data

    async def get_multi_timeframe_analysis(self) -> dict:
        """
        Get TradingView analysis across multiple timeframes.
        Consensus across timeframes = stronger signal.
        """
        analyses = {}
        for interval in ["5", "15", "60"]:
            suffix = f"|{interval}" if interval != "1D" else ""
            columns = [f"{col}{suffix}" if suffix else col for col in TV_COLUMNS_REALTIME]

            payload = {
                "symbols": {
                    "tickers": ["BINANCE:BTCUSDT"],
                    "query": {"types": []},
                },
                "columns": columns,
            }

            try:
                resp = await self.client.post(TV_SCANNER_URL, json=payload)
                resp.raise_for_status()
                result = resp.json()

                if result.get("data") and result["data"][0].get("d"):
                    values = result["data"][0]["d"]
                    raw = {}
                    for name, val in zip(columns, values):
                        clean = name.replace(f"|{interval}", "")
                        raw[clean] = val
                    analyses[f"{interval}m"] = self._parse_tv_data(raw)
            except Exception as e:
                logger.error(f"TradingView {interval}m fetch error: {e}")

        recs = [a.get("recommend_all", 0) for a in analyses.values() if a.get("recommend_all") is not None]
        if recs:
            avg_rec = sum(recs) / len(recs)
            if avg_rec > 0.3:
                consensus = "STRONG_BUY"
            elif avg_rec > 0.1:
                consensus = "BUY"
            elif avg_rec < -0.3:
                consensus = "STRONG_SELL"
            elif avg_rec < -0.1:
                consensus = "SELL"
            else:
                consensus = "NEUTRAL"
        else:
            consensus = "UNKNOWN"
            avg_rec = 0

        return {
            "analyses": analyses,
            "consensus": consensus,
            "avg_recommendation": round(avg_rec, 4),
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def get_5m_candles(self, limit: int = 100) -> list[dict]:
        """
        Fetch BTC 5m candle history from Binance public API.
        No API key needed - completely free.
        """
        # Primary: Binance public klines endpoint
        try:
            resp = await self.client.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": min(limit, 500),
                },
            )
            resp.raise_for_status()
            data = resp.json()

            candles = []
            for k in data:
                candles.append({
                    "timestamp": int(k[0]),
                    "time_str": datetime.utcfromtimestamp(k[0] / 1000).isoformat(),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })

            if candles:
                self.last_candles = candles
                logger.info(f"Binance: fetched {len(candles)} 5m candles, "
                            f"latest=${candles[-1]['close']:.2f}")
                return candles

        except Exception as e:
            logger.warning(f"Binance klines failed: {e}")

        # Fallback: build candles from scanner snapshots over time
        if self.last_5m_data and self.last_5m_data.get("price"):
            d = self.last_5m_data
            candle = {
                "timestamp": int(datetime.utcnow().timestamp() * 1000),
                "time_str": datetime.utcnow().isoformat(),
                "open": d.get("open", d.get("price", 0)),
                "high": d.get("high", d.get("price", 0)),
                "low": d.get("low", d.get("price", 0)),
                "close": d.get("price", 0),
                "volume": d.get("volume", 0),
            }
            self.last_candles.append(candle)
            self.last_candles = self.last_candles[-limit:]
            logger.info(f"Scanner fallback: {len(self.last_candles)} candles accumulated")
            return self.last_candles

        return self.last_candles

    def _parse_tv_data(self, raw: dict) -> dict:
        """Parse raw TradingView scanner data into a structured dict."""
        price = raw.get("close", 0) or 0

        rec_all = raw.get("Recommend.All", 0) or 0
        rec_ma = raw.get("Recommend.MA", 0) or 0
        rec_osc = raw.get("Recommend.Other", 0) or 0

        if rec_all > 0.5:
            recommendation = "STRONG_BUY"
        elif rec_all > 0.1:
            recommendation = "BUY"
        elif rec_all < -0.5:
            recommendation = "STRONG_SELL"
        elif rec_all < -0.1:
            recommendation = "SELL"
        else:
            recommendation = "NEUTRAL"

        return {
            "price": float(price),
            "open": float(raw.get("open", 0) or 0),
            "high": float(raw.get("high", 0) or 0),
            "low": float(raw.get("low", 0) or 0),
            "volume": float(raw.get("volume", 0) or 0),
            "change": float(raw.get("change", 0) or 0),
            "change_abs": float(raw.get("change_abs", 0) or 0),
            # TradingView recommendations
            "recommend_all": float(rec_all),
            "recommend_ma": float(rec_ma),
            "recommend_oscillators": float(rec_osc),
            "recommendation": recommendation,
            # Oscillators
            "rsi": float(raw.get("RSI", 50) or 50),
            "rsi_prev": float(raw.get("RSI[1]", 50) or 50),
            "stoch_k": float(raw.get("Stoch.K", 50) or 50),
            "stoch_d": float(raw.get("Stoch.D", 50) or 50),
            "cci": float(raw.get("CCI20", 0) or 0),
            "adx": float(raw.get("ADX", 0) or 0),
            "adx_plus_di": float(raw.get("ADX+DI", 0) or 0),
            "adx_minus_di": float(raw.get("ADX-DI", 0) or 0),
            "ao": float(raw.get("AO", 0) or 0),
            "momentum": float(raw.get("Mom", 0) or 0),
            "macd": float(raw.get("MACD.macd", 0) or 0),
            "macd_signal": float(raw.get("MACD.signal", 0) or 0),
            # Moving Averages
            "ema5": float(raw.get("EMA5", 0) or 0),
            "ema10": float(raw.get("EMA10", 0) or 0),
            "ema20": float(raw.get("EMA20", 0) or 0),
            "ema50": float(raw.get("EMA50", 0) or 0),
            "ema100": float(raw.get("EMA100", 0) or 0),
            "ema200": float(raw.get("EMA200", 0) or 0),
            "sma5": float(raw.get("SMA5", 0) or 0),
            "sma10": float(raw.get("SMA10", 0) or 0),
            "sma20": float(raw.get("SMA20", 0) or 0),
            "sma50": float(raw.get("SMA50", 0) or 0),
            "sma100": float(raw.get("SMA100", 0) or 0),
            "sma200": float(raw.get("SMA200", 0) or 0),
            # Bands
            "bb_upper": float(raw.get("BB.upper", 0) or 0),
            "bb_lower": float(raw.get("BB.lower", 0) or 0),
            "vwap": float(raw.get("VWAP", 0) or 0),
            "psar": float(raw.get("P.SAR", 0) or 0),
            # Pivots
            "pivot_r1": float(raw.get("Pivot.M.Classic.R1", 0) or 0),
            "pivot_s1": float(raw.get("Pivot.M.Classic.S1", 0) or 0),
        }

    def extract_prices(self, candles: list[dict] = None) -> list[float]:
        data = candles or self.last_candles
        return [c["close"] for c in data]

    def extract_volumes(self, candles: list[dict] = None) -> list[float]:
        data = candles or self.last_candles
        return [c["volume"] for c in data]

    def extract_ohlcv(self, candles: list[dict] = None) -> dict:
        data = candles or self.last_candles
        return {
            "open": [c["open"] for c in data],
            "high": [c["high"] for c in data],
            "low": [c["low"] for c in data],
            "close": [c["close"] for c in data],
            "volume": [c["volume"] for c in data],
            "timestamps": [c["time_str"] for c in data],
        }
