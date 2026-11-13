"""Loopback-only authenticated, read-only API and optional same-origin web viewer."""
import hmac
import json
import os
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from .store import Store
from .releases import list_releases

MAX_LIMIT = 1000
WEB_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/ui/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/ui/app.css": ("app.css", "text/css; charset=utf-8"),
}
CSP = ("default-src 'none'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'; connect-src 'self'; script-src 'self'; "
       "style-src 'self'; img-src 'self'")


def make_handler(store, token, web=False):
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("API token must contain at least 32 characters")
    # Static files contain no user records or credentials. They are bundled with the wheel.
    assets = {}
    if web:
        root = files("goreecloud_changelogs").joinpath("web")
        assets = {route: (root.joinpath(name).read_bytes(), mime)
                  for route, (name, mime) in WEB_FILES.items()}

    class Handler(BaseHTTPRequestHandler):
        def _headers(self, mime, length):
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)

        def _reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path in assets and not url.query and not url.fragment:
                body, mime = assets[url.path]
                self.send_response(200)
                self._headers(mime, len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                self._reply(401, {"error": "Unauthorized"})
                return
            if url.path == "/health":
                if url.query:
                    self._reply(400, {"error": "Invalid query"})
                else:
                    self._reply(200, {"status": "ok"})
                return
            if url.path.startswith("/v1/entries/"):
                match = re.fullmatch(r"/v1/entries/([1-9][0-9]{0,17})", url.path)
                if not match or url.query:
                    self._reply(400, {"error": "Invalid entry ID"})
                    return
                entry = store.get(int(match.group(1)))
                self._reply(200, {"entry": entry}) if entry else self._reply(404, {"error": "Not found"})
                return
            if url.path not in ("/v1/entries", "/v1/search", "/v1/summary", "/v1/releases"):
                self._reply(404, {"error": "Not found"})
                return
            try:
                params = parse_qs(url.query, keep_blank_values=True,
                                  strict_parsing=True, max_num_fields=5)
                if set(params) - {"product", "version", "limit", "offset", "q"} or any(len(v) != 1 for v in params.values()):
                    raise ValueError("Invalid query parameters")
                if url.path == "/v1/summary":
                    if set(params) - {"product"}:
                        raise ValueError("Summary accepts only product")
                    self._reply(200, store.summary(product=params.get("product", [None])[0]))
                    return
                if url.path == "/v1/releases":
                    if set(params) - {"product", "limit", "offset"}:
                        raise ValueError("Releases accepts only product, limit and offset")
                    limit = int(params.get("limit", ["100"])[0])
                    offset = int(params.get("offset", ["0"])[0])
                    releases = list_releases(store,
                                             product=params.get("product", [None])[0],
                                             limit=limit, offset=offset)
                    self._reply(200, {"releases": releases, "limit": limit,
                                      "offset": offset, "has_more": len(releases) == limit})
                    return
                limit = int(params.get("limit", ["100"])[0])
                offset = int(params.get("offset", ["0"])[0])
                if not 1 <= limit <= MAX_LIMIT or not 0 <= offset <= 1000000:
                    raise ValueError("Invalid pagination")
                if url.path == "/v1/search":
                    if "version" in params or "q" not in params:
                        raise ValueError("Search requires q and does not accept version")
                    rows = store.search(params["q"][0],
                                        product=params.get("product", [None])[0],
                                        limit=limit, offset=offset)
                else:
                    if "q" in params:
                        raise ValueError("q is only supported by search")
                    rows = store.list(product=params.get("product", [None])[0],
                                      version=params.get("version", [None])[0],
                                      limit=limit, offset=offset)
            except (ValueError, OverflowError):
                self._reply(400, {"error": "Invalid query"})
                return
            self._reply(200, {"entries": rows, "limit": limit, "offset": offset,
                              "has_more": len(rows) == limit})

        def do_POST(self):
            self._reply(405, {"error": "Read-only API"})

        def do_PUT(self):
            self._reply(405, {"error": "Read-only API"})

        def do_PATCH(self):
            self._reply(405, {"error": "Read-only API"})

        def do_DELETE(self):
            self._reply(405, {"error": "Read-only API"})

        def log_message(self, fmt, *args):
            # Request URLs can include private product names; never print them.
            pass

    return Handler


def serve(db=None, port=8765, token=None, web=False):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    token = token or os.environ.get("GOREE_CHANGELOGS_API_TOKEN")
    if not token:
        raise ValueError("Set GOREE_CHANGELOGS_API_TOKEN (32+ characters)")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Store(db), token, web=web))
    server.daemon_threads = True
    try:
        print("Changelogs read-only listener on http://127.0.0.1:%d%s" %
              (server.server_port, " (web viewer enabled)" if web else ""), flush=True)
        server.serve_forever()
    finally:
        server.server_close()


def generate_token():
    return secrets.token_urlsafe(48)
