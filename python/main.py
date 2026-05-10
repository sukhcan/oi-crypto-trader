"""
OI Trading System — Main Orchestrator
======================================
Async polling loop: fetch → validate → process → publish → sleep.

Usage:
    python -m python.main --symbol BTCUSDT --interval 30 --log-level INFO

Environment variables:
    COINGLASS_API_KEY   CoinGlass fallback provider key
    OI_SIGNAL_PATH      Override default signal JSON path
    OI_DB_PATH          Override default SQLite path
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from python.core.oi_fetcher    import OIFetcher
from python.core.oi_processor  import OIProcessor, TrendClassifier, OIValidator
from python.core.signal_publisher import SignalPublisher

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("oi_system.log", mode="a"),
        ],
    )

logger = logging.getLogger("oi_main")


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_SHUTDOWN = asyncio.Event()

def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    pass

# ---------------------------------------------------------------------------
# Core polling coroutine
# ---------------------------------------------------------------------------

async def poll_once(
    symbol:    str,
    fetcher:   OIFetcher,
    processor: OIProcessor,
    publisher: SignalPublisher,
    source:    str = "",
) -> bool:
    """Fetch → process → publish one OI update. Returns True on success."""
    loop = asyncio.get_running_loop()
    try:
        # Run blocking I/O in thread pool so event loop stays responsive
        snapshot = await loop.run_in_executor(None, fetcher.fetch, symbol)
    except RuntimeError as e:
        logger.error("All providers exhausted: %s", e)
        return False

    metrics = processor.process(snapshot)
    if metrics is None:
        logger.debug("No metrics yet (first snapshot or validation failure).")
        return True   # not an error — first bar

    publisher.publish(metrics, source=snapshot.source)
    logger.info(
        ">> %s | %s | OI change %.2f pct | Px change %.3f pct | %s",
        metrics.symbol,
        metrics.trend_label,
        metrics.oi_change_pct,
        metrics.price_change_pct,
        metrics.signal,
    )
    return True


async def run_loop(
    symbol:    str,
    interval:  int,
    fetcher:   OIFetcher,
    processor: OIProcessor,
    publisher: SignalPublisher,
) -> None:
    logger.info("Starting OI polling loop | symbol=%s | interval=%ds", symbol, interval)
    consecutive_failures = 0
    MAX_FAILURES = 5

    while not _SHUTDOWN.is_set():
        success = await poll_once(symbol, fetcher, processor, publisher)

        if success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            if consecutive_failures >= MAX_FAILURES:
                logger.critical("Too many consecutive failures (%d). Halting.", MAX_FAILURES)
                _SHUTDOWN.set()
                break
            # Exponential back-off on failures
            backoff = min(interval * 2 ** consecutive_failures, 300)
            logger.warning("Backing off %ds after failure #%d", backoff, consecutive_failures)
            await asyncio.sleep(backoff)
            continue

        # Normal sleep (responsive to shutdown signal)
        try:
            await asyncio.wait_for(_SHUTDOWN.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass   # normal — keep polling

    logger.info("OI polling loop exited cleanly.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OI Trading System")
    p.add_argument("--symbol",      default="BTCUSDT",  help="Futures symbol (default: BTCUSDT)")
    p.add_argument("--interval",    type=int, default=30, help="Poll interval in seconds (default: 30)")
    p.add_argument("--log-level",   default="INFO",      help="Logging level (default: INFO)")
    p.add_argument("--signal-path", default=os.getenv("OI_SIGNAL_PATH", "signals/oi_signal.json"))
    p.add_argument("--db-path",     default=os.getenv("OI_DB_PATH",     "signals/oi_signals.db"))
    p.add_argument("--oi-threshold",   type=float, default=0.5,  help="OI change  threshold for trend signal")
    p.add_argument("--px-threshold",   type=float, default=0.1,  help="Price change  threshold for trend signal")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    fetcher   = OIFetcher(coinglass_key=os.getenv("COINGLASS_API_KEY", ""))
    processor = OIProcessor(
        validator  = OIValidator(),
        classifier = TrendClassifier(
            oi_threshold_pct    = args.oi_threshold,
            price_threshold_pct = args.px_threshold,
        ),
    )
    publisher = SignalPublisher(
        signal_path = args.signal_path,
        db_path     = args.db_path,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)

    try:
        loop.run_until_complete(
            run_loop(args.symbol, args.interval, fetcher, processor, publisher)
        )
    finally:
        loop.close()
        logger.info("Event loop closed. Goodbye.")


if __name__ == "__main__":
    main()
