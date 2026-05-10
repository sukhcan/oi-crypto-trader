#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OI Fetcher Pro v2.0 — Professional Edition
Login System + System Tray + Multi-User + Background Service
"""

import os, sys, io, time, json, zipfile, logging, threading, subprocess
import traceback, hashlib, secrets, sqlite3
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests, pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── APP PATHS ─────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH      = DATA_DIR / "users.db"
CONFIG_PATH  = DATA_DIR / "config.json"
LOG_PATH     = DATA_DIR / "oi_fetcher.log"
SESSION_PATH = DATA_DIR / "session.json"

# ── CONFIG ────────────────────────────────────────────────────────
APP_NAME   = "OI Fetcher Pro"
APP_VER    = "2.0"
FETCH_SEC  = 300
START_HOUR = 11
END_HOUR   = 23

SYMBOLS = {
    "EURUSD": {"cftc_name": "EURO FX",          "cftc_exclude": "EURO FX/", "type": "major"},
    "USDJPY": {"cftc_name": "JAPANESE YEN",      "cftc_exclude": "EURO FX/", "type": "major"},
    "GBPUSD": {"cftc_name": "BRITISH POUND",     "cftc_exclude": "EURO FX/", "type": "major"},
    "USDCHF": {"cftc_name": "SWISS FRANC",       "cftc_exclude": "",         "type": "major"},
    "AUDUSD": {"cftc_name": "AUSTRALIAN DOLLAR", "cftc_exclude": "",         "type": "major"},
    "USDCAD": {"cftc_name": "CANADIAN DOLLAR",   "cftc_exclude": "",         "type": "major"},
    "NZDUSD": {"cftc_name": "NZ DOLLAR",         "cftc_exclude": "",         "type": "major"},
    "EURJPY": {"cftc_name": "EURO FX",           "cftc_exclude": "EURO FX/", "type": "minor"},
    "GBPJPY": {"cftc_name": "BRITISH POUND",     "cftc_exclude": "EURO FX/", "type": "minor"},
    "EURGBP": {"cftc_name": "EURO FX",           "cftc_exclude": "EURO FX/", "type": "minor"},
    "AUDJPY": {"cftc_name": "AUSTRALIAN DOLLAR", "cftc_exclude": "",         "type": "minor"},
    "CADJPY": {"cftc_name": "CANADIAN DOLLAR",   "cftc_exclude": "",         "type": "minor"},
    "CHFJPY": {"cftc_name": "SWISS FRANC",       "cftc_exclude": "",         "type": "minor"},
    "XAUUSD": {"cftc_name": "GOLD",              "cftc_exclude": "MINI",     "type": "commodity"},
}

OI_BUY_FILTER  =  1.0
OI_SELL_FILTER = -1.0

MT5_PATHS = [
    r"C:\Users\DeAL\AppData\Roaming\MetaQuotes\Terminal\30DFCE03904134F21E85FDA4A06D4D35\MQL5\Files",
    r"C:\Users\DeAL\AppData\Roaming\MetaQuotes\Terminal\4AB1FF510CA40454D57B5C02C860DEAE\MQL5\Files",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Accept": "*/*",
}

# ── ROLES ─────────────────────────────────────────────────────────
ROLE_ADMIN  = "admin"   # Full access: users, settings, fetch
ROLE_CLIENT = "client"  # View only: signals table, no settings

# ── GLOBALS ───────────────────────────────────────────────────────
g_running    = False
g_stop_event = threading.Event()
g_cycle      = 0
g_last_data  = {}
g_log_cb     = None
g_current_user = None  # logged-in user dict

# ── LOGGING ───────────────────────────────────────────────────────
logger = logging.getLogger("OI")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s | %(message)s", datefmt="%H:%M:%S")
try:
    _fh = RotatingFileHandler(str(LOG_PATH), maxBytes=3_000_000, backupCount=2, encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
except Exception:
    pass

def log(msg, level="INFO"):
    if level == "ERROR": logger.error(msg)
    elif level == "WARN": logger.warning(msg)
    else: logger.info(msg)
    if g_log_cb:
        g_log_cb(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n", level)

# ══════════════════════════════════════════════════════════════════
#  USER DATABASE — SQLite
# ══════════════════════════════════════════════════════════════════
def init_db():
    """Create users table if not exists."""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username  TEXT UNIQUE NOT NULL,
            passhash  TEXT NOT NULL,
            salt      TEXT NOT NULL,
            role      TEXT NOT NULL DEFAULT 'client',
            active    INTEGER NOT NULL DEFAULT 1,
            created   TEXT,
            last_login TEXT
        )
    """)
    conn.commit()
    # Create default admin if no users exist
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        _create_user_db(conn, "admin", "admin123", ROLE_ADMIN)
        print("[DB] Default admin created: admin / admin123")
        print("[DB] IMPORTANT: Change password after first login!")
    conn.close()

def _hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(32)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return h.hex(), salt

def _create_user_db(conn, username, password, role):
    ph, salt = _hash_password(password)
    conn.execute(
        "INSERT INTO users (username,passhash,salt,role,active,created) VALUES (?,?,?,?,1,?)",
        (username.lower().strip(), ph, salt, role,
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()

def create_user(username, password, role=ROLE_CLIENT):
    try:
        conn = sqlite3.connect(str(DB_PATH))
        _create_user_db(conn, username, password, role)
        conn.close()
        return True, "User created"
    except sqlite3.IntegrityError:
        return False, "Username already exists"
    except Exception as e:
        return False, str(e)

def verify_login(username, password):
    """Returns user dict if valid, else None."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        c = conn.cursor()
        c.execute("SELECT id,username,passhash,salt,role,active FROM users WHERE username=?",
                  (username.lower().strip(),))
        row = c.fetchone()
        if not row:
            conn.close(); return None
        uid, uname, stored_hash, salt, role, active = row
        if not active:
            conn.close(); return None
        ph, _ = _hash_password(password, salt)
        if ph != stored_hash:
            conn.close(); return None
        # Update last_login
        conn.execute("UPDATE users SET last_login=? WHERE id=?",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), uid))
        conn.commit(); conn.close()
        return {"id": uid, "username": uname, "role": role}
    except Exception as e:
        log(f"Login error: {e}", "ERROR")
        return None

def get_all_users():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("SELECT id,username,role,active,created,last_login FROM users ORDER BY id")
    rows = c.fetchall(); conn.close()
    return rows

def update_user_password(username, new_password):
    ph, salt = _hash_password(new_password)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE users SET passhash=?,salt=? WHERE username=?",
                 (ph, salt, username.lower()))
    conn.commit(); conn.close()

def toggle_user_active(uid, active):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, uid))
    conn.commit(); conn.close()

def delete_user(uid):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit(); conn.close()

# ══════════════════════════════════════════════════════════════════
#  MT5 PATH FINDER
# ══════════════════════════════════════════════════════════════════
def find_mt5_paths():
    found = []
    for raw in MT5_PATHS:
        p = Path(raw)
        if p.exists():
            found.append(p)
            log(f"Terminal OK: {p.parent.parent.name[:14]}...")
        else:
            log(f"Terminal missing: {p.parent.parent.name[:14]}...", "WARN")
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        mt_root = Path(appdata) / "MetaQuotes" / "Terminal"
        if mt_root.exists():
            for td in mt_root.iterdir():
                if not td.is_dir(): continue
                mf = td / "MQL5" / "Files"
                if mf.exists() and mf not in found:
                    found.append(mf); log(f"Auto-found: {td.name[:14]}...")
    if not found:
        found.append(Path(".")); log("No MT5 found — current dir", "WARN")
    return found

# ══════════════════════════════════════════════════════════════════
#  CFTC DOWNLOAD + EXTRACT
# ══════════════════════════════════════════════════════════════════
def download_df(urls):
    sess = requests.Session(); sess.headers.update(HEADERS)
    for url in urls:
        fname = url.split('/')[-1]
        try:
            log(f"Downloading: {fname}")
            r = sess.get(url, timeout=60)
            if r.status_code != 200: continue
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            files = [n for n in zf.namelist() if n.lower().endswith(('.xls','.xlsx','.csv'))]
            if not files: continue
            raw = zf.read(files[0])
            try:    df = pd.read_excel(io.BytesIO(raw))
            except: df = pd.read_csv(io.BytesIO(raw), encoding='latin-1', low_memory=False)
            log(f"Loaded {len(df):,} rows")
            return df
        except Exception as e:
            log(f"Download error {fname}: {e}", "WARN")
    return None

def get_forex_df():
    return download_df([
        "https://www.cftc.gov/files/dea/history/fut_fin_xls_2026.zip",
        "https://www.cftc.gov/files/dea/history/fut_fin_xls_2025.zip",
    ])

def get_gold_df():
    return download_df([
        "https://www.cftc.gov/files/dea/history/fut_disagg_xls_2026.zip",
        "https://www.cftc.gov/files/dea/history/fut_disagg_xls_2025.zip",
    ])

def extract_symbol(df, symbol, cfg):
    sym_type = cfg.get("type", "major")
    try:
        name_col = None
        for col in df.columns:
            if any(k in str(col).lower() for k in ['market','name','contract','commodity']):
                name_col = col; break
        if name_col is None:
            return err_rec(symbol, "Name col not found", sym_type)

        mask = df[name_col].astype(str).str.upper().str.contains(cfg["cftc_name"].upper(), na=False)
        if cfg["cftc_exclude"]:
            mask &= ~df[name_col].astype(str).str.upper().str.contains(cfg["cftc_exclude"].upper(), na=False)
        sym_df = df[mask].copy()
        if len(sym_df) < 2:
            return err_rec(symbol, f"Only {len(sym_df)} rows", sym_type)

        oi_col = None
        for name in ['Open_Interest_All','OI_All','Open_Interest_all','open_interest_all',
                     'Oi_All','OPEN INTEREST ALL','Open_Int_All']:
            if name in sym_df.columns: oi_col = name; break
        if oi_col is None:
            for col in sym_df.columns:
                cl = str(col).lower()
                if 'open' in cl and 'int' in cl: oi_col = col; break
        if oi_col is None:
            return err_rec(symbol, "OI col not found", sym_type)

        sym_df = sym_df.copy()
        sym_df[oi_col] = pd.to_numeric(
            sym_df[oi_col].astype(str).str.replace(',','',regex=False).str.strip(), errors='coerce')
        sym_df = sym_df[sym_df[oi_col].notna() & (sym_df[oi_col] > 0)]
        if len(sym_df) < 2:
            return err_rec(symbol, "Not enough valid OI rows", sym_type)

        date_sort = None
        for col in sym_df.columns:
            if 'yymmdd' in str(col).lower() or 'as_of' in str(col).lower():
                date_sort = col; break
        date_disp = None
        for col in sym_df.columns:
            if 'mm_dd_yyyy' in str(col).lower() or 'report_date' in str(col).lower():
                date_disp = col; break

        if date_sort:
            sym_df['_sk'] = pd.to_numeric(sym_df[date_sort].astype(str).str.strip(), errors='coerce')
            sym_df = sym_df.dropna(subset=['_sk'])
            sym_df = sym_df.sort_values('_sk', ascending=False).drop_duplicates(subset=['_sk'])

        if len(sym_df) < 2:
            return err_rec(symbol, "Not enough rows after sort", sym_type)

        cur_oi  = int(sym_df.iloc[0][oi_col])
        prev_oi = int(sym_df.iloc[1][oi_col])
        oi_chg  = cur_oi - prev_oi
        oi_pct  = round((oi_chg / prev_oi * 100) if prev_oi else 0.0, 2)

        if abs(oi_pct) > 150:
            log(f"[{symbol}] OI% {oi_pct:.1f}% too high — capped", "WARN")
            oi_pct = 0.0; oi_chg = 0

        rdate = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if date_disp:
            try: rdate = pd.to_datetime(sym_df.iloc[0][date_disp]).strftime("%Y-%m-%d")
            except: pass
        elif date_sort:
            try:
                raw = str(int(sym_df.iloc[0]['_sk'])).zfill(6)
                rdate = f"20{raw[:2]}-{raw[2:4]}-{raw[4:6]}"
            except: pass

        if oi_pct >= OI_BUY_FILTER:   trend, sig = "BULLISH", "WATCH_BUY"
        elif oi_pct <= OI_SELL_FILTER: trend, sig = "BEARISH", "WATCH_SELL"
        else:                          trend, sig = "NEUTRAL",  "NO_TRADE"

        cot_l = cot_s = 0
        for src, attr in [('NonComm_Positions_Long_All','l'),('NonComm_Positions_Short_All','s')]:
            if src in sym_df.columns:
                try:
                    v = pd.to_numeric(str(sym_df.iloc[0][src]).replace(',',''), errors='coerce')
                    if pd.notna(v):
                        if attr=='l': cot_l=int(v)
                        else: cot_s=int(v)
                except: pass
        cot_net = cot_l - cot_s
        spec_bias = 'LONG_BIAS' if cot_net>0 else 'SHORT_BIAS' if cot_net<0 else 'NEUTRAL'

        return {
            "symbol": symbol, "type": sym_type,
            "current_oi": cur_oi, "previous_oi": prev_oi,
            "oi_change": oi_chg, "oi_change_pct": oi_pct,
            "trend": trend, "signal": sig,
            "source": "CFTC_COT", "report_date": rdate,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fetch_status": "OK", "error_message": "",
            "cot_noncomm_long": cot_l, "cot_noncomm_short": cot_s,
            "cot_net_speculative": cot_net, "cot_spec_bias": spec_bias,
        }
    except Exception as e:
        log(f"[{symbol}] {e}", "ERROR")
        return err_rec(symbol, str(e)[:80], sym_type)

def err_rec(sym, msg, t):
    return {
        "symbol": sym, "type": t, "current_oi": 0, "previous_oi": 0,
        "oi_change": 0, "oi_change_pct": 0.0, "trend": "NEUTRAL", "signal": "NO_TRADE",
        "source": "ERROR", "report_date": "—",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetch_status": "ERROR", "error_message": msg,
        "cot_noncomm_long": 0, "cot_noncomm_short": 0,
        "cot_net_speculative": 0, "cot_spec_bias": "NEUTRAL",
    }

def check_news():
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         timeout=10, headers=HEADERS)
        if r.status_code != 200: return []
        events = r.json()
        now_utc = datetime.now(timezone.utc)
        affected = []
        CTS = {
            "USD": ["EURUSD","USDJPY","GBPUSD","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD"],
            "EUR": ["EURUSD","EURJPY","EURGBP"], "GBP": ["GBPUSD","GBPJPY","EURGBP"],
            "JPY": ["USDJPY","EURJPY","GBPJPY","AUDJPY","CADJPY","CHFJPY"],
            "AUD": ["AUDUSD","AUDJPY"], "CAD": ["USDCAD","CADJPY"],
            "CHF": ["USDCHF","CHFJPY"], "NZD": ["NZDUSD"],
        }
        for ev in events:
            try:
                imp = str(ev.get("impact","")).upper()
                if imp not in ["HIGH","MEDIUM"]: continue
                ds = str(ev.get("date","")).strip().replace("Z","+00:00")
                try:
                    ev_dt = datetime.fromisoformat(ds)
                    if ev_dt.tzinfo is None: ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                    ev_utc = ev_dt.astimezone(timezone.utc)
                except ValueError:
                    ev_utc = datetime.strptime(ds[:19],"%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                diff = (ev_utc - now_utc).total_seconds() / 60.0
                if -30.0 <= diff <= 120.0:
                    country = str(ev.get("country","")).upper()
                    for s in CTS.get(country,[]):
                        if s not in affected: affected.append(s)
                    log(f"NEWS {imp}: {country} — {ev.get('title','')} in {diff:.0f}min")
            except: continue
        return affected
    except Exception as e:
        log(f"News check failed: {e}", "WARN"); return []

def write_json(data, path):
    try:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(p); return True
    except Exception as e:
        log(f"Write failed {path}: {e}", "ERROR"); return False

def do_fetch(mt5_paths):
    global g_cycle, g_last_data
    g_cycle += 1
    log(f"=== Cycle #{g_cycle} ===")
    df_forex = get_forex_df()
    df_gold  = get_gold_df()
    syms_data = {}
    for sym, cfg in SYMBOLS.items():
        df = df_gold if sym == "XAUUSD" else df_forex
        if df is not None:
            rec = extract_symbol(df, sym, cfg); syms_data[sym] = rec
            if rec["fetch_status"] == "OK":
                log(f"  {sym:<8} OI={rec['current_oi']:>10,}  {rec['oi_change_pct']:>+6.2f}%  {rec['signal']}")
            else:
                log(f"  {sym:<8} ERR: {rec['error_message']}", "WARN")
        else:
            syms_data[sym] = err_rec(sym, "Download failed", cfg["type"])

    news_blocked = check_news()
    for sym in news_blocked:
        if sym in syms_data:
            syms_data[sym]["news_blocked"] = True
            syms_data[sym]["signal"] = "NEWS_BLOCK"

    best_sym = None; best_pct = 0.0
    for sym, d in syms_data.items():
        if d["fetch_status"] != "OK" or sym in news_blocked: continue
        p = d["oi_change_pct"]
        if d["signal"] == "WATCH_BUY"  and p < OI_BUY_FILTER:  continue
        if d["signal"] == "WATCH_SELL" and p > OI_SELL_FILTER: continue
        if d["signal"] != "NO_TRADE" and abs(p) > best_pct:
            best_pct = abs(p); best_sym = sym

    buy_l  = [s for s,d in syms_data.items() if d["signal"]=="WATCH_BUY"  and d["oi_change_pct"]>=OI_BUY_FILTER]
    sell_l = [s for s,d in syms_data.items() if d["signal"]=="WATCH_SELL" and d["oi_change_pct"]<=OI_SELL_FILTER]

    combined = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetch_status": "OK" if df_forex else "ERROR",
        "total_symbols": len(SYMBOLS),
        "oi_filter_buy_pct": OI_BUY_FILTER, "oi_filter_sell_pct": OI_SELL_FILTER,
        "best_signal_symbol": best_sym or "",
        "best_signal": syms_data[best_sym]["signal"] if best_sym else "NO_TRADE",
        "best_oi_change_pct": syms_data[best_sym]["oi_change_pct"] if best_sym else 0.0,
        "buy_signals": buy_l, "sell_signals": sell_l,
        "news_blocked_symbols": news_blocked, "symbols": syms_data,
    }
    ok = 0
    for mp in mt5_paths:
        if write_json(combined, Path(mp)/"oi_multi_data.json"): ok += 1
        if "EURUSD" in syms_data:
            write_json(syms_data["EURUSD"], Path(mp)/"oi_data.json")
    log(f"Done | Written {ok}/{len(mt5_paths)} | Best:{best_sym or 'None'}")
    g_last_data = combined
    return combined

# ── SCHEDULE ─────────────────────────────────────────────────────
def in_hours(): return START_HOUR <= datetime.now().hour < END_HOUR
def secs_to_start():
    n = datetime.now()
    t = n.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    if n >= t: t += timedelta(days=1)
    return (t - n).total_seconds()

def fetcher_thread(mt5_paths, status_cb, next_cb, table_cb):
    global g_running
    while not g_stop_event.is_set():
        if in_hours():
            status_cb("FETCHING")
            try:
                data = do_fetch(mt5_paths)
                if data and table_cb: table_cb(data)
            except Exception as e:
                log(f"Cycle error: {e}\n{traceback.format_exc()[:300]}", "ERROR")
            if not g_stop_event.is_set() and in_hours():
                nxt = datetime.now() + timedelta(seconds=FETCH_SEC)
                next_cb(nxt.strftime("%H:%M:%S")); status_cb("ACTIVE")
                for _ in range(FETCH_SEC):
                    if g_stop_event.is_set(): break
                    time.sleep(1)
        else:
            w = secs_to_start(); h, m = int(w//3600), int((w%3600)//60)
            log(f"Outside hours. Next: {START_HOUR:02d}:00 in {h}h {m}m")
            status_cb("SLEEPING"); next_cb(f"{START_HOUR:02d}:00 AM (in {h}h {m}m)")
            for _ in range(min(int(w), 60)):
                if g_stop_event.is_set(): break
                time.sleep(1)
    g_running = False; status_cb("STOPPED"); log("Stopped.")

# ══════════════════════════════════════════════════════════════════
#  LOGIN WINDOW
# ══════════════════════════════════════════════════════════════════
class LoginWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — Login")
        self.geometry("420x520")
        self.resizable(False, False)
        self.configure(bg="#040810")
        self.result_user = None
        self._attempts  = 0
        self._locked_until = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        BG="#040810"; HDR="#05194A"
        GRN="#18B854"; RED="#C32D2D"; BLU="#4A91E1"
        DIM="#2D4E6E"; WH="#D7E6FF"

        # Header
        tk.Frame(self, bg=HDR, height=80).pack(fill="x")
        hdr = tk.Frame(self, bg=HDR); hdr.place(x=0,y=0,width=420,height=80)
        tk.Label(hdr, text=APP_NAME, bg=HDR, fg=WH, font=("Arial Bold",18)).pack(pady=(18,0))
        tk.Label(hdr, text=f"Professional Edition v{APP_VER}", bg=HDR, fg=DIM, font=("Arial",9)).pack()

        frm = tk.Frame(self, bg=BG); frm.pack(fill="both", expand=True, padx=40, pady=30)

        tk.Label(frm, text="Username", bg=BG, fg=DIM, font=("Arial",9)).pack(anchor="w", pady=(0,3))
        self.ent_user = tk.Entry(frm, font=("Arial",12), bg="#060F1C", fg=WH,
                                 insertbackground=BLU, relief="flat",
                                 highlightthickness=1, highlightcolor=BLU,
                                 highlightbackground=DIM)
        self.ent_user.pack(fill="x", ipady=8)

        tk.Label(frm, text="Password", bg=BG, fg=DIM, font=("Arial",9)).pack(anchor="w", pady=(18,3))
        self.ent_pass = tk.Entry(frm, font=("Arial",12), bg="#060F1C", fg=WH,
                                 show="●", insertbackground=BLU, relief="flat",
                                 highlightthickness=1, highlightcolor=BLU,
                                 highlightbackground=DIM)
        self.ent_pass.pack(fill="x", ipady=8)
        self.ent_pass.bind("<Return>", lambda e: self._login())

        # Remember me
        self.remember = tk.BooleanVar(value=True)
        tk.Checkbutton(frm, text="Remember me (stay logged in)", variable=self.remember,
                       bg=BG, fg=DIM, selectcolor="#060F1C",
                       activebackground=BG, font=("Arial",8)).pack(anchor="w", pady=(12,0))

        self.lbl_err = tk.Label(frm, text="", bg=BG, fg=RED, font=("Arial",9))
        self.lbl_err.pack(pady=(8,0))

        self.btn_login = tk.Button(frm, text="LOGIN", bg="#0A3D1A", fg=GRN,
                                   font=("Arial Bold",12), relief="flat",
                                   pady=10, cursor="hand2", command=self._login)
        self.btn_login.pack(fill="x", pady=(20,0))

        # Version info
        tk.Label(self, text=f"© 2026 OI Fetcher Pro | v{APP_VER}",
                 bg=BG, fg=DIM, font=("Arial",7)).pack(side="bottom", pady=8)

        self.ent_user.focus()

        # Check saved session
        self._check_saved_session()

    def _check_saved_session(self):
        """Auto-login if valid session exists."""
        try:
            if SESSION_PATH.exists():
                s = json.loads(SESSION_PATH.read_text())
                if s.get("remember") and s.get("username"):
                    # Verify user still exists and is active
                    conn = sqlite3.connect(str(DB_PATH))
                    c = conn.cursor()
                    c.execute("SELECT id,username,role,active FROM users WHERE username=?",
                              (s["username"],))
                    row = c.fetchone(); conn.close()
                    if row and row[3]:  # active
                        self.result_user = {"id":row[0],"username":row[1],"role":row[2]}
                        self.destroy()
        except Exception:
            pass

    def _login(self):
        if self._locked_until and datetime.now() < self._locked_until:
            remaining = (self._locked_until - datetime.now()).seconds
            self.lbl_err.config(text=f"Too many attempts. Wait {remaining}s")
            return

        uname = self.ent_user.get().strip()
        pwd   = self.ent_pass.get()
        if not uname or not pwd:
            self.lbl_err.config(text="Username and password required")
            return

        user = verify_login(uname, pwd)
        if user:
            self._attempts = 0
            # Save session if remember checked
            if self.remember.get():
                SESSION_PATH.write_text(json.dumps(
                    {"username": user["username"], "remember": True}))
            else:
                try: SESSION_PATH.unlink()
                except: pass
            self.result_user = user
            self.destroy()
        else:
            self._attempts += 1
            if self._attempts >= 5:
                self._locked_until = datetime.now() + timedelta(minutes=5)
                self.lbl_err.config(text="5 failed attempts — locked for 5 minutes")
            else:
                rem = 5 - self._attempts
                self.lbl_err.config(text=f"Invalid credentials ({rem} attempts left)")
            self.ent_pass.delete(0, tk.END)

# ══════════════════════════════════════════════════════════════════
#  USER MANAGEMENT WINDOW (Admin only)
# ══════════════════════════════════════════════════════════════════
class UserMgrWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("User Management")
        self.geometry("680x520")
        self.configure(bg="#040810")
        self._build()
        self._load_users()

    def _build(self):
        BG="#040810"; DIM="#2D4E6E"; WH="#D7E6FF"
        GRN="#18B854"; RED="#C32D2D"; BLU="#4A91E1"; GLD="#C3A018"

        # Title
        tk.Label(self, text="User Management", bg="#05194A", fg=WH,
                 font=("Arial Bold",13), pady=10).pack(fill="x")

        # Table
        frm = tk.Frame(self, bg=BG); frm.pack(fill="both", expand=True, padx=10, pady=6)
        cols = ("ID","Username","Role","Active","Created","Last Login")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=12)
        widths = [40,120,70,60,140,140]
        for c,w in zip(cols,widths):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,anchor="center")
        sty=ttk.Style(); sty.configure("Treeview",background="#060F1C",foreground=WH,
            fieldbackground="#060F1C",rowheight=22,font=("Courier New",8))
        self.tree.tag_configure("admin",foreground=GLD)
        self.tree.tag_configure("inactive",foreground=DIM)
        self.tree.pack(fill="both",expand=True)

        # Add user form
        add_frm = tk.LabelFrame(self, text="Add New User", bg=BG, fg=DIM,
                                 font=("Arial",9), padx=10, pady=8)
        add_frm.pack(fill="x", padx=10, pady=(0,6))

        r=0
        tk.Label(add_frm,text="Username",bg=BG,fg=DIM,font=("Arial",8)).grid(row=r,column=0,sticky="w",padx=4)
        self.ent_uname=tk.Entry(add_frm,bg="#060F1C",fg=WH,font=("Arial",9),relief="flat",width=18)
        self.ent_uname.grid(row=r,column=1,padx=4)
        tk.Label(add_frm,text="Password",bg=BG,fg=DIM,font=("Arial",8)).grid(row=r,column=2,sticky="w",padx=4)
        self.ent_pwd=tk.Entry(add_frm,bg="#060F1C",fg=WH,font=("Arial",9),show="●",relief="flat",width=18)
        self.ent_pwd.grid(row=r,column=3,padx=4)
        tk.Label(add_frm,text="Role",bg=BG,fg=DIM,font=("Arial",8)).grid(row=r,column=4,sticky="w",padx=4)
        self.role_var=tk.StringVar(value="client")
        tk.OptionMenu(add_frm,self.role_var,"client","admin").grid(row=r,column=5,padx=4)
        tk.Button(add_frm,text="Add User",bg="#0A3D1A",fg=GRN,font=("Arial Bold",9),
                  relief="flat",padx=12,command=self._add_user).grid(row=r,column=6,padx=8)

        # Action buttons
        btn_frm=tk.Frame(self,bg=BG); btn_frm.pack(fill="x",padx=10,pady=(0,8))
        tk.Button(btn_frm,text="Disable Selected",bg="#3D1A0A",fg=GLD,font=("Arial",9),
                  relief="flat",padx=10,pady=4,command=self._toggle_active).pack(side="left",padx=4)
        tk.Button(btn_frm,text="Delete Selected",bg="#3D0A0A",fg=RED,font=("Arial",9),
                  relief="flat",padx=10,pady=4,command=self._delete_user).pack(side="left",padx=4)
        tk.Button(btn_frm,text="Reset Password",bg="#0A1E3C",fg=BLU,font=("Arial",9),
                  relief="flat",padx=10,pady=4,command=self._reset_pwd).pack(side="left",padx=4)
        tk.Button(btn_frm,text="Refresh",bg=BG,fg=DIM,font=("Arial",9),
                  relief="flat",padx=10,pady=4,command=self._load_users).pack(side="right",padx=4)

    def _load_users(self):
        for row in self.tree.get_children(): self.tree.delete(row)
        for row in get_all_users():
            uid,uname,role,active,created,last_login = row
            tag = "admin" if role==ROLE_ADMIN else ("inactive" if not active else "")
            self.tree.insert("","end",
                values=(uid,uname,role,"Yes" if active else "No",
                        created or "—", last_login or "Never"),tags=(tag,))

    def _add_user(self):
        uname = self.ent_uname.get().strip()
        pwd   = self.ent_pwd.get()
        role  = self.role_var.get()
        if not uname or not pwd:
            messagebox.showwarning("Error","Username and password required",parent=self); return
        if len(pwd) < 6:
            messagebox.showwarning("Error","Password must be at least 6 characters",parent=self); return
        ok, msg = create_user(uname, pwd, role)
        if ok:
            self.ent_uname.delete(0,tk.END); self.ent_pwd.delete(0,tk.END)
            self._load_users()
            messagebox.showinfo("Success",f"User '{uname}' created as {role}",parent=self)
        else:
            messagebox.showerror("Error",msg,parent=self)

    def _get_selected(self):
        sel = self.tree.selection()
        if not sel: messagebox.showwarning("Select","Please select a user",parent=self); return None
        return self.tree.item(sel[0])["values"]

    def _toggle_active(self):
        row = self._get_selected()
        if not row: return
        uid, uname, role, active_str = row[0], row[1], row[2], row[3]
        if uname == g_current_user["username"]:
            messagebox.showwarning("Error","Cannot disable your own account",parent=self); return
        new_active = 0 if active_str == "Yes" else 1
        toggle_user_active(uid, new_active)
        self._load_users()

    def _delete_user(self):
        row = self._get_selected()
        if not row: return
        uid, uname = row[0], row[1]
        if uname == g_current_user["username"]:
            messagebox.showwarning("Error","Cannot delete your own account",parent=self); return
        if messagebox.askyesno("Confirm",f"Delete user '{uname}'?",parent=self):
            delete_user(uid); self._load_users()

    def _reset_pwd(self):
        row = self._get_selected()
        if not row: return
        uname = row[1]
        win = tk.Toplevel(self); win.title("Reset Password")
        win.geometry("300x160"); win.configure(bg="#040810")
        tk.Label(win,text=f"New password for '{uname}'",bg="#040810",fg="#D7E6FF",
                 font=("Arial",10)).pack(pady=(16,4))
        ent = tk.Entry(win,bg="#060F1C",fg="#D7E6FF",show="●",font=("Arial",11),
                       relief="flat",width=22); ent.pack(pady=4,ipady=6)
        def _do():
            p = ent.get()
            if len(p) < 6:
                messagebox.showwarning("Error","Min 6 characters",parent=win); return
            update_user_password(uname, p)
            messagebox.showinfo("Done",f"Password updated for '{uname}'",parent=win)
            win.destroy()
        tk.Button(win,text="Update",bg="#0A3D1A",fg="#18B854",font=("Arial Bold",10),
                  relief="flat",padx=20,pady=6,command=_do).pack(pady=8)

# ══════════════════════════════════════════════════════════════════
#  MAIN APP WINDOW
# ══════════════════════════════════════════════════════════════════
class MainApp(tk.Tk):
    def __init__(self, user):
        super().__init__()
        global g_current_user
        g_current_user = user
        self.user = user
        self.is_admin = (user["role"] == ROLE_ADMIN)
        self.title(f"{APP_NAME} v{APP_VER} — {user['username']} ({user['role']})")
        self.geometry("920x660")
        self.resizable(True, True)
        self.configure(bg="#040810")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.mt5_paths = []
        self.thread    = None
        self._build_ui()
        self._init_paths()
        global g_log_cb
        g_log_cb = self._append_log
        self.after(600, self._autostart)

    def _build_ui(self):
        BG="#040810"; HDR="#05194A"
        GRN="#18B854"; RED="#C32D2D"
        GLD="#C3A018"; BLU="#4A91E1"
        DIM="#2D4E6E"; TXT="#9BBEE6"; WH="#D7E6FF"

        # Header
        hdr=tk.Frame(self,bg=HDR,height=52); hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr,text=f"  {APP_NAME}",bg=HDR,fg=WH,font=("Arial Bold",14)).pack(side="left",pady=14)
        tk.Label(hdr,text=f"  v{APP_VER}",bg=HDR,fg=BLU,font=("Arial Bold",14)).pack(side="left",pady=14)
        tk.Label(hdr,text=f"  {START_HOUR:02d}:00—{END_HOUR:02d}:00 | {FETCH_SEC}s",
                 bg=HDR,fg=DIM,font=("Arial",9)).pack(side="left",pady=16)

        # User info + logout
        tk.Label(hdr,text=f"👤 {self.user['username'].upper()} ({self.user['role']})",
                 bg=HDR,fg=GLD if self.is_admin else TXT,
                 font=("Arial Bold",9)).pack(side="right",padx=6,pady=14)
        tk.Button(hdr,text="Logout",bg=HDR,fg=DIM,font=("Arial",8),relief="flat",
                  cursor="hand2",command=self._logout).pack(side="right",padx=2)

        self.lbl_status=tk.Label(hdr,text="○ IDLE",bg=HDR,fg=GLD,font=("Arial Bold",10))
        self.lbl_status.pack(side="right",padx=16)

        # Status bar
        sb=tk.Frame(self,bg="#060F1C",height=34); sb.pack(fill="x")
        sb.pack_propagate(False)
        tk.Label(sb,text="Next:",bg="#060F1C",fg=DIM,font=("Arial",8)).pack(side="left",padx=(10,2),pady=8)
        self.lbl_next=tk.Label(sb,text="—",bg="#060F1C",fg=BLU,font=("Courier New Bold",9))
        self.lbl_next.pack(side="left")
        tk.Label(sb,text="  Terminals:",bg="#060F1C",fg=DIM,font=("Arial",8)).pack(side="left",padx=(14,2))
        self.lbl_terms=tk.Label(sb,text="—",bg="#060F1C",fg=TXT,font=("Courier New",8))
        self.lbl_terms.pack(side="left")
        tk.Label(sb,text=f"  OI Filter: BUY≥+{OI_BUY_FILTER}%  SELL≤-{OI_SELL_FILTER}%",
                 bg="#060F1C",fg=GRN,font=("Courier New",8)).pack(side="left",padx=(14,0))

        # Main area
        main=tk.Frame(self,bg=BG); main.pack(fill="both",expand=True,padx=6,pady=4)

        # Left: Signal table
        left=tk.Frame(main,bg=BG); left.pack(side="left",fill="both",expand=True)
        tk.Label(left,text="OI SIGNALS",bg=BG,fg=DIM,font=("Arial Bold",8)).pack(anchor="w",padx=4,pady=(4,0))

        tbl=tk.Frame(left,bg="#060F1C"); tbl.pack(fill="both",expand=True,padx=2)
        cols=("Symbol","Type","OI","CHG%","Trend","Signal")
        self.tree=ttk.Treeview(tbl,columns=cols,show="headings",height=14,selectmode="none")
        for c,w in zip(cols,[72,65,115,70,82,120]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,anchor="center")
        sty=ttk.Style(); sty.theme_use("clam")
        sty.configure("Treeview",background="#060F1C",foreground=TXT,
            fieldbackground="#060F1C",rowheight=22,font=("Courier New",8))
        sty.configure("Treeview.Heading",background="#08142A",foreground=DIM,font=("Arial Bold",7))
        sty.map("Treeview",background=[("selected","#0A1E3C")])
        self.tree.tag_configure("buy",foreground=GRN)
        self.tree.tag_configure("sell",foreground=RED)
        self.tree.tag_configure("news",foreground=GLD)
        self.tree.tag_configure("neut",foreground=DIM)
        self.tree.tag_configure("err",foreground="#444")
        vsb=ttk.Scrollbar(tbl,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(side="left",fill="both",expand=True); vsb.pack(side="right",fill="y")

        self.lbl_best=tk.Label(left,text="TOP SIGNAL: —",bg="#030D04",
                                fg=GLD,font=("Arial Bold",10),pady=6)
        self.lbl_best.pack(fill="x",padx=2,pady=(2,0))

        # Right: Log (admin only sees full log)
        right=tk.Frame(main,bg=BG,width=300); right.pack(side="right",fill="y",padx=(4,0))
        right.pack_propagate(False)
        tk.Label(right,text="ACTIVITY LOG",bg=BG,fg=DIM,font=("Arial Bold",8)).pack(anchor="w",pady=(4,0))
        self.log_box=scrolledtext.ScrolledText(right,bg="#030810",fg=TXT,
            font=("Courier New",7),state="disabled",wrap="word",relief="flat")
        self.log_box.pack(fill="both",expand=True)
        self.log_box.tag_configure("grn",foreground=GRN)
        self.log_box.tag_configure("red",foreground=RED)
        self.log_box.tag_configure("gld",foreground=GLD)

        # Buttons
        bf=tk.Frame(self,bg=BG); bf.pack(fill="x",padx=6,pady=5)

        if self.is_admin:
            self.btn_start=tk.Button(bf,text="▶  START",bg="#0A3D1A",fg=GRN,
                font=("Arial Bold",10),relief="flat",padx=18,pady=6,
                command=self.start_fetcher,cursor="hand2")
            self.btn_start.pack(side="left",padx=3)

            self.btn_stop=tk.Button(bf,text="■  STOP",bg="#3D0A0A",fg=RED,
                font=("Arial Bold",10),relief="flat",padx=18,pady=6,
                command=self.stop_fetcher,cursor="hand2",state="disabled")
            self.btn_stop.pack(side="left",padx=3)

            self.btn_now=tk.Button(bf,text="⟳  FETCH NOW",bg="#0A1E3C",fg=BLU,
                font=("Arial Bold",10),relief="flat",padx=18,pady=6,
                command=self.fetch_now,cursor="hand2")
            self.btn_now.pack(side="left",padx=3)

            tk.Button(bf,text="📁 MT5 Folders",bg="#1A1A0A",fg=GLD,font=("Arial",9),
                relief="flat",padx=10,pady=6,command=self.open_folders,cursor="hand2").pack(side="left",padx=3)

            tk.Button(bf,text="👥 Users",bg="#1A0A3D",fg=BLU,font=("Arial",9),
                relief="flat",padx=10,pady=6,
                command=lambda:UserMgrWindow(self),cursor="hand2").pack(side="left",padx=3)
        else:
            # Client: only see status, no controls
            tk.Label(bf,text="View-only mode — signals update automatically",
                     bg=BG,fg=DIM,font=("Arial",9)).pack(side="left",padx=8)

        tk.Label(bf,text=f"v{APP_VER}",bg=BG,fg=DIM,font=("Arial",7)).pack(side="right",padx=8)

    def _init_paths(self):
        self.mt5_paths=find_mt5_paths()
        self.lbl_terms.config(text=f"{len(self.mt5_paths)} found")

    def _autostart(self):
        if self.is_admin:
            if in_hours():
                self._append_log("Trading hours — auto-starting...\n","grn")
                self.start_fetcher()
            else:
                self._append_log(f"Outside hours. Auto-starts at {START_HOUR:02d}:00.\n","gld")
        else:
            self._append_log("Connected — waiting for data updates.\n","grn")

    def start_fetcher(self):
        global g_running
        if g_running: return
        g_running=True; g_stop_event.clear()
        self.btn_start.config(state="disabled"); self.btn_stop.config(state="normal")
        self._set_status("ACTIVE","#18B854")
        self.thread=threading.Thread(target=fetcher_thread,
            args=(self.mt5_paths,self._status_cb,self._next_cb,self._table_cb),daemon=True)
        self.thread.start()
        self._append_log("Fetcher STARTED\n","grn")

    def stop_fetcher(self):
        g_stop_event.set()
        self.btn_start.config(state="normal"); self.btn_stop.config(state="disabled")
        self._set_status("STOPPED","#C32D2D")
        self._append_log("Fetcher STOPPED\n","red")

    def fetch_now(self):
        self._append_log("Manual fetch...\n","gld")
        def _run():
            try:
                data=do_fetch(self.mt5_paths)
                self.after(0,lambda:self._update_table(data))
            except Exception as e:
                self._append_log(f"Error: {e}\n","red")
        threading.Thread(target=_run,daemon=True).start()

    def open_folders(self):
        for p in self.mt5_paths:
            if Path(p).exists(): subprocess.Popen(f'explorer "{p}"')

    def _logout(self):
        if messagebox.askyesno("Logout","Logout karna chahte ho?",parent=self):
            try: SESSION_PATH.unlink()
            except: pass
            g_stop_event.set()
            self.destroy()
            # Restart login
            main()

    def _status_cb(self,txt):
        colors={"ACTIVE":"#18B854","SLEEPING":"#C3A018","FETCHING":"#4A91E1","STOPPED":"#C32D2D"}
        self.after(0,lambda:self._set_status(txt,colors.get(txt,"#C3A018")))

    def _next_cb(self,txt): self.after(0,lambda:self.lbl_next.config(text=txt))
    def _table_cb(self,data): self.after(0,lambda:self._update_table(data))

    def _set_status(self,txt,color="#C3A018"):
        icons={"ACTIVE":"● ","SLEEPING":"◌ ","FETCHING":"⟳ ","STOPPED":"■ ","IDLE":"○ "}
        self.lbl_status.config(text=f"{icons.get(txt,'● ')}{txt}",fg=color)

    def _append_log(self,msg,level="INFO"):
        tag={"ERROR":"red","WARN":"gld","grn":"grn","red":"red","gld":"gld"}.get(level,None)
        def _do():
            self.log_box.config(state="normal")
            if tag: self.log_box.insert("end",msg,tag)
            else:   self.log_box.insert("end",msg)
            self.log_box.see("end"); self.log_box.config(state="disabled")
        self.after(0,_do)

    def _update_table(self,data):
        if not data or "symbols" not in data: return
        for row in self.tree.get_children(): self.tree.delete(row)
        best=data.get("best_signal_symbol","")
        for sym,d in data["symbols"].items():
            if d["fetch_status"]!="OK":
                self.tree.insert("","end",values=(sym,d.get("type","—"),"—","—","—","ERR"),tags=("err",)); continue
            sig=d["signal"]
            tag="buy" if sig=="WATCH_BUY" else "sell" if sig=="WATCH_SELL" \
                else "news" if sig=="NEWS_BLOCK" else "neut"
            star=" ★" if sym==best else ""
            self.tree.insert("","end",
                values=(sym,d.get("type","—"),f"{d['current_oi']:,}",
                        f"{d['oi_change_pct']:+.2f}%",d['trend'][:4],sig+star),tags=(tag,))
        if best and best in data["symbols"]:
            d=data["symbols"][best]
            col="#18B854" if d["signal"]=="WATCH_BUY" else "#C32D2D"
            self.lbl_best.config(text=f"TOP SIGNAL:  {best}  {d['signal']}  ({d['oi_change_pct']:+.2f}%)",fg=col)
        else:
            self.lbl_best.config(text="TOP SIGNAL: No signal passing OI ±1% filter",fg="#C3A018")

    def on_close(self):
        if messagebox.askokcancel("Quit","OI Fetcher bandh karna chahte ho?"):
            g_stop_event.set(); self.destroy()

# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════
def main():
    init_db()
    login = LoginWindow()
    login.mainloop()
    user = login.result_user
    if not user:
        return  # window closed without login
    app = MainApp(user)
    app.mainloop()

if __name__ == "__main__":
    main()
