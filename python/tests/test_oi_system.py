"""
Test Suite — OI Trading System
================================
Run: pytest python/tests/ -v --tb=short
"""

import json
import math
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Adjust import path when running from project root
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from python.core.oi_fetcher       import OISnapshot, BinanceOIProvider, OIFetcher
from python.core.oi_processor     import OIValidator, TrendClassifier, OIProcessor
from python.core.signal_publisher import JSONSignalPublisher, SQLiteSignalLogger, SignalPublisher
from python.core.oi_processor     import OIMetrics


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _snapshot(oi=50000.0, price=40000.0, symbol="BTCUSDT", source="test") -> OISnapshot:
    return OISnapshot(
        symbol=symbol,
        timestamp=datetime.now(tz=timezone.utc),
        open_interest=oi,
        open_interest_usd=oi * price,
        price=price,
        source=source,
    )


def _metrics(signal="BUY", oi_chg=1.5, px_chg=0.3) -> OIMetrics:
    return OIMetrics(
        symbol="BTCUSDT",
        timestamp=datetime.now(tz=timezone.utc),
        current_oi=51000.0,
        previous_oi=50000.0,
        oi_change_abs=1000.0,
        oi_change_pct=oi_chg,
        current_price=40120.0,
        previous_price=40000.0,
        price_change_pct=px_chg,
        trend_label="BULLISH_TREND",
        signal=signal,
    )


# ===========================================================================
# OISnapshot
# ===========================================================================

class TestOISnapshot:
    def test_valid_construction(self):
        s = _snapshot()
        assert s.open_interest == 50000.0
        assert s.price == 40000.0

    def test_negative_oi_raises(self):
        with pytest.raises(ValueError, match="negative"):
            OISnapshot("BTC", datetime.now(tz=timezone.utc), -1, 0, 40000, "test")

    def test_zero_price_raises(self):
        with pytest.raises(ValueError, match="positive"):
            OISnapshot("BTC", datetime.now(tz=timezone.utc), 100, 0, 0, "test")


# ===========================================================================
# OIValidator
# ===========================================================================

class TestOIValidator:
    def setup_method(self):
        self.v = OIValidator()

    def test_clean_snapshot_no_warnings(self):
        s    = _snapshot(oi=50000, price=40000)
        prev = _snapshot(oi=49800, price=39950)
        assert self.v.validate(s, prev) == []

    def test_oi_jump_warning(self):
        s    = _snapshot(oi=100000)   # 100% jump
        prev = _snapshot(oi=50000)
        warns = self.v.validate(s, prev)
        assert any("OI jump" in w for w in warns)

    def test_price_jump_warning(self):
        s    = _snapshot(price=60000)  # 50% jump
        prev = _snapshot(price=40000)
        warns = self.v.validate(s, prev)
        assert any("Price jump" in w for w in warns)

    def test_low_liquidity_raises(self):
        s = _snapshot(oi=10, price=100)   # $1000 notional
        with pytest.raises(ValueError, match="liquidity floor"):
            self.v.validate(s)

    def test_first_snapshot_no_previous(self):
        s = _snapshot()
        warns = self.v.validate(s, None)
        assert warns == []


# ===========================================================================
# TrendClassifier
# ===========================================================================

class TestTrendClassifier:
    def setup_method(self):
        self.c = TrendClassifier(oi_threshold_pct=0.5, price_threshold_pct=0.1)

    @pytest.mark.parametrize("oi_chg,px_chg,expected_trend,expected_signal", [
        ( 1.0,  0.5,  "BULLISH_TREND",    "BUY"),
        ( 1.0, -0.5,  "BEARISH_TREND",    "SELL"),
        (-1.0,  0.5,  "SHORT_COVERING",   "BUY"),
        (-1.0, -0.5,  "LONG_LIQUIDATION", "SELL"),
        ( 0.1,  0.05, "NEUTRAL",          "NEUTRAL"),
    ])
    def test_matrix(self, oi_chg, px_chg, expected_trend, expected_signal):
        trend, signal = self.c.classify(oi_chg, px_chg)
        assert trend  == expected_trend
        assert signal == expected_signal

    def test_boundary_at_threshold_neutral(self):
        # Exactly at threshold — should be NEUTRAL (not strictly greater)
        trend, signal = self.c.classify(0.5, 0.1)
        assert trend == "NEUTRAL"


# ===========================================================================
# OIProcessor
# ===========================================================================

class TestOIProcessor:
    def setup_method(self):
        self.proc = OIProcessor()

    def test_first_snapshot_returns_none(self):
        s = _snapshot()
        assert self.proc.process(s) is None

    def test_second_snapshot_returns_metrics(self):
        self.proc.process(_snapshot(oi=50000, price=40000))
        metrics = self.proc.process(_snapshot(oi=51000, price=40200))
        assert metrics is not None
        assert metrics.signal in ("BUY", "SELL", "NEUTRAL")

    def test_invalid_snapshot_discarded(self):
        """Processor gracefully discards bad snapshots (returns None, no raise)."""
        self.proc.process(_snapshot(oi=50000, price=40000))
        # oi < 0 fails OISnapshot.__post_init__
        with pytest.raises(ValueError):
            _snapshot(oi=-1)

        # A snapshot that passes construction but fails validator (too small notional)
        tiny = OISnapshot("BTCUSDT", datetime.now(tz=timezone.utc), 1.0, 100.0, 100.0, "test")
        result = self.proc.process(tiny)
        assert result is None   # discarded, no exception propagated

    def test_buffer_max_size(self):
        proc = OIProcessor(buffer_size=5)
        for i in range(10):
            proc.process(_snapshot(oi=50000 + i * 10, price=40000))
        assert len(proc._buffer) == 5

    def test_process_dataframe_bulk(self):
        dates  = pd.date_range("2024-01-01", periods=20, freq="5min", tz="UTC")
        oi_ser = [50000 + i * 100 for i in range(20)]
        px_ser = [40000 + i * 10  for i in range(20)]
        df = pd.DataFrame({"open_interest": oi_ser, "price": px_ser}, index=dates)

        result = self.proc.process_dataframe(df, "BTCUSDT")
        assert "signal"      in result.columns
        assert "trend_label" in result.columns
        # First row has NaN previous — skip; rest should have signals
        assert result["signal"].iloc[1:].notna().all()

    def test_dataframe_missing_column_raises(self):
        df = pd.DataFrame({"open_interest": [1, 2, 3]})
        with pytest.raises(ValueError, match="missing columns"):
            self.proc.process_dataframe(df, "BTC")


# ===========================================================================
# JSONSignalPublisher
# ===========================================================================

class TestJSONSignalPublisher:
    def test_publish_creates_valid_json(self, tmp_path):
        pub = JSONSignalPublisher(tmp_path / "signal.json")
        pub.publish(_metrics())
        data = json.loads((tmp_path / "signal.json").read_text())
        assert data["signal"] in ("BUY", "SELL", "NEUTRAL")
        assert "schema_version" in data
        assert "timestamp" in data

    def test_atomic_write(self, tmp_path):
        """Concurrent writes should not corrupt the file."""
        pub = JSONSignalPublisher(tmp_path / "signal.json")
        errors = []

        def _write():
            try:
                pub.publish(_metrics())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors
        data = json.loads((tmp_path / "signal.json").read_text())
        assert "signal" in data

    def test_read_latest_roundtrip(self, tmp_path):
        pub = JSONSignalPublisher(tmp_path / "signal.json")
        pub.publish(_metrics(signal="SELL"))
        latest = pub.read_latest()
        assert latest["signal"] == "SELL"


# ===========================================================================
# SQLiteSignalLogger
# ===========================================================================

class TestSQLiteSignalLogger:
    def test_log_and_tail(self, tmp_path):
        db  = SQLiteSignalLogger(tmp_path / "test.db")
        db.log(_metrics(signal="BUY"),  source="binance")
        db.log(_metrics(signal="SELL"), source="bybit")
        rows = db.tail("BTCUSDT", n=10)
        assert len(rows) == 2
        assert rows[0]["signal"] == "SELL"   # DESC order
        assert rows[1]["signal"] == "BUY"

    def test_thread_safety(self, tmp_path):
        db = SQLiteSignalLogger(tmp_path / "threaded.db")
        errors = []

        def _insert():
            try:
                db.log(_metrics())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_insert) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors
        rows = db.tail("BTCUSDT", 100)
        assert len(rows) == 10


# ===========================================================================
# OIFetcher (mocked HTTP)
# ===========================================================================

class TestOIFetcherMocked:
    """Integration-style tests with mocked HTTP responses."""

    BINANCE_OI_RESP   = {"openInterest": "42500.50", "time": 1705312200000, "symbol": "BTCUSDT"}
    BINANCE_TICK_RESP = {"price": "43200.00", "symbol": "BTCUSDT"}

    def _mock_session_get(self, url, params=None, timeout=10):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        if "openInterest" in url and "fapi" in url:
            resp.json.return_value = self.BINANCE_OI_RESP
        elif "ticker/price" in url:
            resp.json.return_value = self.BINANCE_TICK_RESP
        return resp

    def test_binance_provider_happy_path(self):
        provider = BinanceOIProvider()
        provider._session.get = self._mock_session_get

        snap = provider.fetch("BTCUSDT")
        assert snap.source == "binance"
        assert math.isclose(snap.open_interest, 42500.50, rel_tol=1e-6)
        assert math.isclose(snap.price, 43200.0, rel_tol=1e-6)

    def test_fetcher_falls_back_on_primary_failure(self):
        """When Binance raises, Bybit should be tried."""
        primary_fail = MagicMock()
        primary_fail.fetch.side_effect = RuntimeError("Network timeout")

        good_snap = _snapshot(source="bybit")
        fallback_ok = MagicMock()
        fallback_ok.fetch.return_value = good_snap

        fetcher = OIFetcher(providers=[primary_fail, fallback_ok])
        result  = fetcher.fetch("BTCUSDT")
        assert result.source == "bybit"

    def test_fetcher_raises_when_all_fail(self):
        bad1 = MagicMock(); bad1.fetch.side_effect = RuntimeError("fail")
        bad2 = MagicMock(); bad2.fetch.side_effect = RuntimeError("fail")
        fetcher = OIFetcher(providers=[bad1, bad2])
        with pytest.raises(RuntimeError, match="All OI providers failed"):
            fetcher.fetch("BTCUSDT")


# ===========================================================================
# End-to-end integration test (no real network)
# ===========================================================================

class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        fetcher   = OIFetcher(providers=[])   # no providers
        processor = OIProcessor()
        publisher = SignalPublisher(
            signal_path = tmp_path / "signal.json",
            db_path     = tmp_path / "signals.db",
        )

        # Inject mock provider
        good = MagicMock()
        good.fetch.side_effect = [
            _snapshot(oi=50000, price=40000),
            _snapshot(oi=51500, price=40400),  # bullish: OI+3%, Px+1%
        ]
        fetcher._providers = [good]

        # First call — no metrics yet
        snap = fetcher.fetch("BTCUSDT")
        m    = processor.process(snap)
        assert m is None

        # Second call — metrics available
        snap2 = fetcher.fetch("BTCUSDT")
        m2    = processor.process(snap2)
        assert m2 is not None
        assert m2.signal == "BUY"
        assert m2.trend_label == "BULLISH_TREND"

        publisher.publish(m2, source="mock")
        rows = publisher.db_logger.tail("BTCUSDT", 10)
        assert len(rows) == 1
        assert rows[0]["signal"] == "BUY"

        latest = publisher.json_publisher.read_latest()
        assert latest["trend_label"] == "BULLISH_TREND"
