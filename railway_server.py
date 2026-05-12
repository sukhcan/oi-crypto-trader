import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request

PORT = int(os.environ.get("PORT", 10000))
symbol = "BTCUSDT"
latest_signal = {}
lock = threading.Lock()

def fetch_oi():
    global latest_signal
    prev_oi = None
    prev_px = None
    while True:
        try:
            url1 = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
            with urllib.request.urlopen(url1, timeout=10) as r:
                oi_data = json.loads(r.read())
            url2 = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url2, timeout=10) as r:
                px_data = json.loads(r.read())
            oi = float(oi_data["openInterest"])
            price = float(px_data["price"])
            if prev_oi is None:
                prev_oi = oi
                prev_px = price
            oi_chg = (oi - prev_oi) / (prev_oi + 1e-12) * 100
            px_chg = (price - prev_px) / (prev_px + 1e-12) * 100
            if oi_chg >= 0.5 and px_chg > 0.1:
                sig, trend = "BUY", "BULLISH_TREND"
            elif oi_chg <= -0.5 and px_chg > 0.1:
                sig, trend = "BUY", "SHORT_COVERING"
            elif oi_chg >= 0.5 and px_chg < -0.1:
                sig, trend = "SELL", "BEARISH_TREND"
            elif oi_chg <= -0.5 and px_chg < -0.1:
                sig, trend = "SELL", "LONG_LIQUIDATION"
            else:
                sig, trend = "NEUTRAL", "NEUTRAL"
            now = datetime.now(tz=timezone.utc).isoformat()
            with lock:
                latest_signal = {
                    "schema_version": 1,
                    "symbol": symbol,
                    "signal": sig,
                    "trend_label": trend,
                    "current_oi": oi,
                    "previous_oi": prev_oi,
                    "oi_change_abs": oi - prev_oi,
                    "oi_change_pct": oi_chg,
                    "current_price": price,
                    "previous_price": prev_px,
                    "price_change_pct": px_chg,
                    "published_at": now,
                    "timestamp": now,
                }
            print(f"[OI] {sig} OI={oi:.0f} Price={price:.0f} OI_chg={oi_chg:.4f}%", flush=True)
            prev_oi = oi
            prev_px = price
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
        time.sleep(30)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/signal":
            with lock:
                data = json.dumps(latest_signal if latest_signal else {"status": "loading"}).encode()
            self._send(200, "application/json", data)
        elif path in ("/", "/index.html"):
            try:
                html = open("index.html", "rb").read()
                self._send(200, "text/html", html)
            except:
                self._send(200, "text/html", b"<h1>OI Trader Live</h1>")
        elif path == "/manifest.json":
            try:
                d = open("manifest.json", "rb").read()
                self._send(200, "application/json", d)
            except:
                self._send(404, "text/plain", b"not found")
        elif path == "/sw.js":
            try:
                d = open("sw.js", "rb").read()
                self._send(200, "application/javascript", d)
            except:
                self._send(404, "text/plain", b"not found")
        else:
            self._send(404, "text/plain", b"not found")

    def do_HEAD(self):
        self._send(200, "text/plain", b"")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}", flush=True)

if __name__ == "__main__":
    print(f"[SERVER] Starting on PORT={PORT}", flush=True)
    t = threading.Thread(target=fetch_oi, daemon=True)
    t.start()
    print(f"[SERVER] OI fetch thread started", flush=True)
    print(f"[SERVER] Listening on 0.0.0.0:{PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()