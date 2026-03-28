"""
X (Twitter) Sentiment Analyzer - fetches recent BTC tweets
and calculates a sentiment score for trading signals.
"""
import httpx
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

X_API_BASE = "https://api.x.com/2"

# Keyword-based sentiment scoring (fast, no ML dependency)
BULLISH_WORDS = {
    "bullish", "moon", "pump", "rally", "breakout", "long", "buy",
    "ath", "all time high", "higher", "surge", "soar", "rocket",
    "accumulate", "hodl", "bull", "green", "rip", "send it",
    "100k", "150k", "200k", "parabolic", "fomo", "gm",
}
BEARISH_WORDS = {
    "bearish", "dump", "crash", "short", "sell", "drop", "plunge",
    "collapse", "correction", "fear", "panic", "bear", "red",
    "liquidation", "rekt", "rug", "scam", "lower", "dip",
    "recession", "capitulation", "bubble", "overvalued",
}


class XSentimentAnalyzer:
    def __init__(self, bearer_token: str = ""):
        self.bearer_token = bearer_token
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def analyze_btc_sentiment(self) -> dict:
        """
        Fetch recent BTC tweets from X and compute sentiment.
        Returns: {score: -1.0..1.0, tweet_count, bullish, bearish, neutral, tweets}
        """
        if not self.bearer_token:
            logger.warning("No X bearer token - using neutral sentiment")
            return self._neutral_result("No X API token configured")

        tweets = await self._search_recent_tweets(
            query="BTC OR Bitcoin -is:retweet lang:en",
            max_results=100,
        )

        if not tweets:
            return self._neutral_result("No tweets found")

        return self._compute_sentiment(tweets)

    async def analyze_custom_query(self, query: str, max_results: int = 50) -> dict:
        """Analyze sentiment for a custom query."""
        if not self.bearer_token:
            return self._neutral_result("No X API token configured")

        tweets = await self._search_recent_tweets(query=query, max_results=max_results)
        if not tweets:
            return self._neutral_result("No tweets found")
        return self._compute_sentiment(tweets)

    async def get_trending_btc_topics(self) -> list[str]:
        """Get trending topics related to BTC from recent tweets."""
        if not self.bearer_token:
            return []

        tweets = await self._search_recent_tweets(
            query="BTC OR Bitcoin -is:retweet lang:en",
            max_results=100,
        )

        hashtags = {}
        for tweet in tweets:
            text = tweet.get("text", "")
            tags = re.findall(r"#(\w+)", text)
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower not in ("btc", "bitcoin", "crypto"):
                    hashtags[tag_lower] = hashtags.get(tag_lower, 0) + 1

        sorted_tags = sorted(hashtags.items(), key=lambda x: x[1], reverse=True)
        return [f"#{tag}" for tag, _ in sorted_tags[:10]]

    # ── Internal Methods ──────────────────────────────────────────────

    async def _search_recent_tweets(self, query: str, max_results: int = 100) -> list[dict]:
        """Search recent tweets via X API v2."""
        try:
            headers = {"Authorization": f"Bearer {self.bearer_token}"}
            params = {
                "query": query,
                "max_results": min(max_results, 100),
                "tweet.fields": "created_at,public_metrics,author_id",
                "sort_order": "relevancy",
            }
            resp = await self.client.get(
                f"{X_API_BASE}/tweets/search/recent",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("X API rate limit hit - using neutral sentiment")
            else:
                logger.error(f"X API error: {e.response.status_code} - {e.response.text}")
            return []
        except Exception as e:
            logger.error(f"Error searching tweets: {e}")
            return []

    def _compute_sentiment(self, tweets: list[dict]) -> dict:
        """Score each tweet and aggregate."""
        bullish = 0
        bearish = 0
        neutral = 0
        scored_tweets = []

        for tweet in tweets:
            text = tweet.get("text", "").lower()
            metrics = tweet.get("public_metrics", {})
            engagement = (
                metrics.get("like_count", 0)
                + metrics.get("retweet_count", 0) * 2
                + metrics.get("reply_count", 0)
            )
            weight = 1 + min(engagement / 100, 5)  # cap engagement weight at 6x

            bull_hits = sum(1 for w in BULLISH_WORDS if w in text)
            bear_hits = sum(1 for w in BEARISH_WORDS if w in text)

            if bull_hits > bear_hits:
                bullish += weight
                tweet_sentiment = "bullish"
            elif bear_hits > bull_hits:
                bearish += weight
                tweet_sentiment = "bearish"
            else:
                neutral += 1
                tweet_sentiment = "neutral"

            scored_tweets.append({
                "text": tweet.get("text", ""),
                "sentiment": tweet_sentiment,
                "engagement": engagement,
                "created_at": tweet.get("created_at", ""),
            })

        total = bullish + bearish + neutral
        if total == 0:
            return self._neutral_result("No scorable tweets")

        # Score ranges from -1.0 (very bearish) to 1.0 (very bullish)
        score = (bullish - bearish) / (bullish + bearish + 0.001)
        score = max(-1.0, min(1.0, score))

        return {
            "score": round(score, 4),
            "tweet_count": len(tweets),
            "bullish": int(bullish),
            "bearish": int(bearish),
            "neutral": int(neutral),
            "confidence": round(abs(score), 4),
            "timestamp": datetime.utcnow().isoformat(),
            "top_tweets": sorted(scored_tweets, key=lambda x: x["engagement"], reverse=True)[:5],
        }

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
            "top_tweets": [],
            "note": reason,
        }
