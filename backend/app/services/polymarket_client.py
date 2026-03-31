"""
Polymarket API Client - proper integration with py-clob-client SDK.

Uses:
- py-clob-client: For authenticated trading (order signing, placement, cancellation)
- httpx: For read-only market discovery (Gamma API) and public CLOB endpoints
- Supports both paper and live trading modes
"""
import json
import asyncio
import httpx
import logging
from typing import Optional
from datetime import datetime
from functools import partial

logger = logging.getLogger(__name__)

POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYGON_CHAIN_ID = 137  # Polygon mainnet


class PolymarketClient:
    """
    Polymarket API client with proper CLOB SDK integration.

    For LIVE trading: requires private_key to init py-clob-client for order signing.
    For PAPER/read-only: works without credentials using httpx for public endpoints.
    """

    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        funder: str = "",
        private_key: str = "",
    ):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.funder = funder
        self.private_key = private_key
        self.client = httpx.AsyncClient(timeout=30.0)

        # py-clob-client instance (sync SDK, used via run_in_executor)
        self._clob_client = None
        self._clob_initialized = False
        self._init_clob_client()

    def _init_clob_client(self):
        """Initialize the py-clob-client SDK if credentials are available."""
        if not self.private_key:
            logger.info("No private key - CLOB client not initialized (paper mode only)")
            return

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
        except (ImportError, Exception) as e:
            logger.warning(f"py-clob-client not available: {e} - paper mode only")
            self._clob_client = None
            return

        try:
            self._clob_client = ClobClient(
                POLYMARKET_CLOB_URL,
                key=self.private_key,
                chain_id=POLYGON_CHAIN_ID,
            )

            if self.api_key and self.secret and self.passphrase:
                self._clob_client.set_api_creds(ApiCreds(
                    api_key=self.api_key,
                    api_secret=self.secret,
                    api_passphrase=self.passphrase,
                ))
                self._clob_initialized = True
                logger.info("CLOB client initialized with API credentials")
            else:
                logger.info("CLOB client created (private key only, no API creds yet)")
        except BaseException as e:
            logger.warning(f"CLOB client init failed (paper mode still works): {e}")
            self._clob_client = None
            self._clob_initialized = False

    async def derive_api_credentials(self) -> dict:
        """
        Generate Polymarket API credentials from private key.
        Must be called once to get api_key/secret/passphrase.
        Returns the credentials dict.
        """
        if not self._clob_client:
            return {"error": "No private key configured - cannot derive credentials"}

        try:
            loop = asyncio.get_event_loop()
            creds = await loop.run_in_executor(
                None, self._clob_client.create_or_derive_api_creds
            )

            # Store credentials
            self.api_key = creds.api_key
            self.secret = creds.api_secret
            self.passphrase = creds.api_passphrase

            # Re-set on CLOB client
            from py_clob_client.clob_types import ApiCreds
            self._clob_client.set_api_creds(ApiCreds(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase,
            ))
            self._clob_initialized = True

            logger.info("API credentials derived successfully")
            return {
                "status": "ok",
                "api_key": creds.api_key,
                "api_secret": creds.api_secret,
                "api_passphrase": creds.api_passphrase,
                "funder": self.funder,
            }
        except Exception as e:
            logger.error(f"Failed to derive API credentials: {e}")
            return {"error": str(e)}

    @property
    def is_live_ready(self) -> bool:
        """Check if client is ready for live trading."""
        return self._clob_initialized and self._clob_client is not None

    async def close(self):
        await self.client.aclose()

    # ── Market Discovery (Gamma API - public, no auth needed) ────────

    async def get_btc_5min_market(self) -> Optional[dict]:
        """
        Find the current active BTC 5-minute UP/DOWN market on Polymarket.
        Searches for markets matching BTC 5-minute resolution patterns.
        Returns the best matching active market or None.
        """
        search_queries = [
            {"active": "true", "closed": "false", "limit": 100, "tag": "crypto"},
            {"active": "true", "closed": "false", "limit": 100, "tag": "bitcoin"},
            {"active": "true", "closed": "false", "limit": 200},
        ]

        btc_5min_keywords = [
            "5 min", "5-min", "5min", "five min", "five-min",
            "next 5", "next five",
        ]
        btc_keywords = ["btc", "bitcoin", "₿"]
        direction_keywords = ["up", "down", "above", "below", "higher", "lower", "rise", "fall"]

        best_market = None
        all_btc_5min = []

        for params in search_queries:
            try:
                resp = await self.client.get(f"{GAMMA_API_BASE}/markets", params=params)
                resp.raise_for_status()
                markets = resp.json()
                logger.info(f"Gamma API returned {len(markets)} markets for params={params}")

                for m in markets:
                    question = (m.get("question", "") or "").lower()
                    desc = (m.get("description", "") or "").lower()
                    text = f"{question} {desc}"

                    is_btc = any(kw in text for kw in btc_keywords)
                    is_5min = any(kw in text for kw in btc_5min_keywords)
                    is_direction = any(kw in text for kw in direction_keywords)

                    if is_btc and is_5min:
                        normalized = self._normalize_market(m)
                        normalized["is_5min"] = True
                        normalized["is_direction"] = is_direction
                        all_btc_5min.append(normalized)
                        logger.info(f"Found BTC 5min market: {m.get('question', '')}")

                if all_btc_5min:
                    break  # Found matches, stop searching

            except Exception as e:
                logger.error(f"Error fetching markets: {e}")
                continue

        if all_btc_5min:
            # Prefer direction markets (up/down), then by volume
            direction_markets = [m for m in all_btc_5min if m.get("is_direction")]
            pool = direction_markets if direction_markets else all_btc_5min
            best_market = max(pool, key=lambda m: m.get("volume", 0))
            logger.info(f"Selected BTC 5min market: {best_market['question']} (vol={best_market.get('volume', 0)})")

        return best_market

    async def get_btc_markets(self) -> list[dict]:
        """
        Fetch active BTC prediction markets from Gamma API.
        Prioritizes BTC 5-minute UP/DOWN markets.
        """
        btc_markets = []
        btc_keywords = ["btc", "bitcoin", "₿"]

        # First try to find BTC 5min market
        btc_5min = await self.get_btc_5min_market()
        if btc_5min:
            btc_5min["is_primary"] = True
            btc_markets.append(btc_5min)

        # Also fetch other BTC markets for reference
        search_params = [
            {"tag": "crypto", "active": "true", "closed": "false", "limit": 100},
            {"active": "true", "closed": "false", "limit": 100, "tag": "bitcoin"},
        ]

        for params in search_params:
            try:
                resp = await self.client.get(f"{GAMMA_API_BASE}/markets", params=params)
                resp.raise_for_status()
                markets = resp.json()

                for m in markets:
                    question = (m.get("question", "") or "").lower()
                    desc = (m.get("description", "") or "").lower()
                    mid = m.get("id") or m.get("condition_id", "")
                    if any(kw in question or kw in desc for kw in btc_keywords):
                        if not any(existing["id"] == mid for existing in btc_markets):
                            btc_markets.append(self._normalize_market(m))

                if len(btc_markets) > 1:
                    break

            except Exception as e:
                logger.error(f"Error fetching markets with params {params}: {e}")
                continue

        logger.info(f"Found {len(btc_markets)} BTC markets total")
        return btc_markets

    async def get_market_prices_realtime(self, token_id: str) -> dict:
        """
        Get real-time price data for a Polymarket token.
        Returns current YES/NO prices and recent price movement.
        """
        result = {"yes_price": 0.5, "no_price": 0.5, "midpoint": 0.5, "spread": 0}

        # Get midpoint
        mid = await self.get_midpoint(token_id)
        if mid:
            result["yes_price"] = mid
            result["no_price"] = round(1 - mid, 4)
            result["midpoint"] = mid

        # Get orderbook for spread
        book = await self.get_orderbook(token_id)
        if book.get("bids") and book.get("asks"):
            best_bid = float(book["bids"][0]["price"]) if book["bids"] else 0
            best_ask = float(book["asks"][0]["price"]) if book["asks"] else 1
            result["spread"] = round(best_ask - best_bid, 4)
            result["best_bid"] = best_bid
            result["best_ask"] = best_ask
            # Bid/ask volumes
            bid_vol = sum(float(b.get("size", 0)) for b in book["bids"][:5])
            ask_vol = sum(float(a.get("size", 0)) for a in book["asks"][:5])
            result["bid_volume"] = bid_vol
            result["ask_volume"] = ask_vol
            total = bid_vol + ask_vol
            result["buy_pressure"] = round(bid_vol / total, 4) if total > 0 else 0.5

        return result

    async def get_all_markets(self, limit: int = 100) -> list[dict]:
        """Fetch all active markets (not just BTC)."""
        try:
            resp = await self.client.get(
                f"{GAMMA_API_BASE}/markets",
                params={"active": "true", "closed": "false", "limit": limit},
            )
            resp.raise_for_status()
            markets = resp.json()
            return [self._normalize_market(m) for m in markets]
        except Exception as e:
            logger.error(f"Error fetching all markets: {e}")
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

    # ── Order Book (CLOB public endpoints) ───────────────────────────

    async def get_orderbook(self, token_id: str) -> dict:
        """Get order book for a specific token."""
        # Try py-clob-client first if available
        if self._clob_client:
            try:
                loop = asyncio.get_event_loop()
                book = await loop.run_in_executor(
                    None, partial(self._clob_client.get_order_book, token_id)
                )
                return {
                    "bids": [{"price": str(o.price), "size": str(o.size)} for o in book.bids],
                    "asks": [{"price": str(o.price), "size": str(o.size)} for o in book.asks],
                }
            except Exception as e:
                logger.warning(f"CLOB orderbook failed, falling back to HTTP: {e}")

        # Fallback: direct HTTP
        try:
            resp = await self.client.get(
                f"{POLYMARKET_CLOB_URL}/book",
                params={"token_id": token_id},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return {"bids": [], "asks": []}

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price for a token."""
        if self._clob_client:
            try:
                loop = asyncio.get_event_loop()
                mid = await loop.run_in_executor(
                    None, partial(self._clob_client.get_midpoint, token_id)
                )
                return float(mid) if mid else None
            except Exception as e:
                logger.warning(f"CLOB midpoint failed, falling back to HTTP: {e}")

        try:
            resp = await self.client.get(
                f"{POLYMARKET_CLOB_URL}/midpoint",
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
                f"{POLYMARKET_CLOB_URL}/prices-history",
                params={"market": token_id, "interval": "max", "fidelity": fidelity},
            )
            resp.raise_for_status()
            return resp.json().get("history", [])
        except Exception as e:
            logger.error(f"Error fetching price history: {e}")
            return []

    # ── Trading (requires py-clob-client with signed orders) ─────────

    async def place_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> dict:
        """
        Place a limit order on Polymarket CLOB.

        Uses py-clob-client for proper order signing (EIP-712).
        side: 'BUY' or 'SELL'
        price: 0.01 to 0.99
        size: number of shares
        """
        if not self.api_key or not self._clob_initialized:
            logger.warning("No API credentials - returning paper trade result")
            return {
                "order_id": f"paper_{datetime.utcnow().timestamp()}",
                "status": "paper_trade",
                "side": side,
                "price": price,
                "size": size,
                "token_id": token_id,
            }

        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if side.upper() == "BUY" else SELL

            loop = asyncio.get_event_loop()

            # Build signed order using py-clob-client
            signed_order = await loop.run_in_executor(
                None,
                partial(
                    self._clob_client.create_and_post_order,
                    {
                        "token_id": token_id,
                        "price": price,
                        "size": size,
                        "side": order_side,
                    }
                )
            )

            logger.info(f"Order placed via CLOB SDK: {side} {size}@{price} - {signed_order}")
            return {
                "order_id": signed_order.get("orderID", signed_order.get("id", "")),
                "status": signed_order.get("status", "submitted"),
                "side": side,
                "price": price,
                "size": size,
                "token_id": token_id,
                "raw": signed_order,
            }
        except Exception as e:
            logger.error(f"Error placing order via CLOB SDK: {e}", exc_info=True)
            return {"error": str(e), "status": "failed"}

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an existing order via CLOB SDK."""
        if not self._clob_initialized:
            return {"status": "paper_cancelled", "order_id": order_id}

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, partial(self._clob_client.cancel, order_id)
            )
            logger.info(f"Order cancelled: {order_id} - {result}")
            return {"status": "cancelled", "order_id": order_id, "raw": result}
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return {"error": str(e), "order_id": order_id}

    async def cancel_all_orders(self) -> dict:
        """Cancel all open orders."""
        if not self._clob_initialized:
            return {"status": "paper_mode", "cancelled": 0}

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._clob_client.cancel_all
            )
            logger.info(f"All orders cancelled: {result}")
            return {"status": "ok", "raw": result}
        except Exception as e:
            logger.error(f"Error cancelling all orders: {e}")
            return {"error": str(e)}

    async def get_open_orders(self) -> list[dict]:
        """Get all open orders via CLOB SDK."""
        if not self._clob_initialized:
            return []

        try:
            loop = asyncio.get_event_loop()
            orders = await loop.run_in_executor(
                None, self._clob_client.get_orders
            )
            return orders if isinstance(orders, list) else []
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")
            return []

    async def get_positions(self) -> list[dict]:
        """Get current positions from Polymarket."""
        if not self._clob_initialized:
            return []

        try:
            # Use the CLOB API endpoint for positions
            resp = await self.client.get(
                f"{POLYMARKET_CLOB_URL}/positions",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    async def get_balance(self) -> dict:
        """Get USDC balance on Polymarket."""
        if not self._clob_initialized:
            return {"balance": 0, "status": "paper_mode"}

        try:
            resp = await self.client.get(
                f"{POLYMARKET_CLOB_URL}/balance",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return {"balance": 0, "error": str(e)}

    # ── Helpers ───────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        """Auth headers for direct HTTP calls (non-SDK endpoints)."""
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
