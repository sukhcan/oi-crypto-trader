"""
Signal Publisher
================
Serialises OIMetrics into a JSON signal file consumed by the MQL5 EA
via FileReadJSON / custom file-poll mechanism.

Also maintains a rolling SQLite log of all signals for audit/backtest.
"""

import json
import logging
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .oi_processor import OIMetrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON Signal File (polled by MQL5 EA)
# ---------------------------------------------------------------------------

class JSONSignalPublisher:
    """
    Atomically writes the latest OIMetrics to a JSON file.
    MQL5 EA polls this file on every tick / timer event.

    File schema:
    {
        "symbol":           "BTCUSDT",
        "timestamp":        "2024-01-15T10:30:00+00:00",
        "signal":           "BUY",
        "trend_label":      "BULLISH_TREND",
        "current_oi":       42500.0,
        "previous_oi":      41800.0,
        "oi_change_abs":    700.0,
        "oi_change_pct":    1.674,
        "current_price":    43250.0,
        "price_change_pct": 0.35,
        "schema_version":   1,
        "published_at":     "2024-01-15T10:30:01+00:00"
    }
    """

    SCHEMA_VERSION = 1

    def __init__(self, output_path: str | Path = "oi_signal.json"):
        self._path = Path(output_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def publish(self, metrics: OIMetrics) -> None:
        payload = {
            "schema_version":   self.SCHEMA_VERSION,
            "symbol":           metrics.symbol,
            "timestamp":        metrics.timestamp.isoformat(),
            "signal":           metrics.signal,
            "trend_label":      metrics.trend_label,
            "current_oi":       round(metrics.current_oi,        4),
            "previous_oi":      round(metrics.previous_oi,       4),
            "oi_change_abs":    round(metrics.oi_change_abs,     4),
            "oi_change_pct":    round(metrics.oi_change_pct,     6),
            "current_price":    round(metrics.current_price,     4),
            "previous_price":   round(metrics.previous_price,    4),
            "price_change_pct": round(metrics.price_change_pct,  6),
            "published_at":     datetime.now(tz=timezone.utc).isoformat(),
        }

        tmp = self._path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self._path)   # atomic rename — no partial reads by EA

        logger.info(
            "[publisher] Signal written: %s %s OI_chg=%.2f%% Px_chg=%.2f%%",
            metrics.signal, metrics.symbol,
            metrics.oi_change_pct, metrics.price_change_pct,
        )

    def read_latest(self) -> Optional[dict]:
        """Utility for testing — read back the last published signal."""
        if not self._path.exists():
            return None
        with self._lock:
            return json.loads(self._path.read_text())


# ---------------------------------------------------------------------------
# SQLite audit log
# ---------------------------------------------------------------------------

class SQLiteSignalLogger:
    """
    Persists every emitted signal to SQLite for post-trade analysis.
    Thread-safe via connection-per-thread pattern.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS oi_signals (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol           TEXT    NOT NULL,
        bar_timestamp    TEXT    NOT NULL,
        published_at     TEXT    NOT NULL,
        signal           TEXT    NOT NULL,
        trend_label      TEXT    NOT NULL,
        current_oi       REAL,
        previous_oi      REAL,
        oi_change_abs    REAL,
        oi_change_pct    REAL,
        current_price    REAL,
        previous_price   REAL,
        price_change_pct REAL,
        source           TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_symbol_ts ON oi_signals(symbol, bar_timestamp);
    """

    def __init__(self, db_path: str | Path = "oi_signals.db"):
        self._db_path = str(db_path)
        self._local   = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._db_path, check_same_thread=False)
        return self._local.conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.executescript(self.DDL)
        conn.commit()
        conn.close()

    def log(self, metrics: OIMetrics, source: str = "") -> None:
        row = (
            metrics.symbol,
            metrics.timestamp.isoformat(),
            datetime.now(tz=timezone.utc).isoformat(),
            metrics.signal,
            metrics.trend_label,
            metrics.current_oi,
            metrics.previous_oi,
            metrics.oi_change_abs,
            metrics.oi_change_pct,
            metrics.current_price,
            metrics.previous_price,
            metrics.price_change_pct,
            source,
        )
        self._conn().execute(
            """INSERT INTO oi_signals
               (symbol, bar_timestamp, published_at, signal, trend_label,
                current_oi, previous_oi, oi_change_abs, oi_change_pct,
                current_price, previous_price, price_change_pct, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )
        self._conn().commit()

    def tail(self, symbol: str, n: int = 20):
        """Return last N signals as list of dicts (useful for dashboards)."""
        cur = self._conn().execute(
            "SELECT * FROM oi_signals WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, n),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Combined publisher facade
# ---------------------------------------------------------------------------

class SignalPublisher:
    """Single entry-point used by the main loop."""

    def __init__(
        self,
        signal_path: str | Path = "signals/oi_signal.json",
        db_path:     str | Path = "signals/oi_signals.db",
    ):
        self._json   = JSONSignalPublisher(signal_path)
        self._sqlite = SQLiteSignalLogger(db_path)

    def publish(self, metrics: OIMetrics, source: str = "") -> None:
        self._json.publish(metrics)
        self._sqlite.log(metrics, source)

    @property
    def json_publisher(self) -> JSONSignalPublisher:
        return self._json

    @property
    def db_logger(self) -> SQLiteSignalLogger:
        return self._sqlite
