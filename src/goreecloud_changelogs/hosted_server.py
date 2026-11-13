"""Self-hosted GoreeCloud Changelogs HTTP backend.

An administrator bootstraps accounts locally. Server storage is authoritative:
all remote CLI and app requests operate on the same SQLite entry database.
Loopback listener only; approved HTTPS reverse proxy required for devices.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from email.utils import formatdate
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .api import BoundedHTTPServer, MAX_REQUEST_TARGET
from .hosted_auth import AuthFailed, AuthStore, COOKIE, SESSION_TTL, _password_bytes
from .importer import _normalize, _fingerprint, _reject_constant, _unique_pairs, import_records
from .pagination import entries_page
from .releases import page_releases
from .store import Store, audit_permissions

MAX_BODY = 65536
IDENTIFIER = re.compile(r"/v1/entries/([1-9][0-9]{0,17})\Z")
RESPONSE_CSP = (
    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "script-src 'self'; style-src 'self'; connect-src 'self'; "
    "form-action 'self'; img-src 'self'"
)
WEB_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}


def validate_origin(origin):
    from urllib.parse import urlsplit
    if not isinstance(origin, str) or len(origin) > 1024 or any(
        ord(ch) < 33 for ch in origin
    ):
        raise ValueError("Public origin must be an exact HTTPS origin")
    url = urlsplit(origin)
    try:
        ok = (url.scheme == "https" and bool(url.hostname)
              and url.username is None and url.password is None
              and url.path in ("", "/") and not url.query and not url.fragment
              and url.port != 0)
    except ValueError as exc:
        raise ValueError("Invalid public HTTPS origin") from exc
    if not ok:
        raise ValueError("Public origin must be an exact HTTPS origin")
    return origin.rstrip("/")


def data_paths(directory):
    root = Path(directory).expanduser()
    if root.is_symlink():
        raise ValueError("Server data directory cannot be a symbolic link")
    return root / "changelogs.sqlite3", root / "accounts.sqlite3"


def make_hosted_handler(store, accounts, public_origin, *, allow_test_loopback_host=False):
    """Require exact expected Host in production; test loopback is opt-in only."""
    origin = validate_origin(public_origin)
    trusted_host = urlsplit(origin).netloc.lower()
    assets = {}
    root = files("goreecloud_changelogs").joinpath("hosted_web")
    for path, (filename, mime) in WEB_ASSETS.items():
        assets[path] = (root.joinpath(filename).read_bytes(), mime)

    class HostedHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def parse_request(self):
            if not super().parse_request():
                return False
            hosts = self.headers.get_all("Host", [])
            allowed = (len(hosts) == 1 and len(hosts[0]) <= 255
                       and hosts[0].lower() == trusted_host)
            if not allowed and allow_test_loopback_host and len(hosts) == 1:
                allowed = hosts[0].lower() == f"127.0.0.1:{self.server.server_port}"
            if not allowed:
                self._reply(421, {"error": "Unrecognized request host"})
                return False
            return True

        def _headers(self, mime, length, cookie=None):
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", RESPONSE_CSP)
            self.send_header("Vary", "Cookie, Authorization")
            self.send_header("Connection", "close")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)

        def _reply(self, status, payload, cookie=None):
            content = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode()
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(content), cookie)
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            self.close_connection = True

        def _send_asset(self, asset):
            content, mime = asset
            self.send_response(200)
            self._headers(mime, len(content))
            self.end_headers()
            self.wfile.write(content)
            self.close_connection = True

        def _path(self):
            if len(self.path) > MAX_REQUEST_TARGET:
                self._reply(414, {"error": "Request target too long"})
                return None
            url = urlsplit(self.path)
            if url.fragment:
                self._reply(400, {"error": "Invalid request target"})
                return None
            return url

        def _same_origin(self):
            supplied = self.headers.get_all("Origin", [])
            return len(supplied) == 1 and supplied[0] == origin

        def _credentials(self):
            headers = self.headers.get_all("Authorization", [])
            cookies = self.headers.get_all("Cookie", [])
            if len(headers) > 1 or len(cookies) > 1 or (headers and cookies):
                return None, None, None
            if headers:
                value = headers[0]
                if len(value) > 256 or not value.startswith("Bearer "):
                    return None, None, None
                token = value[7:]
                return accounts.resolve(token, "token"), token, "token"
            if cookies:
                if len(cookies[0]) > 4096:
                    return None, None, None
                jar = SimpleCookie()
                try:
                    jar.load(cookies[0])
                except Exception:
                    return None, None, None
                if COOKIE not in jar:
                    return None, None, None
                token = jar[COOKIE].value
                return accounts.resolve(token, "web"), token, "web"
            return None, None, None

        def _require(self, write=False):
            account, token, kind = self._credentials()
            if account is None:
                self._reply(401, {"error": "Authentication required"})
                return None
            if write and account["role"] != "admin":
                self._reply(403, {"error": "Insufficient permissions"})
                return None
            if write and kind == "web":
                if not self._same_origin() or not accounts.csrf_valid(
                    account, self.headers.get("X-GoreeCloud-CSRF")
                ):
                    self._reply(403, {"error": "Request verification failed"})
                    return None
            return account, token, kind

        def _json_input(self):
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding") is not None:
                raise ValueError("Invalid request framing")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise ValueError("JSON content type required")
            if not lengths[0].isdigit() or not 1 <= int(lengths[0]) <= MAX_BODY:
                raise ValueError("Invalid JSON request length")
            length = int(lengths[0])
            content = self.rfile.read(length)
            if len(content) != length:
                raise ValueError("Incomplete request")
            return json.loads(content.decode("utf-8"),
                              object_pairs_hook=_unique_pairs,
                              parse_constant=_reject_constant)

        def _login(self, browser):
            # Browser logins require an exact Origin; mobile/CLI token logins
            # have no Origin and never receive an ambient cookie.
            origins = self.headers.get_all("Origin", [])
            if browser and not self._same_origin():
                self._reply(403, {"error": "Request verification failed"})
                return
            if not browser and origins and not self._same_origin():
                self._reply(403, {"error": "Request verification failed"})
                return
            try:
                body = self._json_input()
                if not isinstance(body, dict) or set(body) != {"username", "password"}:
                    raise ValueError("Invalid login request")
                principal = accounts.authenticate(body["username"], body["password"])
            except (AuthFailed, ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                self._reply(401, {"error": "Invalid credentials"})
                return
            token, csrf, ttl = accounts.issue(principal["id"], "web" if browser else "token")
            if browser:
                cookie = (f"{COOKIE}={token}; Path=/; Secure; HttpOnly; "
                          f"SameSite=Strict; Max-Age={ttl}")
                self._reply(200, {"username": principal["username"],
                                  "role": principal["role"], "csrf": csrf}, cookie)
            else:
                self._reply(200, {"token": token, "expires_in": ttl,
                                  "username": principal["username"],
                                  "role": principal["role"]})

        def do_GET(self):
            url = self._path()
            if url is None:
                return
            if url.path in assets and not url.query:
                self._send_asset(assets[url.path])
                return
            if url.path not in ("/v1/me", "/v1/entries", "/v1/search",
                                "/v1/releases", "/v1/summary") and not IDENTIFIER.fullmatch(url.path):
                self._reply(404, {"error": "Not found"})
                return
            auth = self._require()
            if auth is None:
                return
            account, token, kind = auth
            if url.path == "/v1/me":
                if url.query:
                    self._reply(400, {"error": "Unexpected query"})
                    return
                # CSRF is derived from the opaque HttpOnly session token;
                # it is visible only through authenticated same-origin JSON.
                csrf = accounts.csrf_for(token) if kind == "web" else None
                self._reply(200, {"username": account["username"],
                                  "role": account["role"], "csrf": csrf})
                return
            if IDENTIFIER.fullmatch(url.path):
                if url.query:
                    self._reply(400, {"error": "Unexpected query"})
                    return
                row = store.get(int(IDENTIFIER.fullmatch(url.path).group(1)))
                self._reply(200, {"entry": row}) if row else self._reply(
                    404, {"error": "Not found"})
                return
            try:
                params = parse_qs(url.query, strict_parsing=True,
                                  keep_blank_values=True, max_num_fields=6) if url.query else {}
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError("Duplicate query")
                if url.path == "/v1/summary":
                    if set(params) - {"product"}:
                        raise ValueError("Invalid summary query")
                    self._reply(200, store.summary(params.get("product", [None])[0]))
                    return
                limit = int(params.get("limit", ["100"])[0])
                offset = int(params.get("offset", ["0"])[0])
                product = params.get("product", [None])[0]
                if url.path == "/v1/releases":
                    if set(params) - {"product", "limit", "offset"}:
                        raise ValueError("Invalid releases query")
                    releases, more = page_releases(store, product, limit, offset)
                    self._reply(200, {"releases": releases, "limit": limit,
                                      "offset": offset, "has_more": more})
                    return
                if set(params) - {"product", "version", "kind", "q", "limit", "offset"}:
                    raise ValueError("Invalid entries query")
                if url.path == "/v1/search":
                    if "q" not in params or "version" in params:
                        raise ValueError("Invalid search query")
                elif "q" in params:
                    raise ValueError("Search query requires /v1/search")
                rows, more = entries_page(
                    store, product=product, version=params.get("version", [None])[0],
                    kind=params.get("kind", [None])[0],
                    query=params.get("q", [None])[0], limit=limit, offset=offset)
                self._reply(200, {"entries": rows, "limit": limit,
                                  "offset": offset, "has_more": more})
            except (ValueError, OverflowError):
                self._reply(400, {"error": "Invalid query"})

        def do_POST(self):
            url = self._path()
            if url is None:
                return
            if url.query:
                self._reply(400, {"error": "Unexpected query"})
                return
            if url.path == "/v1/auth/session":
                self._login(browser=True)
                return
            if url.path == "/v1/auth/token":
                self._login(browser=False)
                return
            if url.path == "/v1/auth/logout":
                auth = self._require(write=False)
                if auth is None:
                    return
                account, token, kind = auth
                if kind == "web" and (not self._same_origin() or
                                      not accounts.csrf_valid(account, self.headers.get("X-GoreeCloud-CSRF"))):
                    self._reply(403, {"error": "Request verification failed"})
                    return
                accounts.revoke(token)
                cookie = (f"{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; "
                          "Max-Age=0") if kind == "web" else None
                self._reply(200, {"logged_out": True}, cookie)
                return
            if url.path == "/v1/import":
                if self._require(write=True) is None:
                    return
                try:
                    document = self._json_input()
                    if not isinstance(document, dict) or set(document) != {"entries"}:
                        raise ValueError("Invalid import structure")
                    rows = document["entries"]
                    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
                        raise ValueError("Import batch must contain 1-100 entries")
                    normalized = [_normalize(row) for row in rows]
                    if len({_fingerprint(row) for row in normalized}) != len(normalized):
                        raise ValueError("Duplicate source rows")
                except (ValueError, TypeError, UnicodeError, OverflowError,
                        json.JSONDecodeError):
                    self._reply(400, {"error": "Invalid import batch"})
                    return
                try:
                    result = import_records(store, normalized)
                except Exception:
                    self._reply(500, {"error": "Import operation failed"})
                    return
                self._reply(200, result)
                return
            if url.path != "/v1/entries":
                self._reply(404, {"error": "Not found"})
                return
            if self._require(write=True) is None:
                return
            try:
                body = self._json_input()
                if not isinstance(body, dict) or (
                    set(body) - {"product", "version", "kind", "title", "description",
                                 "author", "released_at", "metadata"}
                ):
                    raise ValueError("Invalid fields")
                body.setdefault("released_at", datetime.date.today().isoformat())
                row = _normalize(body)
                entry_id = store.add(row["product"], row["version"], row["kind"],
                                     row["title"], row["description"], row["author"],
                                     row["released_at"], json.loads(row["metadata"]))
                self._reply(201, {"entry": store.get(entry_id)})
            except (ValueError, TypeError, UnicodeError, OverflowError,
                    json.JSONDecodeError):
                self._reply(400, {"error": "Invalid entry"})

        def do_PATCH(self):
            url = self._path()
            if url is None:
                return
            match = IDENTIFIER.fullmatch(url.path)
            if match is None or url.query:
                self._reply(404, {"error": "Not found"})
                return
            if self._require(write=True) is None:
                return
            entry_id = int(match.group(1))
            existing = store.get(entry_id)
            if not existing:
                self._reply(404, {"error": "Not found"})
                return
            try:
                updates = self._json_input()
                fields = {"product", "version", "kind", "title", "description",
                          "author", "released_at", "metadata"}
                if not isinstance(updates, dict) or not updates or set(updates) - fields:
                    raise ValueError("Invalid patch")
                row = _normalize({**existing, **updates})
                changes = {key: (json.loads(row[key]) if key == "metadata" else row[key])
                           for key in updates}
                store.update(entry_id, **changes)
                self._reply(200, {"entry": store.get(entry_id)})
            except (ValueError, TypeError, UnicodeError, OverflowError,
                    json.JSONDecodeError):
                self._reply(400, {"error": "Invalid patch"})

        def do_DELETE(self):
            url = self._path()
            if url is None:
                return
            match = IDENTIFIER.fullmatch(url.path)
            if match is None or url.query:
                self._reply(404, {"error": "Not found"})
                return
            if self._require(write=True) is None:
                return
            self._reply(200, {"deleted": True}) if store.delete(
                int(match.group(1))) else self._reply(404, {"error": "Not found"})

        def do_PUT(self):
            self._reply(405, {"error": "Method not allowed"})

        def do_OPTIONS(self):
            self._reply(405, {"error": "Method not allowed"})

        def log_message(self, *_args):
            # Never log credentials, cookies, personally identifiable entry data.
            pass

    return HostedHandler


def serve_hosted(directory, public_origin, port=8876):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid server port")
    validate_origin(public_origin)
    db_path, auth_path = data_paths(directory)
    if not db_path.is_file() or db_path.is_symlink():
        raise ValueError("Initialize the server before serving")
    if not audit_permissions(db_path)["secure"]:
        raise ValueError("Changelog storage permissions must be owner-only")
    accounts = AuthStore(auth_path)
    store = Store(db_path)
    server = BoundedHTTPServer(
        ("127.0.0.1", port), make_hosted_handler(store, accounts, public_origin))
    try:
        print(f"Changelogs self-hosted service on 127.0.0.1:{server.server_port}",
              flush=True)
        server.serve_forever()
    finally:
        server.server_close()
