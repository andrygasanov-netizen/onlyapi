"""TelegaStars API gateway for a separate Bothost domain.

Start command:
    python api_gateway.py

The main bot owns the API keys, balance, orders, and Stars delivery. This
process forwards only its three public developer API operations to that bot.
No Telegram bot token or API key is stored in this gateway.
"""

import json
import logging
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api_gateway")

# Этот адрес используется только сервером для связи с основным ботом.
# Клиенты обращаются к публичному https://bot-api.bothost.tech/api/v1.
UPSTREAM = os.environ.get(
    "TELEGASTARS_UPSTREAM_URL",
    "https://bot-1788890713-7094-andrey510913.bothost.tech",
).strip().rstrip("/")
PORT = int(os.environ.get("PORT") or os.environ.get("WEBHOOK_LISTEN_PORT") or "8080")
MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 1024 * 1024
ORDER_PATH = re.compile(r"/api/v1/stars/orders/[0-9]+\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never follow redirects with a customer's Bearer key attached.
        return None


opener = build_opener(NoRedirect)


def public_route(method: str, path: str) -> bool:
    if method == "GET":
        return path == "/api/v1/balance" or bool(ORDER_PATH.fullmatch(path))
    return method == "POST" and path == "/api/v1/stars/orders"


class Handler(BaseHTTPRequestHandler):
    server_version = "TelegaStarsAPI"

    def respond(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def respond_json(self, status: int, **data) -> None:
        self.respond(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                     "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path == "/":
            self.respond(200, b"ok", "text/plain; charset=utf-8")
            return
        if self.path == "/health":
            self.respond_json(200, status="ok")
            return
        self.relay("GET")

    def do_POST(self) -> None:
        self.relay("POST")

    def relay(self, method: str) -> None:
        # Reject unknown paths before reading a body or forwarding credentials.
        if not public_route(method, self.path):
            self.respond_json(404, error="not_found")
            return
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            self.respond_json(401, error="invalid_api_key")
            return

        body = None
        headers = {"Authorization": authorization, "Accept": "application/json"}
        if method == "POST":
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self.respond_json(411, error="content_length_required")
                return
            if not 0 <= size <= MAX_REQUEST_BYTES:
                self.respond_json(413, error="request_too_large")
                return
            body = self.rfile.read(size)
            headers["Content-Type"] = "application/json"
            idem = self.headers.get("Idempotency-Key", "")
            if idem:
                headers["Idempotency-Key"] = idem

        request = Request(UPSTREAM + self.path, data=body, headers=headers, method=method)
        try:
            with opener.open(request, timeout=25) as response:
                status, content_type = response.status, response.headers.get("Content-Type", "")
                result = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as response:
            status, content_type = response.code, response.headers.get("Content-Type", "")
            result = response.read(MAX_RESPONSE_BYTES + 1)
        except (URLError, TimeoutError, OSError) as exc:
            log.warning("Main bot API unavailable for %s %s: %s", method, self.path, type(exc).__name__)
            self.respond_json(502, error="upstream_unavailable")
            return

        if len(result) > MAX_RESPONSE_BYTES:
            self.respond_json(502, error="upstream_response_too_large")
        elif not content_type.lower().startswith("application/json"):
            log.warning("Main bot returned non-JSON: HTTP %s for %s %s", status, method, self.path)
            self.respond_json(502, error="upstream_not_api")
        else:
            self.respond(status, result, "application/json; charset=utf-8")


if __name__ == "__main__":
    parsed = urlsplit(UPSTREAM)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise SystemExit("Set TELEGASTARS_UPSTREAM_URL to the main bot's public HTTPS origin (no /api/v1)")
    log.info("Starting API gateway on port %s", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
