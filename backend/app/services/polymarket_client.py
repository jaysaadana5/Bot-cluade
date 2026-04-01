"""
Polymarket API Client - uses CLOB API (clob.polymarket.com) for real-time data.

PRIMARY: CLOB /books endpoint for live market discovery + orderbooks
SECONDARY: Gamma API only as fallback for metadata

CLOB is the real trading layer - Gamma is stale/cached.
"""
import json
import re
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

# Keywords to find BTC 5min UP/DOWN markets
BTC_KEYWORDS = ["btc", "bitcoin", "₿"]
FIVE_MIN_KEYWORDS = ["5 min", "5-min", "5min", "five min"]
DIRECTION_KEYWORDS = ["up", "down", "up or down", "above", "below"]


class PolymarketClient:
    """
    Polymarket API client using CLOB API for real-time market data.

    For LIVE trading: requires private_key for order signing.
    For PAPER/read-only: works without credentials using HTTP endpoints.
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

        # Track traded markets to avoid double-trading
        self._traded_markets = set()

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

    # ── Market Discovery ─────────────────────────────────────────────

    async def get_clob_markets(self) -> list[dict]:
        """
        Fetch active markets from CLOB /sampling-markets and /markets endpoints.
        These are the real CLOB discovery endpoints (not /books which doesn't exist).
        """
        all_markets = []

        # Try CLOB /sampling-simplified-markets first (featured/active)
        for endpoint in ["/sampling-simplified-markets", "/sampling-markets"]:
            try:
                resp = await self.client.get(
                    f"{POLYMARKET_CLOB_URL}{endpoint}",
                    params={"next_cursor": "LQ=="},
                )
                resp.raise_for_status()
                data = resp.json()
                markets = data if isinstance(data, list) else data.get("data", [])
                if markets:
                    logger.info(f"CLOB {endpoint} returned {len(markets)} markets")
                    all_markets.extend(markets)
                    break
            except Exception as e:
                logger.warning(f"CLOB {endpoint} failed: {e}")

        return all_markets

    async def get_btc_5min_market(self) -> Optional[dict]:
        """
        Find the current active BTC 5min UP/DOWN market.
        Strategy:
        1. Try CLOB sampling endpoints for real-time data
        2. Try Gamma API search as fallback
        3. If no market found at all, return None
        """
        # Try CLOB first
        clob_markets = await self.get_clob_markets()
        result = self._find_btc_5min_in_markets(clob_markets, source="clob")
        if result:
            return result

        # Fallback to Gamma API (broader search)
        logger.info("No BTC 5min market in CLOB, trying Gamma API")
        return await self._get_btc_5min_from_gamma()

    def _find_btc_5min_in_markets(self, markets: list[dict], source: str = "unknown") -> Optional[dict]:
        """Search a list of markets for BTC 5min UP/DOWN."""
        btc_5min_markets = []

        for book in markets:
            question = (book.get("question", "") or "").lower()

            is_btc = any(kw in question for kw in BTC_KEYWORDS)
            is_5min = any(kw in question for kw in FIVE_MIN_KEYWORDS)
            is_direction = any(kw in question for kw in DIRECTION_KEYWORDS)

            if is_btc and (is_5min or is_direction):
                threshold = self._extract_threshold(book.get("question", ""))

                tokens = book.get("tokens", [])
                yes_token = None
                no_token = None
                if isinstance(tokens, list):
                    for t in tokens:
                        outcome = (t.get("outcome", "") or "").lower()
                        if outcome in ("yes", "up"):
                            yes_token = t
                        elif outcome in ("no", "down"):
                            no_token = t

                end_time = book.get("endDate") or book.get("end_date_iso", "") or ""

                btc_5min_markets.append({
                    "id": book.get("condition_id") or book.get("id", ""),
                    "question": book.get("question", ""),
                    "description": book.get("description", ""),
                    "threshold_price": threshold,
                    "yes_token": yes_token.get("token_id", "") if yes_token else "",
                    "no_token": no_token.get("token_id", "") if no_token else "",
                    "yes_price": float(yes_token.get("price", 0.5)) if yes_token else 0.5,
                    "no_price": float(no_token.get("price", 0.5)) if no_token else 0.5,
                    "end_time": end_time,
                    "volume": float(book.get("volume", 0) or 0),
                    "liquidity": float(book.get("liquidity", 0) or 0),
                    "active": book.get("active", True),
                    "closed": book.get("closed", False),
                    "is_primary": True,
                    "source": source,
                })
                logger.info(
                    f"{source.upper()} BTC 5min: {book.get('question', '')} | "
                    f"threshold=${threshold or '?'} | end={end_time}"
                )

        if btc_5min_markets:
            btc_5min_markets.sort(key=lambda m: m.get("end_time", ""), reverse=True)
            best = btc_5min_markets[0]
            logger.info(f"Selected {source} market: {best['question']} (threshold=${best['threshold_price']})")
            return best

        return None

    async def _get_btc_5min_from_gamma(self) -> Optional[dict]:
        """Fallback: search Gamma API for BTC 5min markets."""
        search_params = [
            {"tag": "crypto", "active": "true", "closed": "false", "limit": 100},
            {"active": "true", "closed": "false", "limit": 100, "tag": "bitcoin"},
            {"active": "true", "closed": "false", "limit": 200},  # broad search
        ]
        for params in search_params:
            try:
                resp = await self.client.get(f"{GAMMA_API_BASE}/markets", params=params)
                resp.raise_for_status()
                markets = resp.json()

                # First pass: exact BTC 5min match
                for m in markets:
                    question = (m.get("question", "") or "").lower()
                    is_btc = any(kw in question for kw in BTC_KEYWORDS)
                    is_5min = any(kw in question for kw in FIVE_MIN_KEYWORDS)
                    if is_btc and is_5min:
                        normalized = self._normalize_market(m)
                        normalized["threshold_price"] = self._extract_threshold(m.get("question", ""))
                        normalized["is_primary"] = True
                        normalized["source"] = "gamma"
                        logger.info(f"Gamma found BTC 5min: {m.get('question', '')}")
                        return normalized

                # Second pass: any BTC up/down market
                for m in markets:
                    question = (m.get("question", "") or "").lower()
                    is_btc = any(kw in question for kw in BTC_KEYWORDS)
                    is_direction = any(kw in question for kw in DIRECTION_KEYWORDS)
                    if is_btc and is_direction:
                        normalized = self._normalize_market(m)
                        normalized["threshold_price"] = self._extract_threshold(m.get("question", ""))
                        normalized["is_primary"] = True
                        normalized["source"] = "gamma"
                        logger.info(f"Gamma found BTC direction market: {m.get('question', '')}")
                        return normalized

            except Exception as e:
                logger.error(f"Gamma fallback error: {e}")
        return None

    @staticmethod
    def _extract_threshold(question: str) -> Optional[float]:
        """Extract threshold/reference price from market question.
        e.g. 'BTC Up or Down from 68400' → 68400.0
        """
        if not question:
            return None
        # Try patterns: "from XXXXX", "at XXXXX", "above XXXXX", "XXXXX"
        patterns = [
            r'from\s+\$?([\d,]+\.?\d*)',
            r'at\s+\$?([\d,]+\.?\d*)',
            r'above\s+\$?([\d,]+\.?\d*)',
            r'below\s+\$?([\d,]+\.?\d*)',
            r'\$?([\d]{4,6}\.?\d*)',  # 4-6 digit number (BTC price range)
        ]
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                try:
                    val = float(match.group(1).replace(",", ""))
                    if 10000 < val < 500000:  # Sane BTC price range
                        return val
                except ValueError:
                    continue
        return None

    async def get_btc_markets(self) -> list[dict]:
        """Fetch BTC markets. Primary from CLOB, rest from Gamma."""
        btc_markets = []

        btc_5min = await self.get_btc_5min_market()
        if btc_5min:
            btc_markets.append(btc_5min)

        # Also fetch other BTC markets from Gamma for reference
        try:
            resp = await self.client.get(
                f"{GAMMA_API_BASE}/markets",
                params={"tag": "crypto", "active": "true", "closed": "false", "limit": 50},
            )
            resp.raise_for_status()
            for m in resp.json():
                question = (m.get("question", "") or "").lower()
                if any(kw in question for kw in BTC_KEYWORDS):
                    mid = m.get("id") or m.get("condition_id", "")
                    if not any(existing["id"] == mid for existing in btc_markets):
                        btc_markets.append(self._normalize_market(m))
        except Exception as e:
            logger.error(f"Gamma BTC markets fetch error: {e}")

        return btc_markets

    async def get_market_orderbook_analysis(self, yes_token: str, no_token: str = "") -> dict:
        """
        Get full orderbook analysis for a market from CLOB.
        Returns prices, spread, liquidity, and buy/sell pressure.
        """
        result = {
            "yes_price": 0.5, "no_price": 0.5,
            "spread": 0, "best_bid": 0, "best_ask": 1,
            "bid_volume": 0, "ask_volume": 0, "buy_pressure": 0.5,
            "has_liquidity": False,
        }

        book = await self.get_orderbook(yes_token)
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if bids and asks:
            result["has_liquidity"] = True
            result["best_bid"] = float(bids[0]["price"])
            result["best_ask"] = float(asks[0]["price"])
            result["spread"] = round(result["best_ask"] - result["best_bid"], 4)
            result["yes_price"] = round((result["best_bid"] + result["best_ask"]) / 2, 4)
            result["no_price"] = round(1 - result["yes_price"], 4)

            bid_vol = sum(float(b.get("size", 0)) for b in bids[:10])
            ask_vol = sum(float(a.get("size", 0)) for a in asks[:10])
            result["bid_volume"] = bid_vol
            result["ask_volume"] = ask_vol
            total = bid_vol + ask_vol
            result["buy_pressure"] = round(bid_vol / total, 4) if total > 0 else 0.5
        elif bids:
            result["best_bid"] = float(bids[0]["price"])
            result["yes_price"] = result["best_bid"]
            result["no_price"] = round(1 - result["yes_price"], 4)
        elif asks:
            result["best_ask"] = float(asks[0]["price"])
            result["yes_price"] = result["best_ask"]
            result["no_price"] = round(1 - result["yes_price"], 4)

        return result

    def mark_traded(self, market_id: str):
        """Mark a market as already traded (one trade per market)."""
        self._traded_markets.add(market_id)

    def already_traded(self, market_id: str) -> bool:
        return market_id in self._traded_markets

    def reset_traded(self):
        """Reset traded markets (new window)."""
        self._traded_markets.clear()

    async def get_all_markets(self, limit: int = 100) -> list[dict]:
        """Fetch all active markets from Gamma."""
        try:
            resp = await self.client.get(
                f"{GAMMA_API_BASE}/markets",
                params={"active": "true", "closed": "false", "limit": limit},
            )
            resp.raise_for_status()
            return [self._normalize_market(m) for m in resp.json()]
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
