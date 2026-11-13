"""Loopback-only, read-only HTTP API for local changelog consumers.

No CORS headers, no remote binding, no write endpoints, and no implicit trust
of browser requests. Use a randomly generated bearer token for every request.
"""
import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .store import Store

MAX_LIMIT = 1000

def make_handler(store, token):
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("API token must contain at least 32 characters")

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                self._reply(401, {"error": "Unauthorized"})
                return
            url = urlsplit(self.path)
            if url.path == "/health":
                self._reply(200, {"status": "ok"})
                return
            if url.path not in ("/v1/entries", "/v1/search"):
                self._reply(404, {"error": "Not found"})
                return
            try:
                params = parse_qs(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
                if set(params) - {"product", "version", "limit", "q"} or any(len(v) != 1 for v in params.values()):
                    raise ValueError("Invalid query parameters")
                limit = int(params.get("limit", ["100"])[0])
                if not 1 <= limit <= MAX_LIMIT:
                    raise ValueError("Invalid limit")
                if url.path == "/v1/search":
                    if "version" in params or "q" not in params:
                        raise ValueError("Search requires q and does not accept version")
                    rows = store.search(params["q"][0], product=params.get("product", [None])[0], limit=limit)
                else:
                    if "q" in params:
                        raise ValueError("q is only supported by search")
                    rows = store.list(product=params.get("product", [None])[0],
                                      version=params.get("version", [None])[0], limit=limit)
            except (ValueError, OverflowError):
                self._reply(400, {"error": "Invalid query"})
                return
            self._reply(200, {"entries": rows})

        def do_POST(self):
            self._reply(405, {"error": "Read-only API"})

        def do_PUT(self):
            self._reply(405, {"error": "Read-only API"})

        def do_DELETE(self):
            self._reply(405, {"error": "Read-only API"})

        def log_message(self, fmt, *args):
            # Do not log URLs, tokens, or entry contents.
            pass

    return Handler

def serve(db=None, port=8765, token=None):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    token = token or os.environ.get("GOREE_CHANGELOGS_API_TOKEN")
    if not token:
        raise ValueError("Set GOREE_CHANGELOGS_API_TOKEN (32+ characters)")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Store(db), token))
    server.daemon_threads = True
    try:
        print("Changelogs read-only API listening on http://127.0.0.1:%d" % server.server_port, flush=True)
        server.serve_forever()
    finally:
        server.server_close()

def generate_token():
    return secrets.token_urlsafe(48)
