"""
Open Interest Metrics Processor
================================
Validates raw snapshots, computes derived metrics, and classifies
market regime using a price × OI matrix (analogous to CME 6E COT analysis).

Trend Matrix (standard futures interpretation):
┌───────────────┬─────────────────────┬──────────────────────┐
│               │   OI Rising         │   OI Falling         │
├───────────────┼─────────────────────┼──────────────────────┤
│ Price Rising  │ BULLISH TREND       │ SHORT COVERING       │
│ Price Falling │ BEARISH TREND       │ LONG LIQUIDATION     │
└───────────────┴─────────────────────┴──────────────────────┘
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from .oi_fetcher import OISnapshot, OIMetrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class OIValidator:
    """Sanity-checks an OISnapshot before it enters the processing pipeline."""

    # Max tolerated single-step OI jump (e.g. 50% in one 5-min bar = data error)
    MAX_OI_CHANGE_PCT: float = 50.0
    # Max tolerated single-step price move
    MAX_PRICE_CHANGE_PCT: float = 20.0
    # Minimum USD notional to consider the market liquid
    MIN_OI_USD: float = 1_000_000.0   # $1M

    def validate(self, snapshot: OISnapshot, previous: Optional[OISnapshot] = None) -> list[str]:
        """
        Returns a list of warning strings (empty = clean).
        Raises ValueError for hard failures that must abort processing.
        """
        warnings: list[str] = []

        # Hard checks
        if snapshot.open_interest <= 0:
            raise ValueError(f"Non-positive OI: {snapshot.open_interest}")
        if snapshot.price <= 0:
            raise ValueError(f"Non-positive price: {snapshot.price}")
        if snapshot.open_interest_usd < self.MIN_OI_USD:
            raise ValueError(
                f"OI USD {snapshot.open_interest_usd:,.0f} below liquidity floor "
                f"{self.MIN_OI_USD:,.0f}"
            )

        # Soft checks vs previous snapshot
        if previous is not None:
            oi_chg = abs(snapshot.open_interest - previous.open_interest) / (
                previous.open_interest + 1e-12
            ) * 100
            px_chg = abs(snapshot.price - previous.price) / (previous.price + 1e-12) * 100

            if oi_chg > self.MAX_OI_CHANGE_PCT:
                warnings.append(
                    f"OI jump {oi_chg:.1f}% exceeds threshold {self.MAX_OI_CHANGE_PCT}%"
                )
            if px_chg > self.MAX_PRICE_CHANGE_PCT:
                warnings.append(
                    f"Price jump {px_chg:.1f}% exceeds threshold {self.MAX_PRICE_CHANGE_PCT}%"
                )

        return warnings


# ---------------------------------------------------------------------------
# Trend Classifier
# ---------------------------------------------------------------------------

class TrendClassifier:
    """
    Implements the price × OI matrix plus momentum extensions.

    OI threshold: change must exceed `oi_threshold_pct` to count as directional.
    Price threshold: same logic for price.
    """

    def __init__(
        self,
        oi_threshold_pct: float = 0.5,
        price_threshold_pct: float = 0.1,
    ):
        self.oi_threshold_pct    = oi_threshold_pct
        self.price_threshold_pct = price_threshold_pct

    def classify(
        self,
        oi_change_pct: float,
        price_change_pct: float,
    ) -> tuple[str, str]:
        """
        Returns (trend_label, signal).
        signal in {BUY, SELL, NEUTRAL}.
        """
        oi_up    = oi_change_pct    >  self.oi_threshold_pct
        oi_down  = oi_change_pct    < -self.oi_threshold_pct
        px_up    = price_change_pct >  self.price_threshold_pct
        px_down  = price_change_pct < -self.price_threshold_pct

        if px_up and oi_up:
            return "BULLISH_TREND", "BUY"
        elif px_up and oi_down:
            return "SHORT_COVERING", "BUY"
        elif px_down and oi_up:
            return "BEARISH_TREND", "SELL"
        elif px_down and oi_down:
            return "LONG_LIQUIDATION", "SELL"
        else:
            return "NEUTRAL", "NEUTRAL"


# ---------------------------------------------------------------------------
# Main Processor
# ---------------------------------------------------------------------------

class OIProcessor:
    """
    Orchestrates validation → metric computation → classification.
    Maintains an internal rolling buffer for time-series analysis.
    """

    def __init__(
        self,
        validator: OIValidator = None,
        classifier: TrendClassifier = None,
        buffer_size: int = 500,
    ):
        self._validator  = validator  or OIValidator()
        self._classifier = classifier or TrendClassifier()
        self._buffer: list[OISnapshot] = []        # ring buffer of clean snapshots
        self._buffer_size = buffer_size

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def process(self, snapshot: OISnapshot) -> Optional[OIMetrics]:
        """
        Validate snapshot, append to buffer, compute metrics vs last bar.
        Returns None on the very first bar (no previous to compare against)
        or when validation raises a hard error.
        """
        previous = self._buffer[-1] if self._buffer else None

        # Validate
        try:
            warnings = self._validator.validate(snapshot, previous)
            for w in warnings:
                logger.warning("[%s] Validation warning: %s", snapshot.symbol, w)
        except ValueError as e:
            logger.error("[%s] Validation FAILED — snapshot discarded: %s", snapshot.symbol, e)
            return None

        # Buffer management
        self._buffer.append(snapshot)
        if len(self._buffer) > self._buffer_size:
            self._buffer.pop(0)

        # Need at least 2 snapshots for metrics
        if previous is None:
            logger.debug("[%s] First snapshot; no metrics yet.", snapshot.symbol)
            return None

        return self._compute_metrics(snapshot, previous)

    def process_dataframe(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Bulk-process a historical OI DataFrame.

        Expected columns: open_interest, price  (open_interest_usd optional)
        Index: DatetimeTZAware

        Returns DataFrame with all OIMetrics fields appended.
        """
        df = df.copy().sort_index()
        self._validate_dataframe(df)
        df = self._cleanse_dataframe(df)
        return self._compute_dataframe_metrics(df, symbol)

    def get_buffer_df(self) -> pd.DataFrame:
        """Export current buffer as a DataFrame for inspection / backtest."""
        if not self._buffer:
            return pd.DataFrame()
        records = [
            {
                "timestamp": s.timestamp,
                "symbol": s.symbol,
                "open_interest": s.open_interest,
                "open_interest_usd": s.open_interest_usd,
                "price": s.price,
                "source": s.source,
            }
            for s in self._buffer
        ]
        return pd.DataFrame(records).set_index("timestamp")

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _compute_metrics(self, current: OISnapshot, previous: OISnapshot) -> OIMetrics:
        oi_change_abs = current.open_interest - previous.open_interest
        oi_change_pct = oi_change_abs / (previous.open_interest + 1e-12) * 100
        px_change_pct = (current.price - previous.price) / (previous.price + 1e-12) * 100

        trend, signal = self._classifier.classify(oi_change_pct, px_change_pct)

        return OIMetrics(
            symbol=current.symbol,
            timestamp=current.timestamp,
            current_oi=current.open_interest,
            previous_oi=previous.open_interest,
            oi_change_abs=oi_change_abs,
            oi_change_pct=oi_change_pct,
            current_price=current.price,
            previous_price=previous.price,
            price_change_pct=px_change_pct,
            trend_label=trend,
            signal=signal,
        )

    # ---------- DataFrame helpers ----------

    def _validate_dataframe(self, df: pd.DataFrame) -> None:
        required = {"open_interest", "price"}
        missing  = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")
        if not isinstance(df.index, pd.DatetimeTZIndex if hasattr(pd, 'DatetimeTZIndex') else type(df.index)):
            pass  # allow naive index with warning
        if df.empty:
            raise ValueError("DataFrame is empty")

    def _cleanse_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        n_before = len(df)
        # Drop rows with non-positive OI or price
        df = df[(df["open_interest"] > 0) & (df["price"] > 0)]
        # Drop extreme OI jumps (data errors)
        oi_pct_chg = df["open_interest"].pct_change().abs() * 100
        df = df[oi_pct_chg <= self._validator.MAX_OI_CHANGE_PCT]
        # Fill gaps with forward fill (max 3 periods)
        df = df.ffill(limit=3)
        # Drop remaining NaNs
        df = df.dropna(subset=["open_interest", "price"])

        n_after = len(df)
        if n_before != n_after:
            logger.info("Cleansing removed %d rows (%d → %d)", n_before - n_after, n_before, n_after)
        return df

    def _compute_dataframe_metrics(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df["previous_oi"]       = df["open_interest"].shift(1)
        df["oi_change_abs"]     = df["open_interest"] - df["previous_oi"]
        df["oi_change_pct"]     = df["oi_change_abs"] / (df["previous_oi"] + 1e-12) * 100
        df["previous_price"]    = df["price"].shift(1)
        df["price_change_pct"]  = (df["price"] - df["previous_price"]) / (
            df["previous_price"] + 1e-12
        ) * 100

        # Vectorised trend classification
        conditions = [
            (df["price_change_pct"] >  self._classifier.price_threshold_pct) & (df["oi_change_pct"] >  self._classifier.oi_threshold_pct),
            (df["price_change_pct"] >  self._classifier.price_threshold_pct) & (df["oi_change_pct"] < -self._classifier.oi_threshold_pct),
            (df["price_change_pct"] < -self._classifier.price_threshold_pct) & (df["oi_change_pct"] >  self._classifier.oi_threshold_pct),
            (df["price_change_pct"] < -self._classifier.price_threshold_pct) & (df["oi_change_pct"] < -self._classifier.oi_threshold_pct),
        ]
        trend_labels = ["BULLISH_TREND", "SHORT_COVERING", "BEARISH_TREND", "LONG_LIQUIDATION"]
        signals      = ["BUY",           "BUY",            "SELL",          "SELL"]

        df["trend_label"] = np.select(conditions, trend_labels, default="NEUTRAL")
        df["signal"]      = np.select(conditions, signals,      default="NEUTRAL")
        df["symbol"]      = symbol

        return df
