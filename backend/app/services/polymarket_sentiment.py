"""
Polymarket Sentiment - derives market sentiment from Polymarket BTC 5min
UP/DOWN market odds instead of external news sources.

The Polymarket YES/NO prices ARE the sentiment:
- YES > 0.55 = market is bullish (traders betting BTC goes up)
- YES < 0.45 = market is bearish (traders betting BTC goes down)
- Order book pressure shows where money is flowing
- Price history trend shows momentum of sentiment
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class PolymarketSentiment:
    """
    Derives sentiment directly from Polymarket BTC 5min UP/DOWN market.
    No external API keys needed - uses the same Polymarket data the bot trades on.
    """

    def __init__(self, polymarket_client):
        self.polymarket = polymarket_client
        self._cached_result = None
        self._cache_time = None

    async def close(self):
        """No separate client to close - uses polymarket_client."""
        pass

    async def analyze_btc_sentiment(self) -> dict:
        """
        Compute sentiment from Polymarket BTC 5min market odds.
        Returns: {score: -1.0..1.0, bullish, bearish, neutral, ...}
        """
        # Cache for 30 seconds to avoid hammering
        if self._cached_result and self._cache_time:
            age = (datetime.utcnow() - self._cache_time).total_seconds()
            if age < 30:
                return self._cached_result

        result = await self._compute_from_polymarket()
        self._cached_result = result
        self._cache_time = datetime.utcnow()
        return result

    async def _compute_from_polymarket(self) -> dict:
        """Fetch Polymarket BTC 5min market and derive sentiment."""
        try:
            market = await self.polymarket.get_btc_5min_market()
            if not market:
                return self._neutral_result("No BTC 5min market found on Polymarket")

            yes_token = market.get("yes_token", "")
            no_token = market.get("no_token", "")

            # Get real-time prices from orderbook analysis
            yes_price = market.get("yes_price", 0.50)
            no_price = market.get("no_price", 0.50)
            buy_pressure = 0.5
            bid_vol = 0
            ask_vol = 0
            spread = 0

            if yes_token:
                try:
                    prices = await self.polymarket.get_market_orderbook_analysis(
                        yes_token, no_token
                    )
                    yes_price = prices.get("yes_price", yes_price)
                    no_price = prices.get("no_price", no_price)
                    buy_pressure = prices.get("buy_pressure", 0.5)
                    bid_vol = prices.get("bid_volume", 0)
                    ask_vol = prices.get("ask_volume", 0)
                    spread = prices.get("spread", 0)
                except Exception as e:
                    logger.warning(f"Orderbook analysis failed: {e}")

            # Get price history for trend
            price_history = []
            if yes_token:
                try:
                    price_history = await self.polymarket.get_price_history(
                        yes_token, fidelity=1
                    )
                except Exception as e:
                    logger.warning(f"Price history fetch failed: {e}")

            # Calculate trend from history
            trend_score = 0
            if len(price_history) >= 3:
                recent = [float(p.get("p", p.get("price", 0.5)))
                          for p in price_history[-5:]]
                if len(recent) >= 2 and recent[0] > 0:
                    trend_score = (recent[-1] - recent[0]) / max(recent[0], 0.01)

            # --- Derive sentiment score ---
            # YES price: 0.5 = neutral, >0.5 = bullish, <0.5 = bearish
            price_sentiment = (yes_price - 0.50) * 2  # Maps 0.3-0.7 to -0.4..+0.4

            # Order book: buy pressure > 0.5 = bullish
            book_sentiment = (buy_pressure - 0.50) * 1.5  # Maps 0.3-0.7 to -0.3..+0.3

            # Trend: positive = bullish
            trend_sentiment = min(max(trend_score * 10, -0.3), 0.3)

            # Weighted combination
            score = (
                price_sentiment * 0.50 +
                book_sentiment * 0.30 +
                trend_sentiment * 0.20
            )
            score = max(-1.0, min(1.0, score))

            # Classify
            if score > 0.05:
                bullish = 1
                bearish = 0
                neutral = 0
            elif score < -0.05:
                bullish = 0
                bearish = 1
                neutral = 0
            else:
                bullish = 0
                bearish = 0
                neutral = 1

            logger.info(
                f"[SENTIMENT] Polymarket: YES={yes_price:.3f} "
                f"pressure={buy_pressure:.2f} trend={trend_score:.4f} "
                f"→ score={score:.3f}"
            )

            return {
                "score": round(score, 4),
                "tweet_count": len(price_history),  # kept for API compat
                "bullish": bullish,
                "bearish": bearish,
                "neutral": neutral,
                "confidence": round(abs(score), 4),
                "timestamp": datetime.utcnow().isoformat(),
                "source": "polymarket",
                "market": market.get("question", "BTC 5min UP/DOWN"),
                "details": {
                    "yes_price": round(yes_price, 4),
                    "no_price": round(no_price, 4),
                    "buy_pressure": round(buy_pressure, 4),
                    "bid_volume": bid_vol,
                    "ask_volume": ask_vol,
                    "spread": round(spread, 4),
                    "price_sentiment": round(price_sentiment, 4),
                    "book_sentiment": round(book_sentiment, 4),
                    "trend_sentiment": round(trend_sentiment, 4),
                    "history_points": len(price_history),
                },
                "top_tweets": [],  # kept for API compat
            }

        except Exception as e:
            logger.error(f"Polymarket sentiment error: {e}")
            return self._neutral_result(f"Error: {e}")

    async def get_trending_btc_topics(self) -> list[str]:
        """Return Polymarket market info as topics."""
        try:
            market = await self.polymarket.get_btc_5min_market()
            if market:
                return [
                    market.get("question", "BTC 5min"),
                    f"YES: {market.get('yes_price', 0.5):.0%}",
                    f"NO: {market.get('no_price', 0.5):.0%}",
                    f"Vol: ${market.get('volume', 0):,.0f}",
                ]
        except Exception:
            pass
        return ["BTC 5min UP/DOWN", "Polymarket"]

    @staticmethod
    def _neutral_result(reason: str) -> dict:
        return {
            "score": 0.0,
            "tweet_count": 0,
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "confidence": 0.0,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "polymarket",
            "top_tweets": [],
            "note": reason,
        }
