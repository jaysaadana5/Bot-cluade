"""
CoinTelegraph News Sentiment Analyzer - fetches recent BTC/crypto news
from CoinTelegraph RSS feed and computes sentiment for trading signals.

No API key required - uses the public RSS feed.
"""
import httpx
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

COINTELEGRAPH_RSS = "https://cointelegraph.com/rss"
COINTELEGRAPH_BTC_RSS = "https://cointelegraph.com/rss/tag/bitcoin"

# Keyword-based sentiment scoring
BULLISH_WORDS = {
    "bullish", "rally", "surge", "soar", "breakout", "pump", "moon",
    "ath", "all-time high", "record high", "new high", "higher",
    "accumulate", "adoption", "institutional", "etf approved", "inflow",
    "bull", "green", "gains", "profit", "optimistic", "uptrend",
    "100k", "150k", "200k", "parabolic", "recovery", "rebound",
    "buy signal", "demand", "upgrade", "approval", "mainstream",
}
BEARISH_WORDS = {
    "bearish", "crash", "plunge", "dump", "drop", "decline", "sell-off",
    "correction", "fear", "panic", "bear", "red", "loss", "losses",
    "liquidation", "bankruptcy", "hack", "exploit", "vulnerability",
    "regulation", "ban", "crackdown", "sec", "lawsuit", "fraud",
    "recession", "bubble", "overvalued", "outflow", "warning",
    "sell signal", "downturn", "capitulation", "collapse",
}


class CoinTelegraphSentiment:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self._cached_result = None
        self._cache_time = None

    async def close(self):
        await self.client.aclose()

    async def analyze_btc_sentiment(self) -> dict:
        """
        Fetch recent BTC news from CoinTelegraph and compute sentiment.
        Returns: {score: -1.0..1.0, tweet_count (article_count), bullish, bearish, neutral}
        """
        # Cache for 3 minutes to avoid hammering RSS
        if self._cached_result and self._cache_time:
            age = (datetime.utcnow() - self._cache_time).total_seconds()
            if age < 180:
                return self._cached_result

        articles = await self._fetch_rss_articles()

        if not articles:
            return self._neutral_result("No articles fetched from CoinTelegraph")

        result = self._compute_sentiment(articles)
        self._cached_result = result
        self._cache_time = datetime.utcnow()
        return result

    async def get_trending_btc_topics(self) -> list[str]:
        """Extract trending topics from recent CoinTelegraph headlines."""
        articles = await self._fetch_rss_articles()

        # Extract common meaningful words from titles
        word_counts = {}
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "it", "its", "that", "this", "and", "or", "but", "not",
            "bitcoin", "btc", "crypto", "price", "market", "will", "can",
            "has", "have", "had", "new", "says", "could", "may", "after",
        }

        for article in articles:
            title = article.get("title", "").lower()
            words = re.findall(r"[a-z]+", title)
            for word in words:
                if len(word) > 3 and word not in stop_words:
                    word_counts[word] = word_counts.get(word, 0) + 1

        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:10]]

    # ── Internal Methods ──────────────────────────────────────────────

    async def _fetch_rss_articles(self) -> list[dict]:
        """Fetch articles from CoinTelegraph RSS feeds."""
        all_articles = []

        for url in [COINTELEGRAPH_BTC_RSS, COINTELEGRAPH_RSS]:
            try:
                resp = await self.client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)",
                })
                resp.raise_for_status()
                articles = self._parse_rss(resp.text)
                all_articles.extend(articles)

                if len(all_articles) >= 20:
                    break

            except Exception as e:
                logger.warning(f"CoinTelegraph RSS fetch failed ({url}): {e}")
                continue

        # Deduplicate by title
        seen = set()
        unique = []
        for a in all_articles:
            title = a.get("title", "")
            if title not in seen:
                seen.add(title)
                unique.append(a)

        # Filter to BTC-related articles
        btc_keywords = ["btc", "bitcoin", "₿"]
        btc_articles = [
            a for a in unique
            if any(kw in a.get("title", "").lower() or kw in a.get("description", "").lower()
                   for kw in btc_keywords)
        ]

        # If no BTC-specific articles, use all crypto articles
        articles = btc_articles if btc_articles else unique[:20]
        logger.info(f"CoinTelegraph: {len(articles)} articles ({len(btc_articles)} BTC-specific)")
        return articles

    def _parse_rss(self, xml_text: str) -> list[dict]:
        """Parse RSS XML into article dicts."""
        articles = []
        try:
            root = ET.fromstring(xml_text)

            # Handle both RSS 2.0 and Atom feeds
            for item in root.findall(".//item"):
                title = item.findtext("title", "")
                desc = item.findtext("description", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")

                # Clean HTML from description
                desc_clean = re.sub(r"<[^>]+>", "", desc).strip()[:500]

                articles.append({
                    "title": title,
                    "description": desc_clean,
                    "link": link,
                    "published": pub_date,
                })

        except ET.ParseError as e:
            logger.error(f"RSS parse error: {e}")

        return articles

    def _compute_sentiment(self, articles: list[dict]) -> dict:
        """Score each article and aggregate sentiment."""
        bullish = 0
        bearish = 0
        neutral = 0
        scored_articles = []

        for article in articles:
            title = article.get("title", "").lower()
            desc = article.get("description", "").lower()
            text = f"{title} {desc}"

            bull_hits = sum(1 for w in BULLISH_WORDS if w in text)
            bear_hits = sum(1 for w in BEARISH_WORDS if w in text)

            if bull_hits > bear_hits:
                bullish += 1
                sentiment = "bullish"
            elif bear_hits > bull_hits:
                bearish += 1
                sentiment = "bearish"
            else:
                neutral += 1
                sentiment = "neutral"

            scored_articles.append({
                "text": article.get("title", ""),
                "sentiment": sentiment,
                "engagement": 0,
                "created_at": article.get("published", ""),
                "link": article.get("link", ""),
            })

        total = bullish + bearish + neutral
        if total == 0:
            return self._neutral_result("No scorable articles")

        score = (bullish - bearish) / (bullish + bearish + 0.001)
        score = max(-1.0, min(1.0, score))

        return {
            "score": round(score, 4),
            "tweet_count": len(articles),  # kept as tweet_count for API compat
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "confidence": round(abs(score), 4),
            "timestamp": datetime.utcnow().isoformat(),
            "top_tweets": sorted(scored_articles, key=lambda x: x["text"])[:5],
            "source": "cointelegraph",
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
            "source": "cointelegraph",
            "note": reason,
        }
