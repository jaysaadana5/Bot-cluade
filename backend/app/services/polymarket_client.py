"""
Polymarket API Client - interfaces with Polymarket's CLOB API
for BTC-related prediction markets.
"""
import json
import httpx
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

POLYMARKET_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"


class PolymarketClient:
    def __init__(self, api_key: str = "", secret: str = "", passphrase: str = "", funder: str = ""):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.funder = funder
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    # ── Market Discovery ──────────────────────────────────────────────

    async def get_btc_markets(self) -> list[dict]:
        """Fetch active BTC-related prediction markets from Gamma API."""
        try:
            resp = await self.client.get(
                f"{GAMMA_API_BASE}/markets",
                params={
                    "tag": "crypto",
                    "active": "true",
                    "closed": "false",
                    "limit": 50,
                },
            )
            resp.raise_for_status()
            markets = resp.json()

            btc_markets = []
            btc_keywords = ["btc", "bitcoin", "₿"]
            for m in markets:
                question = (m.get("question", "") or "").lower()
                desc = (m.get("description", "") or "").lower()
                if any(kw in question or kw in desc for kw in btc_keywords):
                    btc_markets.append(self._normalize_market(m))

            logger.info(f"Found {len(btc_markets)} BTC markets")
            return btc_markets
        except Exception as e:
            logger.error(f"Error fetching BTC markets: {e}")
            return []

    async def get_market(self, condition_id: str) -> Optional[dict]:
        """Get a single market by condition ID."""
        try:
            resp = await self.client.get(f"{GAMMA_API_BASE}/markets/{condition_id}")
            resp.raise_for_status()
            return self._normalize_market(resp.json())
        except Exception as e:
            logger.error(f"Error fetching market {condition_id}: {e}")
            return None

    # ── Order Book ────────────────────────────────────────────────────

    async def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a specific token."""
        try:
            resp = await self.client.get(
                f"{POLYMARKET_API_BASE}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return {"bids": [], "asks": []}

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        try:
            resp = await self.client.get(
                f"{POLYMARKET_API_BASE}/midpoint",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("mid", 0))
        except Exception as e:
            logger.error(f"Error fetching midpoint: {e}")
            return None

    async def get_price_history(self, token_id: str, fidelity: int = 5) -> list[dict]:
        """Get price history for charting. fidelity in minutes."""
        try:
            resp = await self.client.get(
                f"{POLYMARKET_API_BASE}/prices-history",
                params={"market": token_id, "interval": "max", "fidelity": fidelity},
            )
            resp.raise_for_status()
            return resp.json().get("history", [])
        except Exception as e:
            logger.error(f"Error fetching price history: {e}")
            return []

    # ── Trading ───────────────────────────────────────────────────────

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict:
        """
        Place a limit order on Polymarket CLOB.
        side: 'BUY' or 'SELL'
        price: 0.01 to 0.99
        size: number of shares
        """
        if not self.api_key:
            logger.warning("No API key configured - running in paper trading mode")
            return {
                "order_id": f"paper_{datetime.utcnow().timestamp()}",
                "status": "paper_trade",
                "side": side,
                "price": price,
                "size": size,
                "token_id": token_id,
            }

        try:
            headers = self._auth_headers()
            order_payload = {
                "tokenID": token_id,
                "price": price,
                "size": size,
                "side": side.upper(),
                "feeRateBps": 0,
                "nonce": 0,
                "expiration": 0,
                "taker": "0x0000000000000000000000000000000000000000",
            }

            resp = await self.client.post(
                f"{POLYMARKET_API_BASE}/order",
                json=order_payload,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Order placed: {side} {size}@{price} - {result}")
            return result
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"error": str(e), "status": "failed"}

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an existing order."""
        if not self.api_key:
            return {"status": "paper_cancelled", "order_id": order_id}
        try:
            headers = self._auth_headers()
            resp = await self.client.delete(
                f"{POLYMARKET_API_BASE}/order/{order_id}",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {"error": str(e)}

    async def get_open_orders(self) -> list[dict]:
        """Get all open orders."""
        if not self.api_key:
            return []
        try:
            headers = self._auth_headers()
            resp = await self.client.get(
                f"{POLYMARKET_API_BASE}/orders",
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []

    # ── Helpers ───────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        return {
            "POLY-ADDRESS": self.funder,
            "POLY-SIGNATURE": self.secret,
            "POLY-TIMESTAMP": str(int(datetime.utcnow().timestamp())),
            "POLY-NONCE": "0",
            "POLY-API-KEY": self.api_key,
            "POLY-PASSPHRASE": self.passphrase,
        }

    @staticmethod
    def _normalize_market(m: dict) -> dict:
        tokens = m.get("tokens", []) or m.get("clobTokenIds", [])
        yes_token = ""
        no_token = ""
        yes_price = 0.5
        no_price = 0.5

        if isinstance(tokens, list) and tokens:
            if isinstance(tokens[0], dict):
                for t in tokens:
                    if t.get("outcome", "").lower() == "yes":
                        yes_token = t.get("token_id", "")
                        yes_price = float(t.get("price", 0.5))
                    elif t.get("outcome", "").lower() == "no":
                        no_token = t.get("token_id", "")
                        no_price = float(t.get("price", 0.5))
            elif isinstance(tokens[0], str) and len(tokens) >= 2:
                yes_token = tokens[0]
                no_token = tokens[1]

        outcome_prices = m.get("outcomePrices", "")
        if outcome_prices and isinstance(outcome_prices, str):
            try:
                prices = json.loads(outcome_prices)
                if len(prices) >= 2:
                    yes_price = float(prices[0])
                    no_price = float(prices[1])
            except Exception:
                pass

        return {
            "id": m.get("id") or m.get("condition_id", ""),
            "question": m.get("question", ""),
            "description": m.get("description", ""),
            "yes_token": yes_token,
            "no_token": no_token,
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": float(m.get("volume", 0) or 0),
            "liquidity": float(m.get("liquidity", 0) or 0),
            "end_date": m.get("endDate") or m.get("end_date_iso", ""),
            "active": m.get("active", True),
            "closed": m.get("closed", False),
        }
