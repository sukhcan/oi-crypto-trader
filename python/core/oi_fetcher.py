"""
Open Interest Data Fetcher for Crypto Futures
=============================================
Primary: Binance/Bybit perpetual futures OI endpoints
Fallback: CoinGlass aggregated OI data (COT-equivalent for crypto)

Author: OI Trading System
Version: 1.0.0
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class OISnapshot:
    """Immutable snapshot of Open Interest for one symbol at one timestamp."""
    symbol: str
    timestamp: datetime
    open_interest: float          # contracts / native units
    open_interest_usd: float      # USD notional
    price: float                  # mark price at snapshot time
    source: str                   # which API delivered this record
    raw: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.open_interest < 0:
            raise ValueError(f"OI cannot be negative: {self.open_interest}")
        if self.price <= 0:
            raise ValueError(f"Price must be positive: {self.price}")


@dataclass
class OIMetrics:
    """Derived metrics computed from two consecutive OI snapshots."""
    symbol: str
    timestamp: datetime
    current_oi: float
    previous_oi: float
    oi_change_abs: float
    oi_change_pct: float
    current_price: float
    previous_price: float
    price_change_pct: float
    trend_label: str              # see TrendClassifier
    signal: str                   # BUY / SELL / NEUTRAL


# ---------------------------------------------------------------------------
# HTTP session with retry/backoff
# ---------------------------------------------------------------------------

def _build_session(retries: int = 3, backoff: float = 1.5) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Accept": "application/json", "User-Agent": "OITradingSystem/1.0"})
    return session


# ---------------------------------------------------------------------------
# Abstract base provider
# ---------------------------------------------------------------------------

class OIProvider(ABC):
    """All data providers implement this contract."""

    name: str = "base"
    TIMEOUT: int = 10

    def __init__(self):
        self._session = _build_session()

    @abstractmethod
    def fetch(self, symbol: str) -> OISnapshot:
        ...

    def _get(self, url: str, params: dict = None) -> dict:
        try:
            resp = self._session.get(url, params=params, timeout=self.TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.warning("[%s] HTTP error %s for %s", self.name, e.response.status_code, url)
            raise
        except requests.exceptions.RequestException as e:
            logger.warning("[%s] Request failed: %s", self.name, e)
            raise


# ---------------------------------------------------------------------------
# Primary Provider — Binance USDT-M Futures
# ---------------------------------------------------------------------------

class BinanceOIProvider(OIProvider):
    name = "binance"
    BASE = "https://fapi.binance.com/fapi/v1"

    def fetch(self, symbol: str) -> OISnapshot:
        symbol_u = symbol.upper().replace("-", "")   # e.g. BTCUSDT
        oi_data   = self._get(f"{self.BASE}/openInterest", {"symbol": symbol_u})
        tick_data = self._get(f"{self.BASE}/ticker/price", {"symbol": symbol_u})

        oi_val   = float(oi_data["openInterest"])
        price    = float(tick_data["price"])
        ts       = datetime.fromtimestamp(oi_data["time"] / 1000, tz=timezone.utc)

        return OISnapshot(
            symbol=symbol,
            timestamp=ts,
            open_interest=oi_val,
            open_interest_usd=oi_val * price,
            price=price,
            source=self.name,
            raw=oi_data,
        )


# ---------------------------------------------------------------------------
# Secondary Provider — Bybit USDT Perpetuals
# ---------------------------------------------------------------------------

class BybitOIProvider(OIProvider):
    name = "bybit"
    BASE = "https://api.bybit.com/v5/market"

    def fetch(self, symbol: str) -> OISnapshot:
        symbol_u = symbol.upper().replace("-", "")
        data = self._get(
            f"{self.BASE}/open-interest",
            {"category": "linear", "symbol": symbol_u, "intervalTime": "5min", "limit": 1},
        )
        if data.get("retCode") != 0:
            raise ValueError(f"Bybit API error: {data.get('retMsg')}")

        record = data["result"]["list"][0]
        ts_data = self._get(f"{self.BASE}/tickers", {"category": "linear", "symbol": symbol_u})
        price  = float(ts_data["result"]["list"][0]["markPrice"])

        oi_val = float(record["openInterest"])
        ts     = datetime.fromtimestamp(int(record["timestamp"]) / 1000, tz=timezone.utc)

        return OISnapshot(
            symbol=symbol,
            timestamp=ts,
            open_interest=oi_val,
            open_interest_usd=oi_val * price,
            price=price,
            source=self.name,
            raw=record,
        )


# ---------------------------------------------------------------------------
# Fallback Provider — CoinGlass (COT-equivalent aggregator)
# ---------------------------------------------------------------------------

class CoinGlassOIProvider(OIProvider):
    """
    CoinGlass aggregates OI across all major exchanges — analogous to CFTC COT
    in that it gives a consolidated market-wide view rather than single-venue data.

    Requires a free API key from https://www.coinglass.com/pricing
    Set env var COINGLASS_API_KEY or pass api_key=... to constructor.
    """
    name = "coinglass"
    BASE = "https://open-api.coinglass.com/public/v2"

    def __init__(self, api_key: str = ""):
        super().__init__()
        import os
        self._key = api_key or os.getenv("COINGLASS_API_KEY", "")
        if not self._key:
            logger.warning("[coinglass] No API key — fallback provider may return 401")

    def fetch(self, symbol: str) -> OISnapshot:
        coin = symbol.upper().replace("USDT", "").replace("USD", "").replace("-", "")
        data = self._get(
            f"{self.BASE}/open_interest",
            {"symbol": coin},
        )
        if data.get("code") != "0":
            raise ValueError(f"CoinGlass error: {data.get('msg')}")

        # Sum across all exchanges for total market OI
        records = data["data"]
        total_oi_usd = sum(float(r.get("openInterestUsd", 0)) for r in records)
        # Use average price across venues as best estimate
        prices = [float(r["price"]) for r in records if r.get("price")]
        price  = sum(prices) / len(prices) if prices else 0.0

        if price == 0:
            raise ValueError("CoinGlass returned zero price — skipping")

        return OISnapshot(
            symbol=symbol,
            timestamp=datetime.now(tz=timezone.utc),
            open_interest=total_oi_usd / price,    # approximate contracts
            open_interest_usd=total_oi_usd,
            price=price,
            source=self.name,
            raw={"venues": len(records), "total_oi_usd": total_oi_usd},
        )


# ---------------------------------------------------------------------------
# Resilient fetcher with provider chain
# ---------------------------------------------------------------------------

class OIFetcher:
    """
    Tries providers in priority order; returns first successful snapshot.
    Raises RuntimeError only when ALL providers fail.
    """

    def __init__(self, providers: list[OIProvider] = None, coinglass_key: str = ""):
        self._providers: list[OIProvider] = providers or [
            BinanceOIProvider(),
            BybitOIProvider(),
            CoinGlassOIProvider(api_key=coinglass_key),
        ]

    def fetch(self, symbol: str) -> OISnapshot:
        last_err = None
        for provider in self._providers:
            try:
                snapshot = provider.fetch(symbol)
                logger.info("[%s] OI fetched: %s OI=%.2f price=%.2f",
                            provider.name, symbol, snapshot.open_interest, snapshot.price)
                return snapshot
            except Exception as exc:
                logger.warning("[%s] Failed for %s: %s — trying next provider",
                               provider.name, symbol, exc)
                last_err = exc
        raise RuntimeError(
            f"All OI providers failed for {symbol}. Last error: {last_err}"
        )

    def fetch_history(
        self, symbol: str, interval: str = "5m", limit: int = 100
    ) -> pd.DataFrame:
        """
        Fetch historical OI from Binance (primary); falls back to Bybit.
        Returns DataFrame indexed by timestamp with columns:
            open_interest, open_interest_usd, price, source
        """
        rows = self._binance_history(symbol, interval, limit)
        if rows is None:
            rows = self._bybit_history(symbol, interval, limit)
        if rows is None:
            raise RuntimeError(f"Historical OI unavailable for {symbol}")
        return rows

    # -- private helpers -------------------------------------------------

    def _binance_history(self, symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
        try:
            session = _build_session()
            symbol_u = symbol.upper().replace("-", "")
            resp = session.get(
                "https://fapi.binance.com/futures/data/openInterestHist",
                params={"symbol": symbol_u, "period": interval, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df.rename(columns={"sumOpenInterest": "open_interest",
                                "sumOpenInterestValue": "open_interest_usd"}, inplace=True)
            df[["open_interest", "open_interest_usd"]] = df[
                ["open_interest", "open_interest_usd"]
            ].astype(float)
            df["price"] = df["open_interest_usd"] / df["open_interest"]
            df["source"] = "binance_hist"
            return df[["open_interest", "open_interest_usd", "price", "source"]]
        except Exception as e:
            logger.warning("Binance history failed: %s", e)
            return None

    def _bybit_history(self, symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
        try:
            session = _build_session()
            symbol_u = symbol.upper().replace("-", "")
            resp = session.get(
                "https://api.bybit.com/v5/market/open-interest",
                params={"category": "linear", "symbol": symbol_u,
                        "intervalTime": interval, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            records = data["result"]["list"]
            df = pd.DataFrame(records)
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df.rename(columns={"openInterest": "open_interest"}, inplace=True)
            df["open_interest"] = df["open_interest"].astype(float)
            df["open_interest_usd"] = float("nan")
            df["price"]  = float("nan")
            df["source"] = "bybit_hist"
            return df[["open_interest", "open_interest_usd", "price", "source"]]
        except Exception as e:
            logger.warning("Bybit history failed: %s", e)
            return None
