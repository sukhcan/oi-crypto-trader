"""
OI Dashboard Server v2 - PWA Edition
"""
import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SIGNAL_FILE = Path(__file__).parent / "signals" / "oi_signal.json"
PORT = 8765
SERVE_DIR = Path(__file__).parent

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js':   'application/javascript',
    '.json': 'application/json',
    '.png':  'image/png',
    '.ico':  'image/x-icon',
    '.css':  'text/css',
}

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.do_GET(head_only=True)

    def do_GET(self, head_only=False):
        path = self.path.split('?')[0]
        if path == '/signal':
            self._serve_signal(head_only)
        elif path in ('/', '/index.html', ''):
            self._serve_file(SERVE_DIR / 'index.html', head_only)
        elif path == '/manifest.json':
            self._serve_file(SERVE_DIR / 'manifest.json', head_only)
        elif path == '/sw.js':
            self._serve_file(SERVE_DIR / 'sw.js', head_only)
        else:
            f = SERVE_DIR / path.lstrip('/')
            if f.exists() and f.is_file():
                self._serve_file(f, head_only)
            else:
                self.send_response(404)
                self.end_headers()

    def _serve_signal(self, head_only=False):
        try:
            data = SIGNAL_FILE.read_text(encoding='utf-8')
            json.loads(data)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            if not head_only:
                self.wfile.write(data.encode())
        except FileNotFoundError:
            self._error(503, 'Signal file not found')
        except Exception as e:
            self._error(500, str(e))

    def _serve_file(self, path, head_only=False):
        try:
            data = path.read_bytes()
            mime = MIME.get(path.suffix, 'application/octet-stream')
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            if not head_only:
                self.wfile.write(data)
        except FileNotFoundError:
            self._error(404, f'{path.name} not found')

    def _error(self, code, msg):
        body = json.dumps({'error': msg}).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # silent

def main():
    ip = get_local_ip()
    print('=' * 55)
    print('  OI Crypto Trader - PWA Server v2')
    print('=' * 55)
    print(f'  PC browser  : http://localhost:{PORT}')
    print(f'  Mobile      : http://{ip}:{PORT}')
    print(f'  Signal API  : http://localhost:{PORT}/signal')
    print(f'  Manifest    : http://localhost:{PORT}/manifest.json')
    print('  Ctrl+C se band karo')
    print('=' * 55)
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[server] Band ho gaya.')

if __name__ == '__main__':
    main()
