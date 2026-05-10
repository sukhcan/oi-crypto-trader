# OI Trading System — Technical Documentation
## Hybrid Crypto Futures Open Interest Signal Engine

---

## 1. System Overview

This system replicates the analytical edge that professional futures traders derive from **CFTC Commitments of Traders (COT)** data on CME 6E (EUR Futures) — but applied to 24/7 cryptocurrency perpetual futures markets.

The core insight: Open Interest (OI) combined with price direction reveals *who* is driving a move and whether it is sustainable:

| Price Direction | OI Direction | Interpretation       | Signal  |
|----------------|-------------|----------------------|---------|
| Rising         | Rising      | New longs entering   | **BUY** (BULLISH_TREND) |
| Rising         | Falling     | Shorts covering      | **BUY** (SHORT_COVERING) |
| Falling        | Rising      | New shorts entering  | **SELL** (BEARISH_TREND) |
| Falling        | Falling     | Longs liquidating    | **SELL** (LONG_LIQUIDATION) |
| Flat           | Either      | No conviction        | NEUTRAL |

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PYTHON DATA LAYER                           │
│                                                                 │
│  ┌───────────────┐   ┌───────────────┐   ┌──────────────────┐  │
│  │ BinanceOI     │   │  BybitOI      │   │  CoinGlass OI    │  │
│  │ Provider      │   │  Provider     │   │  Provider        │  │
│  │ (PRIMARY)     │   │  (SECONDARY)  │   │  (COT FALLBACK)  │  │
│  └───────┬───────┘   └───────┬───────┘   └────────┬─────────┘  │
│          └─────────────┬─────┘                    │            │
│                        ▼                           │            │
│               ┌────────────────┐◄──────────────────┘           │
│               │  OIFetcher     │ (provider chain / waterfall)  │
│               └───────┬────────┘                               │
│                       │ OISnapshot                              │
│                       ▼                                         │
│               ┌────────────────┐                               │
│               │  OIValidator   │ (hard + soft checks)          │
│               └───────┬────────┘                               │
│                       │ validated OISnapshot                    │
│                       ▼                                         │
│               ┌────────────────┐                               │
│               │  OIProcessor   │ (metrics + trend matrix)      │
│               └───────┬────────┘                               │
│                       │ OIMetrics                               │
│                       ▼                                         │
│               ┌────────────────┐                               │
│               │SignalPublisher │                               │
│               │ ├ JSON file ──────────────────────────────┐   │
│               │ └ SQLite log │                             │   │
│               └──────────────┘                             │   │
└────────────────────────────────────────────────────────────┼───┘
                                                             │
                          oi_signal.json (atomic write)      │
                                                             │
┌────────────────────────────────────────────────────────────▼───┐
│                     MQL5 EXECUTION LAYER                        │
│                                                                 │
│               ┌────────────────┐                               │
│               │ OI_Signal_EA   │ (EventSetTimer poll)          │
│               │ ├ ReadSignal() │                               │
│               │ ├ Validate     │ (staleness, OI threshold)     │
│               │ ├ BUY/SELL     │ (with SL/TP)                 │
│               │ └ CloseOnRev   │ (reverse signal → close)     │
│               └────────────────┘                               │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources

### 3.1 Primary — Binance USDT-M Perpetuals
- **Endpoint**: `GET https://fapi.binance.com/fapi/v1/openInterest`
- **Rate limit**: 500 req/10s weight-based; single OI call = weight 1
- **Latency**: ~50–150ms from major cloud regions
- **Coverage**: BTC, ETH, BNB, and 300+ pairs

### 3.2 Secondary — Bybit Linear Perpetuals
- **Endpoint**: `GET https://api.bybit.com/v5/market/open-interest`
- **Rate limit**: 120 req/min per IP (no auth required)
- **Latency**: ~80–200ms
- **Coverage**: BTC, ETH, SOL, and 200+ pairs

### 3.3 Fallback — CoinGlass (COT Equivalent)
CoinGlass aggregates OI across **Binance, Bybit, OKX, Deribit, CME Bitcoin Futures, Kraken**, and others — providing a market-wide view analogous to the CFTC COT report for traditional futures.

- **Endpoint**: `GET https://open-api.coinglass.com/public/v2/open_interest`
- **Auth**: Free API key (https://www.coinglass.com/pricing)
- **Use case**: Primary exchanges down, or when consolidated market view is preferred
- **Update frequency**: ~5 minutes aggregated

---

## 4. Python Module Reference

### `OISnapshot` (dataclass)
Raw, validated point-in-time OI record.

| Field              | Type     | Description                           |
|-------------------|----------|---------------------------------------|
| `symbol`          | str      | e.g. "BTCUSDT"                       |
| `timestamp`       | datetime | UTC, timezone-aware                  |
| `open_interest`   | float    | Native contract units                |
| `open_interest_usd` | float  | USD notional                         |
| `price`           | float    | Mark price at capture time           |
| `source`          | str      | Provider name                        |

### `OIMetrics` (dataclass)
Derived metrics and signal, emitted after each validated pair of snapshots.

| Field               | Type  | Description                          |
|--------------------|-------|--------------------------------------|
| `oi_change_abs`    | float | Δ OI in native units                |
| `oi_change_pct`    | float | % change vs previous bar            |
| `price_change_pct` | float | % price change vs previous bar      |
| `trend_label`      | str   | BULLISH_TREND / BEARISH_TREND / etc. |
| `signal`           | str   | BUY / SELL / NEUTRAL                |

### `OIValidator`
Configurable thresholds:

| Parameter           | Default | Purpose                                    |
|--------------------|---------|--------------------------------------------|
| `MAX_OI_CHANGE_PCT` | 50%    | Flag data errors (sudden 50%+ OI spikes)  |
| `MAX_PRICE_CHANGE_PCT` | 20% | Flag price feed errors                    |
| `MIN_OI_USD`        | $1M    | Enforce minimum liquidity                 |

### `TrendClassifier`
| Parameter               | Default | Purpose                              |
|------------------------|---------|--------------------------------------|
| `oi_threshold_pct`     | 0.5%   | Minimum OI move to count as directional |
| `price_threshold_pct`  | 0.1%   | Minimum price move to count         |

---

## 5. Signal File Schema (v1)

The JSON file written atomically to `signals/oi_signal.json`:

```json
{
  "schema_version":   1,
  "symbol":           "BTCUSDT",
  "timestamp":        "2024-01-15T10:30:00+00:00",
  "signal":           "BUY",
  "trend_label":      "BULLISH_TREND",
  "current_oi":       42500.0,
  "previous_oi":      41800.0,
  "oi_change_abs":    700.0,
  "oi_change_pct":    1.6746,
  "current_price":    43250.0,
  "previous_price":   43100.0,
  "price_change_pct": 0.348,
  "published_at":     "2024-01-15T10:30:01+00:00"
}
```

The MQL5 EA polls this file on its timer event. The `published_at` field enables the staleness check — if the EA reads a signal older than `InpSignalStaleSec` (default 120s), it ignores it.

---

## 6. MQL5 EA Configuration

| Input                | Default         | Description                              |
|---------------------|-----------------|------------------------------------------|
| `InpSignalFile`     | oi_signal.json  | Path relative to MQL5\Files\Common       |
| `InpPollSeconds`    | 5               | How often the EA checks the signal file  |
| `InpSignalStaleSec` | 120             | Max age of signal before ignoring        |
| `InpLotSize`        | 0.01            | Trade size                               |
| `InpStopLossPct`    | 1.5%            | SL distance from entry                   |
| `InpTakeProfitPct`  | 3.0%            | TP distance from entry                   |
| `InpMaxPositions`   | 1               | Max simultaneous open positions          |
| `InpCloseOnReverse` | true            | Close longs on SELL signal (and vice versa) |
| `InpMinOIChangePct` | 0.5%            | OI move must exceed this to trade        |
| `InpMinPxChangePct` | 0.1%            | Price move must exceed this to trade     |

**Deployment**: Copy `OI_Signal_EA.mq5` → `MT5/MQL5/Experts/`, compile in MetaEditor, attach to the crypto CFD chart. Enable "Allow DLL imports" and "Read/write files from common folder".

---

## 7. Running the System

### Prerequisites
```bash
pip install -r requirements.txt
export COINGLASS_API_KEY="your_key_here"   # optional, for fallback
```

### Start the polling loop
```bash
# Default: BTCUSDT, 30s interval
python -m python.main

# Custom symbol and interval
python -m python.main --symbol ETHUSDT --interval 15 --log-level DEBUG

# Override signal path to MT5 Common Files directory (Windows example)
python -m python.main \
  --signal-path "C:/Users/You/AppData/Roaming/MetaQuotes/Terminal/Common/Files/oi_signal.json"
```

### Run tests
```bash
pytest python/tests/ -v
```

---

## 8. Project Layout

```
oi_trading_system/
├── python/
│   ├── core/
│   │   ├── oi_fetcher.py         # Data acquisition (3 providers + fallback)
│   │   ├── oi_processor.py       # Validation, metrics, trend classification
│   │   └── signal_publisher.py   # JSON + SQLite output
│   ├── tests/
│   │   └── test_oi_system.py     # 29 unit + integration tests
│   └── main.py                   # Async orchestration loop
├── mql5/
│   └── Experts/
│       └── OI_Signal_EA.mq5      # MetaTrader 5 Expert Advisor
├── signals/                      # Runtime output (gitignored)
│   ├── oi_signal.json
│   └── oi_signals.db
├── requirements.txt
└── README.md                     # This file
```

---

## 9. Production Hardening Checklist

- [ ] Set `COINGLASS_API_KEY` env var for the fallback provider
- [ ] Run Python main loop as a systemd service or Docker container
- [ ] Mount `signals/` as a shared volume accessible to the MT5 host (or use a network share)
- [ ] Monitor `oi_system.log` for consecutive failure alerts
- [ ] Query `oi_signals.db` for post-trade signal audit
- [ ] Backtest OI signals on historical data via `OIFetcher.fetch_history()` + `OIProcessor.process_dataframe()`
- [ ] Tune `InpStopLossPct`, `InpMinOIChangePct`, and `TrendClassifier` thresholds per symbol and timeframe

---

## 10. Extending the System

**Add a new exchange provider**: Subclass `OIProvider`, implement `fetch(symbol) -> OISnapshot`, inject into `OIFetcher(providers=[...])`.

**Add position sizing**: Replace `InpLotSize` with a Kelly-fraction calculator driven by `oi_change_pct` magnitude.

**Add OI z-score filter**: In `OIProcessor`, compute rolling z-score of `oi_change_pct` over the buffer window; only signal when z > 1.5.

**Webhook / Telegram alerts**: In `SignalPublisher.publish()`, add a `requests.post()` to a Telegram bot API alongside the JSON write.
