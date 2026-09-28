"""Temporary HTTP page for checking a Bothost custom domain.

Start with: python domain_probe.py
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PAGE = b"<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>ok</title><body>ok</body></html>"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or os.environ.get("WEBHOOK_LISTEN_PORT") or "8080")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
