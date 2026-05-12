"""
OI Crypto Trader - Railway Cloud Server
Fetches live OI data from Binance and serves it via API
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import urllib.request

PORT = int(os.environ.get("PORT", 10000))
symbol = "BTCUSDT"
latest_signal = {}
lock = threading.Lock()

def fetch_oi():
    while True:
        try:
            url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=10) as r:
                oi_data = json.loads(r.read())
            url2 = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url2, timeout=10) as r:
                px_data = json.loads(r.read())
            oi = float(oi_data["openInterest"])
            price = float(px_data["price"])
            now = datetime.now(tz=timezone.utc).isoformat()
            with lock:
                prev = latest_signal.get("current_oi", oi)
                prev_px = latest_signal.get("current_price", price)
                oi_chg = (oi - prev) / (prev + 1e-12) * 100
                px_chg = (price - prev_px) / (prev_px + 1e-12) * 100
                if oi_chg >= 0.5 and px_chg > 0.1:
                    sig = "BUY"
                    trend = "BULLISH_TREND"
                elif oi_chg <= -0.5 and px_chg > 0.1:
                    sig = "BUY"
                    trend = "SHORT_COVERING"
                elif oi_chg >= 0.5 and px_chg < -0.1:
                    sig = "SELL"
                    trend = "BEARISH_TREND"
                elif oi_chg <= -0.5 and px_chg < -0.1:
                    sig = "SELL"
                    trend = "LONG_LIQUIDATION"
                else:
                    sig = "NEUTRAL"
                    trend = "NEUTRAL"
                latest_signal.update({
                    "schema_version": 1,
                    "symbol": symbol,
                    "signal": sig,
                    "trend_label": trend,
                    "current_oi": oi,
                    "previous_oi": prev,
                    "oi_change_abs": oi - prev,
                    "oi_change_pct": oi_chg,
                    "current_price": price,
                    "previous_price": prev_px,
                    "price_change_pct": px_chg,
                    "published_at": now,
                    "timestamp": now,
                })
            print(f"[OI] {sig} | OI={oi:.0f} | Price={price:.0f} | OI_chg={oi_chg:.4f}%")
        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(30)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/signal":
            with lock:
                data = json.dumps(latest_signal).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        elif path in ("/", "/index.html"):
            try:
                html = Path("index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html)
            except:
                self.send_response(404)
                self.end_headers()
        elif path == "/manifest.json":
            try:
                data = Path("manifest.json").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except:
                self.send_response(404)
                self.end_headers()
        elif path == "/sw.js":
            try:
                data = Path("sw.js").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    t = threading.Thread(target=fetch_oi, daemon=True)
    t.start()
    print(f"[SERVER] Starting on port {PORT}")
    print(f"[SERVER] Starting on port {PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()