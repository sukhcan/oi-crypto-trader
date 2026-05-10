"""
╔══════════════════════════════════════════════════════════════╗
║          Crypto OI Fetcher Pro  v1.0                        ║
║  Institutional Smart Money Signals → MT5 Auto-Trading       ║
║  Data: CoinGlass + Binance + Fear&Greed                     ║
╚══════════════════════════════════════════════════════════════╝
"""
import os, sys, io, json, time, logging, threading, traceback, subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime, timezone, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler

import requests
import pandas as pd

# ── MT5 (optional) ────────────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

# ══════════════════════════════════════════════════════════════
#  CONFIG — SIRF YAHAN EDIT KARO
# ══════════════════════════════════════════════════════════════
APP_NAME    = "Crypto OI Fetcher Pro"
APP_VER     = "1.0"
FETCH_SEC   = 60          # Har kitne seconds mein fetch (60 = 1 min)

# ── MT5 Auto-Trade Config ─────────────────────────────────────
MT5_AUTO_TRADE    = False
MT5_SYMBOL_SUFFIX = ""        # "" ya "m" ya ".crypto" — broker pe depend
MT5_SYMBOL_PREFIX = ""        # "" ya "."
MT5_MAX_TRADES    = 2
MT5_MAGIC         = 20250509
MT5_STOP_LOSS_PCT = 2.0       # SL = 2% from entry
MT5_TP_RATIO      = 2.0       # TP = 2x SL (1:2 RR)
MT5_DEVIATION     = 50
MT5_COMMENT       = "CryptoOI"
RISK_PCT          = 2.0       # 2% account risk per trade

# Signal thresholds
OI_LONG_FILTER    = +1.0      # OI must rise >= 1% for LONG
OI_SHORT_FILTER   = +1.0      # OI must rise >= 1% for SHORT
FUNDING_LONG_MAX  =  0.00     # Funding must be <= 0% for LONG
FUNDING_SHORT_MIN = +0.03     # Funding must be >= +0.03% for SHORT
LS_LONG_MIN       =  1.2      # L/S ratio must be >= 1.2 for LONG
LS_SHORT_MAX      =  0.8      # L/S ratio must be <= 0.8 for SHORT
SCORE_STRONG      = 60        # Score >= 60 = STRONG
SCORE_WEAK        = 35        # Score >= 35 = WEAK

# ── MT5 Accounts ──────────────────────────────────────────────
MT5_ACCOUNTS = [
    ("Demo #52719978",  52719978,  "kYp&S5QVo39avC",  "ICMarketsSC-Demo"),
    ("Demo #52659962",  52659962,  "lQ!8qdt6S1$LzJ",  "ICMarketsSC-Demo"),
    ("Demo #52781955",  52781955,  "79nrrMZL@D$n10",  "ICMarketsSC-Demo"),
    ("Demo #52781987",  52781987,  "CYh&XDuzl4flYv",  "ICMarketsSC-Demo"),
    ("Demo #2785364",   2785364,   "o2lYshV$XLZRNg",  "ICMarketsSC-Demo"),
    ("Demo #52785370",  52785370,  "$bEwlSb0F@7tNN",  "ICMarketsSC-Demo"),
    ("Demo #52785551",  52785551,  "w&99lfqAh&r&PS",  "ICMarketsSC-Demo"),
    ("Demo #52787254",  52787254,  "$cIQHJQ5VSmvyG",  "ICMarketsSC-Demo"),
    ("Demo #52787255",  52787255,  "DrO1Xai@Teyy1Z",  "ICMarketsSC-Demo"),
]

# Active account (GUI se change hoga)
_active_acct = MT5_ACCOUNTS[0]
MT5_LOGIN    = _active_acct[1]
MT5_PASSWORD = _active_acct[2]
MT5_SERVER   = _active_acct[3]

# ── Crypto Symbols ────────────────────────────────────────────
# MT5 name : Binance futures symbol
SYMBOLS = {
    "BTCUSD":  "BTCUSDT",
    "ETHUSD":  "ETHUSDT",
    "SOLUSD":  "SOLUSDT",
    "XRPUSD":  "XRPUSDT",
    "BNBUSD":  "BNBUSDT",
    "ADAUSD":  "ADAUSDT",
    "DOGEUSD": "DOGEUSDT",
    "LINKUSD": "LINKUSDT",
    "AVAXUSD": "AVAXUSDT",
}

# ── Colors ────────────────────────────────────────────────────
BG  = "#040810"; HDR = "#05194A"; GRN = "#18B854"; RED = "#C32D2D"
GLD = "#C3A018"; BLU = "#4A91E1"; DIM = "#2D4E6E"; TXT = "#9BBEE6"
WH  = "#D7E6FF"; PNL = "#060F1C"; CYN = "#7EC8E3"; ORG = "#E87C1A"

# ── Logging ───────────────────────────────────────────────────
log_file = Path("crypto_oi_fetcher.log")
_log_handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=2)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_logger = logging.getLogger("CryptoOI")
_logger.addHandler(_log_handler)
_logger.setLevel(logging.INFO)

g_log_cb     = None
g_cycle      = 0
g_running    = False
g_stop_event = threading.Event()
g_last_data  = {}

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    full = f"[{ts}] {msg}"
    _logger.info(full)
    if g_log_cb:
        g_log_cb(full + "\n", level)
    else:
        print(full)

# ══════════════════════════════════════════════════════════════
#  DATA FETCHERS
# ══════════════════════════════════════════════════════════════
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
sess = requests.Session()
sess.headers.update(HEADERS)

def safe_get(url, params=None, timeout=10):
    try:
        r = sess.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"API error {url[:60]}: {e}", "WARN")
    return None

def fetch_binance_tickers():
    """Binance 24h ticker — price + change%"""
    data = safe_get("https://api.binance.com/api/v3/ticker/24hr")
    if not data:
        return {}
    return {
        item["symbol"]: {
            "price": float(item["lastPrice"]),
            "change_pct": float(item["priceChangePercent"]),
            "volume": float(item["quoteVolume"]),
        }
        for item in data
        if item["symbol"].endswith("USDT")
    }

def fetch_binance_funding():
    """Binance futures funding rates"""
    data = safe_get("https://fapi.binance.com/fapi/v1/premiumIndex")
    if not data:
        return {}
    return {
        item["symbol"]: float(item.get("lastFundingRate", 0)) * 100
        for item in data
    }

def fetch_top_ls_ratio(symbol, period="5m"):
    """Binance Top Trader Long/Short Ratio"""
    data = safe_get(
        "https://fapi.binance.com/futures/data/topLongShortAccountRatio",
        params={"symbol": symbol, "period": period, "limit": 1}
    )
    if data and len(data) > 0:
        try:
            return float(data[0]["longShortRatio"])
        except:
            pass
    return 1.0  # neutral default

def fetch_coinglass_oi():
    """CoinGlass Open Interest — tries multiple endpoints"""
    # Try public endpoint
    endpoints = [
        "https://open-api.coinglass.com/public/v2/open_interest",
        "https://open-api-v3.coinglass.com/api/futures/openInterest/chart",
    ]
    for url in endpoints:
        data = safe_get(url, timeout=15)
        if data:
            return data
    return None

def fetch_binance_oi():
    """Binance futures OI — reliable fallback"""
    results = {}
    for mt5_sym, bn_sym in SYMBOLS.items():
        data = safe_get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": bn_sym}
        )
        if data:
            try:
                results[bn_sym] = float(data["openInterest"])
            except:
                pass
        time.sleep(0.05)  # rate limit
    return results

def fetch_binance_oi_history():
    """Binance OI history for change calculation"""
    results = {}
    for mt5_sym, bn_sym in SYMBOLS.items():
        data = safe_get(
            "https://fapi.binance.com/futures/data/openInterestHist",
            params={"symbol": bn_sym, "period": "1h", "limit": 3}
        )
        if data and len(data) >= 2:
            try:
                cur  = float(data[-1]["sumOpenInterest"])
                prev = float(data[-2]["sumOpenInterest"])
                pct  = (cur - prev) / prev * 100 if prev else 0.0
                results[bn_sym] = {
                    "current": cur,
                    "previous": prev,
                    "change_pct": round(pct, 3),
                }
            except:
                pass
        time.sleep(0.05)
    return results

def fetch_fear_greed():
    """Alternative.me Fear & Greed Index"""
    data = safe_get("https://api.alternative.me/fng/?limit=2", timeout=8)
    if data and "data" in data and len(data["data"]) > 0:
        d = data["data"][0]
        return {
            "value":       int(d.get("value", 50)),
            "label":       d.get("value_classification", "Neutral"),
            "yesterday":   int(data["data"][1].get("value", 50)) if len(data["data"]) > 1 else 50,
        }
    return {"value": 50, "label": "Neutral", "yesterday": 50}

def fetch_btc_dominance():
    """CoinGecko global market data"""
    data = safe_get("https://api.coingecko.com/api/v3/global", timeout=8)
    if data and "data" in data:
        d = data["data"]
        return {
            "btc_dominance":  round(d.get("market_cap_percentage", {}).get("btc", 0), 1),
            "market_cap_usd": d.get("total_market_cap", {}).get("usd", 0),
            "volume_24h":     d.get("total_volume", {}).get("usd", 0),
        }
    return {"btc_dominance": 0, "market_cap_usd": 0, "volume_24h": 0}

# ══════════════════════════════════════════════════════════════
#  SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════
def fg_bias(fg_value):
    """Fear & Greed → directional bias"""
    if fg_value <= 25:  return "LONG",  20   # Extreme Fear  → buy zone
    if fg_value <= 45:  return "LONG",  10   # Fear          → mild buy
    if fg_value <= 54:  return "NEUT",  0    # Neutral
    if fg_value <= 74:  return "SHORT", 10   # Greed         → mild short
    return "SHORT", 20                        # Extreme Greed → short zone

def calc_signal(sym_data, fg):
    """
    Score-based signal (0-100):
      OI change:    30 pts max
      Funding rate: 25 pts max
      L/S ratio:    25 pts max
      Fear&Greed:   20 pts max
    """
    oi_pct   = sym_data.get("oi_change_pct", 0.0)
    funding  = sym_data.get("funding_rate", 0.0)   # % e.g. 0.03
    ls_ratio = sym_data.get("ls_ratio", 1.0)
    price    = sym_data.get("price", 0.0)
    fg_val   = fg.get("value", 50)

    # ── Direction votes ───────────────────────────────────────
    long_votes = 0; short_votes = 0

    # OI score (30 pts)
    oi_score = 0
    if oi_pct >= 2.0:   oi_score = 30
    elif oi_pct >= 1.0: oi_score = 20
    elif oi_pct >= 0.5: oi_score = 10

    # Funding score (25 pts) — negative = good for longs, positive = good for shorts
    fund_score_long = 0; fund_score_short = 0
    if funding <= -0.05:   fund_score_long  = 25; long_votes  += 2
    elif funding <= 0.00:  fund_score_long  = 15; long_votes  += 1
    elif funding >= 0.05:  fund_score_short = 25; short_votes += 2
    elif funding >= 0.03:  fund_score_short = 15; short_votes += 1

    # L/S ratio score (25 pts)
    ls_score_long = 0; ls_score_short = 0
    if ls_ratio >= 1.5:   ls_score_long  = 25; long_votes  += 2
    elif ls_ratio >= 1.2: ls_score_long  = 15; long_votes  += 1
    elif ls_ratio <= 0.7: ls_score_short = 25; short_votes += 2
    elif ls_ratio <= 0.8: ls_score_short = 15; short_votes += 1

    # Fear & Greed score (20 pts)
    fg_dir, fg_pts = fg_bias(fg_val)
    fg_score_long  = fg_pts if fg_dir == "LONG"  else 0
    fg_score_short = fg_pts if fg_dir == "SHORT" else 0
    if fg_dir == "LONG":  long_votes  += 1
    if fg_dir == "SHORT": short_votes += 1

    # ── Final scores ──────────────────────────────────────────
    long_score  = oi_score + fund_score_long  + ls_score_long  + fg_score_long
    short_score = oi_score + fund_score_short + ls_score_short + fg_score_short

    # OI must be rising to trade
    if oi_pct < OI_LONG_FILTER and oi_pct < OI_SHORT_FILTER:
        return "NO_TRADE", "NONE", 0, 0

    # Determine direction
    if long_score > short_score and long_votes >= 2:
        direction = "LONG"
        score = long_score
    elif short_score > long_score and short_votes >= 2:
        direction = "SHORT"
        score = short_score
    else:
        return "NO_TRADE", "NONE", 0, 0

    # Don't short in extreme fear, don't long in extreme greed
    if direction == "SHORT" and fg_val <= 25:
        return "NO_TRADE", "NONE", 0, 0
    if direction == "LONG"  and fg_val >= 75:
        return "NO_TRADE", "NONE", 0, 0

    # Signal strength
    if score >= SCORE_STRONG:   strength = "STRONG"
    elif score >= SCORE_WEAK:   strength = "WEAK"
    else:                       return "NO_TRADE", "NONE", 0, 0

    signal = f"{'LONG' if direction=='LONG' else 'SHORT'}_{strength}"
    return signal, strength, score, direction

# ══════════════════════════════════════════════════════════════
#  MAIN FETCH CYCLE
# ══════════════════════════════════════════════════════════════
_fg_cache       = {"value": 50, "label": "Neutral", "yesterday": 50}
_fg_last_fetch  = 0
_global_cache   = {"btc_dom": 0, "mcap": 0, "vol24h": 0}
_global_last    = 0

def do_fetch(status_cb=None, table_cb=None):
    global g_cycle, g_last_data, _fg_cache, _fg_last_fetch, _global_cache, _global_last

    g_cycle += 1
    log(f"=== Cycle #{g_cycle} ===")
    if status_cb: status_cb("FETCHING")

    # ── Fear & Greed (every 5 min) ────────────────────────────
    if time.time() - _fg_last_fetch > 300:
        log("Fetching Fear & Greed index...")
        _fg_cache      = fetch_fear_greed()
        _fg_last_fetch = time.time()
        log(f"Fear & Greed: {_fg_cache['value']} — {_fg_cache['label']}")

    # ── BTC Dominance (every 10 min) ─────────────────────────
    if time.time() - _global_last > 600:
        log("Fetching global market data...")
        gd = fetch_btc_dominance()
        _global_cache = {
            "btc_dom": gd["btc_dominance"],
            "mcap":    gd["market_cap_usd"],
            "vol24h":  gd["volume_24h"],
        }
        _global_last = time.time()

    # ── Binance price + funding ───────────────────────────────
    log("Fetching Binance prices...")
    tickers = fetch_binance_tickers()
    log("Fetching funding rates...")
    funding = fetch_binance_funding()

    # ── OI history ────────────────────────────────────────────
    log("Fetching OI history...")
    oi_hist = fetch_binance_oi_history()

    # ── Build symbol data ────────────────────────────────────
    syms_data = {}
    best_sym  = None
    best_score = -1

    for mt5_sym, bn_sym in SYMBOLS.items():
        t   = tickers.get(bn_sym, {})
        oi  = oi_hist.get(bn_sym, {})
        f   = funding.get(bn_sym, 0.0)

        # L/S ratio (slower — fetch per symbol)
        ls = fetch_top_ls_ratio(bn_sym)

        price      = t.get("price", 0.0)
        change_pct = t.get("change_pct", 0.0)
        oi_cur     = oi.get("current", 0.0)
        oi_pct     = oi.get("change_pct", 0.0)

        d = {
            "mt5_symbol":    mt5_sym,
            "bn_symbol":     bn_sym,
            "price":         price,
            "change_24h":    change_pct,
            "oi_current":    oi_cur,
            "oi_change_pct": oi_pct,
            "funding_rate":  f,
            "ls_ratio":      ls,
            "fg_value":      _fg_cache["value"],
            "fetch_ok":      price > 0,
        }

        sig, strength, score, direction = calc_signal(d, _fg_cache)
        d["signal"]    = sig
        d["strength"]  = strength
        d["score"]     = score
        d["direction"] = direction

        syms_data[mt5_sym] = d

        log(f"  {mt5_sym:<10} ${price:>10,.2f}  OI:{oi_pct:>+6.2f}%"
            f"  Fund:{f:>+6.3f}%  L/S:{ls:.2f}"
            f"  [{strength}] {sig}")

        # Best signal selection
        if strength in ("STRONG", "WEAK") and score > best_score:
            best_score = score
            best_sym   = mt5_sym

    # ── Summary ───────────────────────────────────────────────
    combined = {
        "cycle":         g_cycle,
        "generated_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fear_greed":    _fg_cache,
        "global":        _global_cache,
        "best_symbol":   best_sym,
        "best_score":    best_score,
        "symbols":       syms_data,
    }

    longs  = [s for s,d in syms_data.items() if "LONG"  in d["signal"]]
    shorts = [s for s,d in syms_data.items() if "SHORT" in d["signal"]]
    log(f"Done | LONG:{longs} SHORT:{shorts} Best:{best_sym or 'None'} Score:{best_score}")

    # Save JSON
    try:
        with open("crypto_oi_data.json", "w") as f:
            json.dump(combined, f, indent=2)
    except:
        pass

    g_last_data = combined
    if table_cb:
        table_cb(combined)

    # ── MT5 Auto-Trade ────────────────────────────────────────
    if MT5_AUTO_TRADE:
        mt5_process_signals(syms_data, best_sym)

    if status_cb:
        status_cb("ACTIVE")

    return combined

# ══════════════════════════════════════════════════════════════
#  FETCHER THREAD
# ══════════════════════════════════════════════════════════════
def fetcher_thread(status_cb=None, next_cb=None, table_cb=None):
    global g_running
    log("Fetcher STARTED")
    try:
        do_fetch(status_cb, table_cb)
    except Exception as e:
        log(f"Cycle error: {e}\n{traceback.format_exc()[:300]}", "ERROR")

    while not g_stop_event.is_set():
        # Countdown
        for remaining in range(FETCH_SEC, 0, -1):
            if g_stop_event.is_set():
                break
            if next_cb:
                next_cb(f"{remaining}s")
            time.sleep(1)
        if g_stop_event.is_set():
            break
        try:
            do_fetch(status_cb, table_cb)
        except Exception as e:
            log(f"Cycle error: {e}\n{traceback.format_exc()[:300]}", "ERROR")
            if status_cb: status_cb("ACTIVE")

    g_running = False
    log("Fetcher STOPPED")

# ══════════════════════════════════════════════════════════════
#  MT5 ENGINE
# ══════════════════════════════════════════════════════════════
_mt5_connected    = False
_traded_this_cycle = set()

def mt5_symbol(mt5_sym):
    """Apply broker prefix/suffix"""
    return f"{MT5_SYMBOL_PREFIX}{mt5_sym}{MT5_SYMBOL_SUFFIX}"

def switch_account(label, login, password, server):
    global MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, _mt5_connected
    mt5_disconnect()
    MT5_LOGIN      = login
    MT5_PASSWORD   = password
    MT5_SERVER     = server
    _mt5_connected = False
    log(f"Account switched → {label} ({login})")

def mt5_connect():
    global _mt5_connected
    if not MT5_AVAILABLE:
        log("MetaTrader5 nahi mili — pip install MetaTrader5", "WARN")
        return False
    if _mt5_connected:
        try:
            info = mt5.account_info()
            if info and info.login == MT5_LOGIN:
                return True
            mt5.shutdown(); _mt5_connected = False
        except:
            mt5.shutdown(); _mt5_connected = False
    if not MT5_LOGIN or not MT5_PASSWORD or not MT5_SERVER:
        log("MT5 credentials set nahi", "WARN"); return False
    try:
        if not mt5.initialize():
            log(f"MT5 init fail: {mt5.last_error()}", "ERROR"); return False
        auth = mt5.login(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
        if not auth:
            log(f"MT5 login fail: {mt5.last_error()}", "ERROR")
            mt5.shutdown(); return False
        info = mt5.account_info()
        if info.login != MT5_LOGIN:
            log(f"[MT5] Account mismatch {info.login}≠{MT5_LOGIN}", "ERROR")
            mt5.shutdown(); return False
        log(f"MT5 ✓ #{info.login} | {info.balance:.2f} {info.currency} | {info.server}")
        _mt5_connected = True
        return True
    except Exception as e:
        log(f"MT5 connect error: {e}", "ERROR"); return False

def mt5_disconnect():
    global _mt5_connected
    if MT5_AVAILABLE and _mt5_connected:
        try: mt5.shutdown()
        except: pass
        _mt5_connected = False
        log("MT5 disconnected.")

def mt5_count_open():
    try:
        pos = mt5.positions_get()
        return sum(1 for p in pos if p.magic == MT5_MAGIC) if pos else 0
    except: return 0

def mt5_has_trade(sym):
    try:
        pos = mt5.positions_get(symbol=mt5_symbol(sym))
        return any(p.magic == MT5_MAGIC for p in pos) if pos else False
    except: return False

def mt5_check_daily_loss():
    try:
        info = mt5.account_info()
        if not info: return 0.0, 0.0, 0.0
        bal = info.balance; eq = info.equity
        open_loss = min(0.0, eq - bal)
        from_dt   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        deals     = mt5.history_deals_get(from_dt, datetime.now())
        closed    = sum(d.profit for d in deals if d.magic == MT5_MAGIC) if deals else 0.0
        total     = open_loss + min(0.0, closed)
        loss_pct  = abs(total / bal * 100) if bal > 0 else 0.0
        return loss_pct, bal, eq
    except Exception as e:
        log(f"[MT5] daily loss check error: {e}", "WARN")
        return 0.0, 0.0, 0.0

def mt5_calc_lot(sym, sl_price_dist, balance):
    """2% risk lot calculator for crypto"""
    try:
        si = mt5.symbol_info(mt5_symbol(sym))
        if not si: return 0.01
        risk_amt      = balance * RISK_PCT / 100.0
        tick_val      = si.trade_tick_value   # USD per tick per lot
        tick_sz       = si.trade_tick_size    # price per tick
        if tick_sz <= 0 or tick_val <= 0: return si.volume_min
        ticks_in_sl   = sl_price_dist / tick_sz
        sl_cost_lot   = ticks_in_sl * tick_val
        if sl_cost_lot <= 0: return si.volume_min
        raw_lot = risk_amt / sl_cost_lot
        step    = si.volume_step
        lot     = max(si.volume_min, min(si.volume_max, round(raw_lot / step) * step))
        lot     = round(lot, 4)
        log(f"[MT5] Lot calc {sym}: bal={balance:.0f} risk=${risk_amt:.0f} sl_dist={sl_price_dist:.2f} lot={lot}")
        return lot
    except Exception as e:
        log(f"[MT5] lot calc error {sym}: {e}", "WARN")
        return 0.01

def mt5_place_trade(mt5_sym, direction, score, price_hint):
    try:
        if not mt5_connect(): return False
        full_sym = mt5_symbol(mt5_sym)
        si = mt5.symbol_info(full_sym)
        if not si:
            log(f"[MT5] Symbol {full_sym} not found", "WARN"); return False
        if not si.visible:
            mt5.symbol_select(full_sym, True); time.sleep(0.3)
            si = mt5.symbol_info(full_sym)
        tick = mt5.symbol_info_tick(full_sym)
        if not tick:
            log(f"[MT5] No tick for {full_sym}", "WARN"); return False

        info = mt5.account_info()
        bal  = info.balance if info else 10000.0

        if direction == "LONG":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
            sl_dist = price * MT5_STOP_LOSS_PCT / 100.0
            sl  = round(price - sl_dist, si.digits)
            tp  = round(price + sl_dist * MT5_TP_RATIO, si.digits)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
            sl_dist = price * MT5_STOP_LOSS_PCT / 100.0
            sl  = round(price + sl_dist, si.digits)
            tp  = round(price - sl_dist * MT5_TP_RATIO, si.digits)

        lot = mt5_calc_lot(mt5_sym, sl_dist, bal)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       full_sym,
            "volume":       lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    MT5_DEVIATION,
            "magic":        MT5_MAGIC,
            "comment":      f"{MT5_COMMENT}_S{score}",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            log(f"[MT5] ✅ {direction} {full_sym} | Lot:{lot} | "
                f"Price:{price} | SL:{sl} | TP:{tp} | #{result.order}")
            return True
        else:
            log(f"[MT5] ❌ Fail {full_sym}: retcode={result.retcode} | {result.comment}", "ERROR")
            return False
    except Exception as e:
        log(f"[MT5] Exception {mt5_sym}: {e}", "ERROR"); return False

def mt5_process_signals(syms_data, best_sym):
    global _traded_this_cycle
    if not MT5_AUTO_TRADE: return
    if not MT5_AVAILABLE:
        log("[MT5] Library not found", "WARN"); return
    if not mt5_connect(): return

    DAILY_LIMIT = 2.0
    loss_pct, bal, eq = mt5_check_daily_loss()
    if loss_pct >= DAILY_LIMIT:
        log(f"[MT5] 🚫 Daily loss {loss_pct:.2f}% >= {DAILY_LIMIT}% — trading stopped"); return
    if mt5_count_open() >= MT5_MAX_TRADES:
        log(f"[MT5] Max {MT5_MAX_TRADES} trades open — skip"); return
    if not best_sym:
        log("[MT5] No qualifying signal"); return

    d        = syms_data.get(best_sym, {})
    signal   = d.get("signal", "NO_TRADE")
    strength = d.get("strength", "NONE")
    score    = d.get("score", 0)
    direction = d.get("direction", "")
    price    = d.get("price", 0.0)
    oi_pct   = d.get("oi_change_pct", 0.0)
    funding  = d.get("funding_rate", 0.0)
    ls       = d.get("ls_ratio", 1.0)
    fg_val   = d.get("fg_value", 50)

    if strength != "STRONG":
        log(f"[MT5] {best_sym} strength={strength} — only STRONG trades allowed"); return
    if best_sym in _traded_this_cycle:
        log(f"[MT5] {best_sym} already traded this cycle"); return
    if mt5_has_trade(best_sym):
        log(f"[MT5] {best_sym} already has open trade"); return
    if not direction:
        log(f"[MT5] No direction for {best_sym}"); return

    log(f"[MT5] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log(f"[MT5] 🏦 CRYPTO SIGNAL — {best_sym}")
    log(f"[MT5]    Direction  : {direction}")
    log(f"[MT5]    Signal     : {signal} [Score:{score}]")
    log(f"[MT5]    OI Change  : {oi_pct:+.2f}%")
    log(f"[MT5]    Funding    : {funding:+.4f}%")
    log(f"[MT5]    L/S Ratio  : {ls:.2f}")
    log(f"[MT5]    Fear&Greed : {fg_val}")
    log(f"[MT5]    Daily Loss : {loss_pct:.2f}% / {DAILY_LIMIT}%")
    log(f"[MT5]    Balance    : ${bal:,.2f}  Equity:${eq:,.2f}")
    log(f"[MT5] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    ok = mt5_place_trade(best_sym, direction, score, price)
    if ok:
        _traded_this_cycle.add(best_sym)

def mt5_reset_cycle():
    global _traded_this_cycle
    _traded_this_cycle = set()

# ══════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════
class CryptoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VER}")
        self.geometry("1280x760")
        self.resizable(True, True)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._auto_trade_on = MT5_AUTO_TRADE
        self.thread = None
        self._build_ui()
        global g_log_cb
        g_log_cb = self._append_log
        self.after(500, self._start_auto)

    # ── BUILD UI ──────────────────────────────────────────────
    def _build_ui(self):

        # ── HEADER ────────────────────────────────────────────
        hdr = tk.Frame(self, bg=HDR, height=54)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  {APP_NAME}  v{APP_VER}",
                 bg=HDR, fg=WH, font=("Arial Bold", 14)).pack(side="left", pady=14)
        tk.Label(hdr, text=f"  24/7 | {FETCH_SEC}s",
                 bg=HDR, fg=DIM, font=("Arial", 9)).pack(side="left", pady=16)
        self.lbl_status = tk.Label(hdr, text="○ IDLE",
                                   bg=HDR, fg=GLD, font=("Arial Bold", 10))
        self.lbl_status.pack(side="right", padx=16)

        # ── FEAR & GREED + MARKET BAR ─────────────────────────
        fgbar = tk.Frame(self, bg="#030C18", height=28)
        fgbar.pack(fill="x"); fgbar.pack_propagate(False)
        self.lbl_fg      = tk.Label(fgbar, text="😐 F&G: 50 — NEUTRAL",
                                    bg="#030C18", fg=GLD, font=("Courier New", 9))
        self.lbl_fg.pack(side="left", padx=12)
        self.lbl_dom     = tk.Label(fgbar, text="BTC Dom: —",
                                    bg="#030C18", fg=TXT, font=("Courier New", 9))
        self.lbl_dom.pack(side="left", padx=10)
        self.lbl_mcap    = tk.Label(fgbar, text="MCap: —",
                                    bg="#030C18", fg=TXT, font=("Courier New", 9))
        self.lbl_mcap.pack(side="left", padx=10)
        self.lbl_vol     = tk.Label(fgbar, text="24h Vol: —",
                                    bg="#030C18", fg=TXT, font=("Courier New", 9))
        self.lbl_vol.pack(side="left", padx=10)

        # ── SUB BAR ───────────────────────────────────────────
        sb = tk.Frame(self, bg=PNL, height=28)
        sb.pack(fill="x"); sb.pack_propagate(False)
        tk.Label(sb, text="Next:", bg=PNL, fg=DIM, font=("Arial", 8)).pack(side="left", padx=(10,2), pady=5)
        self.lbl_next = tk.Label(sb, text="—", bg=PNL, fg=BLU, font=("Courier New Bold", 9))
        self.lbl_next.pack(side="left")
        tk.Label(sb, text="  OI Filter:", bg=PNL, fg=DIM, font=("Arial", 8)).pack(side="left", padx=(14,2))
        tk.Label(sb, text=f"LONG≥+{OI_LONG_FILTER}%  SHORT≥+{OI_SHORT_FILTER}%",
                 bg=PNL, fg=GRN, font=("Courier New", 8)).pack(side="left")

        # ── MT5 PANEL ─────────────────────────────────────────
        mt5_pnl = tk.Frame(self, bg="#030C18")
        mt5_pnl.pack(fill="x")

        left_m = tk.Frame(mt5_pnl, bg="#030C18")
        left_m.pack(side="left", fill="x", expand=True, padx=10, pady=3)

        tk.Label(left_m, text="ACCOUNT:", bg="#030C18", fg=DIM,
                 font=("Arial Bold", 7)).grid(row=0, column=0, sticky="w")
        acct_labels = [a[0] for a in MT5_ACCOUNTS]
        self._acct_var = tk.StringVar(value=acct_labels[0])
        self._acct_drop = ttk.Combobox(left_m, textvariable=self._acct_var,
                                        values=acct_labels, state="readonly",
                                        width=18, font=("Courier New", 8))
        self._acct_drop.grid(row=0, column=1, padx=(4,0))
        self._acct_drop.bind("<<ComboboxSelected>>", self._on_account_change)

        tk.Label(left_m, text="  Status:", bg="#030C18", fg=DIM,
                 font=("Arial", 7)).grid(row=0, column=2, padx=(10,2), sticky="w")
        self.lbl_mt5_conn = tk.Label(left_m, text="⬤ DISCONNECTED",
                                     bg="#030C18", fg=RED, font=("Courier New Bold", 8))
        self.lbl_mt5_conn.grid(row=0, column=3)

        tk.Label(left_m, text="  Balance:", bg="#030C18", fg=DIM,
                 font=("Arial", 7)).grid(row=0, column=4, padx=(10,2), sticky="w")
        self.lbl_mt5_bal = tk.Label(left_m, text="—", bg="#030C18",
                                    fg=GLD, font=("Courier New Bold", 8))
        self.lbl_mt5_bal.grid(row=0, column=5)

        tk.Label(left_m, text="  SL:", bg="#030C18", fg=DIM,
                 font=("Arial", 7)).grid(row=0, column=6, padx=(10,2), sticky="w")
        tk.Label(left_m, text=f"{MT5_STOP_LOSS_PCT}%",
                 bg="#030C18", fg="#E17070", font=("Courier New", 8)).grid(row=0, column=7)

        tk.Label(left_m, text="  TP:", bg="#030C18", fg=DIM,
                 font=("Arial", 7)).grid(row=0, column=8, padx=(8,2), sticky="w")
        tk.Label(left_m, text=f"{MT5_STOP_LOSS_PCT*MT5_TP_RATIO:.1f}%",
                 bg="#030C18", fg=GRN, font=("Courier New", 8)).grid(row=0, column=9)

        right_m = tk.Frame(mt5_pnl, bg="#030C18")
        right_m.pack(side="right", padx=10, pady=3)

        tog_txt = "🤖 AUTO-TRADE: ON" if self._auto_trade_on else "🤖 AUTO-TRADE: OFF"
        tog_bg  = "#0A3D1A" if self._auto_trade_on else "#1C1C1C"
        tog_fg  = GRN if self._auto_trade_on else DIM
        self.btn_toggle = tk.Button(right_m, text=tog_txt,
                                    bg=tog_bg, fg=tog_fg, font=("Arial Bold", 9),
                                    relief="flat", padx=14, pady=3,
                                    command=self._toggle_auto, cursor="hand2")
        self.btn_toggle.pack(side="left", padx=(0, 6))

        self.btn_test = tk.Button(right_m, text="🔗 Test MT5",
                                   bg="#0A1A3D", fg=CYN, font=("Arial", 9),
                                   relief="flat", padx=12, pady=3,
                                   command=self._test_mt5, cursor="hand2")
        self.btn_test.pack(side="left")

        tk.Frame(self, bg="#0A1628", height=2).pack(fill="x")

        # ── MAIN AREA ─────────────────────────────────────────
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=6, pady=4)

        # Left — table
        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="CRYPTO OI SIGNALS",
                 bg=BG, fg=DIM, font=("Arial Bold", 8)).pack(anchor="w", padx=4, pady=(2,0))

        tbl = tk.Frame(left, bg=PNL)
        tbl.pack(fill="both", expand=True, padx=2)

        cols = ("Symbol","Price","24h%","OI($B)","OI_CHG%","Funding","L/S","F&G","Score","Signal")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings",
                                 height=12, selectmode="none")
        col_w = [80, 100, 60, 70, 70, 72, 55, 45, 50, 140]
        for c, w in zip(cols, col_w):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="center")

        sty = ttk.Style(); sty.theme_use("clam")
        sty.configure("Treeview", background=PNL, foreground=TXT,
                      fieldbackground=PNL, rowheight=24, font=("Courier New", 8))
        sty.configure("Treeview.Heading", background="#08142A",
                      foreground=DIM, font=("Arial Bold", 7))
        sty.map("Treeview", background=[("selected", "#0A1E3C")])

        self.tree.tag_configure("strong_long",  foreground="#00FF88")
        self.tree.tag_configure("weak_long",    foreground=GRN)
        self.tree.tag_configure("strong_short", foreground="#FF3333")
        self.tree.tag_configure("weak_short",   foreground=RED)
        self.tree.tag_configure("no_trade",     foreground=DIM)
        self.tree.tag_configure("err",          foreground="#333")

        vsb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.lbl_best = tk.Label(left, text="TOP SIGNAL: —",
                                 bg="#030D04", fg=GLD,
                                 font=("Arial Bold", 10), pady=6)
        self.lbl_best.pack(fill="x", padx=2, pady=(2,0))

        # Right — log
        right = tk.Frame(main, bg=BG, width=310)
        right.pack(side="right", fill="y", padx=(4,0))
        right.pack_propagate(False)
        tk.Label(right, text="ACTIVITY LOG", bg=BG, fg=DIM,
                 font=("Arial Bold", 8)).pack(anchor="w", pady=(2,0))
        self.log_box = scrolledtext.ScrolledText(
            right, bg="#030810", fg=TXT, font=("Courier New", 7),
            state="disabled", wrap="word", relief="flat")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_configure("grn", foreground=GRN)
        self.log_box.tag_configure("red", foreground=RED)
        self.log_box.tag_configure("gld", foreground=GLD)

        # ── BUTTON BAR ────────────────────────────────────────
        bf = tk.Frame(self, bg=BG)
        bf.pack(fill="x", padx=6, pady=4)

        self.btn_start = tk.Button(bf, text="▶  START",
            bg="#0A3D1A", fg=GRN, font=("Arial Bold", 10),
            relief="flat", padx=20, pady=6,
            command=self.start_fetcher, cursor="hand2")
        self.btn_start.pack(side="left", padx=4)

        self.btn_stop = tk.Button(bf, text="■  STOP",
            bg="#3D0A0A", fg=RED, font=("Arial Bold", 10),
            relief="flat", padx=20, pady=6,
            command=self.stop_fetcher, cursor="hand2", state="disabled")
        self.btn_stop.pack(side="left", padx=4)

        self.btn_now = tk.Button(bf, text="⟳  FETCH NOW",
            bg="#0A1E3C", fg=BLU, font=("Arial Bold", 10),
            relief="flat", padx=20, pady=6,
            command=self.fetch_now, cursor="hand2")
        self.btn_now.pack(side="left", padx=4)

        tk.Label(bf, text=f"v{APP_VER}  |  {FETCH_SEC}s  |  24/7",
                 bg=BG, fg=DIM, font=("Arial", 7)).pack(side="right", padx=8)

    # ── AUTO-TRADE TOGGLE ─────────────────────────────────────
    def _toggle_auto(self):
        global MT5_AUTO_TRADE
        self._auto_trade_on = not self._auto_trade_on
        MT5_AUTO_TRADE = self._auto_trade_on
        if self._auto_trade_on:
            if not MT5_LOGIN or not MT5_PASSWORD or not MT5_SERVER:
                messagebox.showwarning("Credentials Missing",
                    "MT5_LOGIN / PASSWORD / SERVER set nahi!\n"
                    "File mein MT5_ACCOUNTS fill karo.")
                self._auto_trade_on = False; MT5_AUTO_TRADE = False; return
            ok = messagebox.askyesno("⚠️ Live Trading",
                f"AUTO-TRADE ON karna chahte ho?\n\n"
                f"Account: {MT5_LOGIN}\nServer:  {MT5_SERVER}\n"
                f"SL: {MT5_STOP_LOSS_PCT}%  TP: {MT5_STOP_LOSS_PCT*MT5_TP_RATIO:.1f}%\n"
                f"Risk:    {RISK_PCT}% per trade\n\n"
                f"Real money trades place honge!")
            if not ok:
                self._auto_trade_on = False; MT5_AUTO_TRADE = False; return
            self.btn_toggle.config(text="🤖 AUTO-TRADE: ON", bg="#0A3D1A", fg=GRN)
            self._append_log("AUTO-TRADE ENABLED ✅ — Live crypto trades!\n", "grn")
        else:
            self.btn_toggle.config(text="🤖 AUTO-TRADE: OFF", bg="#1C1C1C", fg=DIM)
            self._append_log("AUTO-TRADE DISABLED — Sirf signals.\n", "gld")

    # ── ACCOUNT CHANGE ────────────────────────────────────────
    def _on_account_change(self, event=None):
        sel = self._acct_var.get()
        for acct in MT5_ACCOUNTS:
            if acct[0] == sel:
                switch_account(*acct)
                self.lbl_mt5_conn.config(text="⬤ DISCONNECTED", fg=RED)
                self.lbl_mt5_bal.config(text="—")
                self._append_log(f"Account → {acct[0]}\n", "gld")
                break

    # ── TEST MT5 ──────────────────────────────────────────────
    def _test_mt5(self):
        self._append_log("MT5 test kar raha hoon...\n", "gld")
        self.btn_test.config(state="disabled", text="Testing...")
        def _run():
            ok = mt5_connect()
            def _ui():
                self.btn_test.config(state="normal", text="🔗 Test MT5")
                if ok and MT5_AVAILABLE:
                    try:
                        info = mt5.account_info()
                        self.lbl_mt5_conn.config(text="⬤ CONNECTED", fg=GRN)
                        self.lbl_mt5_bal.config(text=f"{info.balance:,.2f} {info.currency}")
                        self._append_log(
                            f"MT5 ✅ #{info.login} | ${info.balance:,.2f}\n", "grn")
                    except Exception as e:
                        self._append_log(f"MT5 info error: {e}\n", "red")
                else:
                    self.lbl_mt5_conn.config(text="⬤ FAILED", fg=RED)
                    self._append_log("MT5 ❌ — credentials check karo\n", "red")
            self.after(0, _ui)
        threading.Thread(target=_run, daemon=True).start()

    # ── FETCHER CONTROL ───────────────────────────────────────
    def _start_auto(self):
        self._append_log("Crypto OI Fetcher started — 24/7 market.\n", "grn")
        self.start_fetcher()

    def start_fetcher(self):
        global g_running
        if g_running: return
        g_running = True; g_stop_event.clear()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self._set_status("ACTIVE", GRN)
        self.thread = threading.Thread(
            target=fetcher_thread,
            args=(self._status_cb, self._next_cb, self._table_cb),
            daemon=True)
        self.thread.start()
        self._append_log("Fetcher STARTED\n", "grn")

    def stop_fetcher(self):
        g_stop_event.set()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self._set_status("STOPPED", RED)
        self._append_log("Fetcher STOPPED\n", "red")

    def fetch_now(self):
        self._append_log("Manual fetch...\n", "gld")
        def _run():
            try:
                data = do_fetch(self._status_cb, self._table_cb)
            except Exception as e:
                self._append_log(f"Error: {e}\n", "red")
        threading.Thread(target=_run, daemon=True).start()

    # ── CALLBACKS ─────────────────────────────────────────────
    def _status_cb(self, txt):
        colors = {"ACTIVE": GRN, "FETCHING": BLU, "STOPPED": RED, "SLEEPING": GLD}
        self.after(0, lambda: self._set_status(txt, colors.get(txt, GLD)))

    def _next_cb(self, txt):
        self.after(0, lambda: self.lbl_next.config(text=txt))

    def _table_cb(self, data):
        self.after(0, lambda: self._update_table(data))

    def _set_status(self, txt, color=GLD):
        icons = {"ACTIVE": "● ", "FETCHING": "⟳ ", "STOPPED": "■ ",
                 "SLEEPING": "◌ ", "IDLE": "○ "}
        self.lbl_status.config(text=f"{icons.get(txt,'● ')}{txt}", fg=color)

    def _append_log(self, msg, level="INFO"):
        tag = {"grn": "grn", "red": "red", "gld": "gld",
               "WARN": "gld", "ERROR": "red"}.get(level, None)
        def _do():
            self.log_box.config(state="normal")
            if tag: self.log_box.insert("end", msg, tag)
            else:   self.log_box.insert("end", msg)
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.after(0, _do)

    # ── TABLE UPDATE ──────────────────────────────────────────
    def _update_table(self, data):
        if not data or "symbols" not in data: return
        for row in self.tree.get_children():
            self.tree.delete(row)

        # Update market bar
        fg   = data.get("fear_greed", {})
        gl   = data.get("global", {})
        fg_v = fg.get("value", 50)
        fg_l = fg.get("label", "Neutral")

        if fg_v <= 25:   fg_emoji = "😱"
        elif fg_v <= 45: fg_emoji = "😨"
        elif fg_v <= 54: fg_emoji = "😐"
        elif fg_v <= 74: fg_emoji = "😏"
        else:            fg_emoji = "🤑"

        self.lbl_fg.config(text=f"{fg_emoji} F&G: {fg_v} — {fg_l.upper()}")

        dom  = gl.get("btc_dom", 0)
        mcap = gl.get("mcap", 0)
        vol  = gl.get("vol24h", 0)
        if dom:  self.lbl_dom.config(text=f"BTC Dom: {dom:.1f}%")
        if mcap: self.lbl_mcap.config(text=f"MCap: ${mcap/1e12:.2f}T")
        if vol:  self.lbl_vol.config(text=f"24h Vol: ${vol/1e9:.0f}B")

        best = data.get("best_symbol", "")

        for sym, d in data["symbols"].items():
            if not d.get("fetch_ok"):
                self.tree.insert("", "end",
                    values=(sym,"—","—","—","—","—","—","—","—","ERR"),
                    tags=("err",))
                continue

            sig    = d.get("signal", "NO_TRADE")
            score  = d.get("score", 0)
            price  = d.get("price", 0)
            ch24   = d.get("change_24h", 0)
            oi_cur = d.get("oi_current", 0)
            oi_pct = d.get("oi_change_pct", 0)
            fund   = d.get("funding_rate", 0)
            ls     = d.get("ls_ratio", 1.0)
            fg_val = d.get("fg_value", 50)
            star   = " ★" if sym == best else ""

            # format OI in billions
            oi_b = f"{oi_cur/1e9:.2f}" if oi_cur > 1e9 else f"{oi_cur/1e6:.1f}M"

            # Price format
            if price >= 1000:    p_fmt = f"${price:,.0f}"
            elif price >= 1:     p_fmt = f"${price:.4f}"
            else:                p_fmt = f"${price:.6f}"

            # Tag
            if "STRONG_LONG"  in sig: tag = "strong_long"
            elif "WEAK_LONG"  in sig: tag = "weak_long"
            elif "STRONG_SHORT" in sig: tag = "strong_short"
            elif "WEAK_SHORT" in sig: tag = "weak_short"
            else:                   tag = "no_trade"

            self.tree.insert("", "end", values=(
                sym,
                p_fmt,
                f"{ch24:+.2f}%",
                oi_b,
                f"{oi_pct:+.2f}%",
                f"{fund:+.4f}%",
                f"{ls:.2f}",
                str(fg_val),
                str(score),
                sig + star,
            ), tags=(tag,))

        # Best signal bar
        if best and best in data["symbols"]:
            d   = data["symbols"][best]
            sig = d.get("signal", "")
            sc  = d.get("score", 0)
            oi  = d.get("oi_change_pct", 0)
            fn  = d.get("funding_rate", 0)
            ls  = d.get("ls_ratio", 1.0)
            col = "#00FF88" if "LONG" in sig else "#FF3333" if "SHORT" in sig else GLD
            self.lbl_best.config(
                text=f"TOP SIGNAL:  {best}  {sig}  Score:{sc}"
                     f"  OI:{oi:+.2f}%  Fund:{fn:+.4f}%  L/S:{ls:.2f}",
                fg=col)
        else:
            self.lbl_best.config(text="TOP SIGNAL: Koi STRONG signal nahi — wait kar raha hoon...",
                                  fg=GLD)

    # ── CLOSE ─────────────────────────────────────────────────
    def on_close(self):
        if messagebox.askokcancel("Quit", "Crypto OI Fetcher band karna chahte ho?"):
            g_stop_event.set()
            mt5_disconnect()
            self.destroy()

# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = CryptoApp()
    app.mainloop()