"""HTTPS-only direct CLI access to the self-hosted Changelogs workspace.

No local SQLite writes, redirects, proxy-environment inheritance, TLS bypass,
or credential persistence. CLI access token is supplied by the environment.
"""
from __future__ import annotations

import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (HTTPSHandler, HTTPRedirectHandler, ProxyHandler,
                            Request, build_opener)

from .metadata import parse_metadata
from .store import KINDS

MAX_RESPONSE = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def origin(value):
    if not isinstance(value, str) or len(value) > 1024 or any(
        ord(ch) < 33 for ch in value
    ):
        raise ValueError("Configure an exact trusted HTTPS server origin")
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and bool(url.hostname)
                 and url.username is None and url.password is None
                 and url.path in ("", "/") and not url.query and not url.fragment
                 and url.port != 0)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Configure an exact trusted HTTPS server origin")
    return value.rstrip("/")


def request(server, path, *, token=None, method="GET", body=None, transport=None):
    server = origin(server)
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("Invalid server API path")
    if method not in ("GET", "POST", "PATCH", "DELETE"):
        raise ValueError("Unsupported server method")
    if token is not None and (not isinstance(token, str) or not 32 <= len(token) <= 256
                               or not token.isascii()):
        raise ValueError("Invalid access token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body, ensure_ascii=True, allow_nan=False).encode("utf-8")
        if len(body) > 65536:
            raise ValueError("Request exceeds server input limit")
    req = Request(server + path, method=method, data=body, headers=headers)
    try:
        if transport is not None:
            status, response = transport(req)
        else:
            opener = build_opener(
                ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()),
                NoRedirect())
            with opener.open(req, timeout=12) as stream:
                status, response = stream.status, stream.read(MAX_RESPONSE + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("Authentication failed or insufficient permissions") from None
        if exc.code == 404:
            raise ValueError("Server endpoint or entry not found") from None
        raise ValueError(f"Server rejected operation (HTTP {exc.code})") from None
    except (URLError, OSError):
        raise ValueError("Unable to reach trusted HTTPS Changelogs server") from None
    if not 200 <= status < 300 or len(response) > MAX_RESPONSE:
        raise ValueError("Unexpected server response")
    try:
        value = json.loads(response.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Server returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Server returned unexpected data")
    return value


def login(server, username, password, transport=None):
    response = request(server, "/v1/auth/token", method="POST",
                       body={"username": username, "password": password},
                       transport=transport)
    token = response.get("token")
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise ValueError("Server returned invalid access token")
    return token


def execute(args, token=None, transport=None):
    """Map familiar local CLI operations to central server API requests."""
    server = origin(args.server)
    if token is None:
        token = os.environ.get("GOREE_CHANGELOGS_REMOTE_TOKEN")
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise ValueError("Set GOREE_CHANGELOGS_REMOTE_TOKEN using a login token")
    command = args.command
    if command in ("list", "search", "releases", "summary"):
        params = {}
        for field in ("product", "version", "kind", "limit", "offset"):
            value = getattr(args, field, None)
            if value is not None:
                params[field] = value
        if command == "search":
            params["q"] = args.query
        if command == "releases":
            params.pop("version", None)
            params.pop("kind", None)
        if command == "summary":
            params = {"product": args.product} if args.product is not None else {}
        path = {
            "list": "/v1/entries", "search": "/v1/search",
            "releases": "/v1/releases", "summary": "/v1/summary"
        }[command]
        data = request(server, path + ("?" + urlencode(params) if params else ""),
                       token=token, transport=transport)
        if command == "list" or command == "search":
            return data["entries"]
        if command == "releases":
            return data["releases"]
        return data
    if command == "show":
        data = request(server, f"/v1/entries/{args.id}",
                       token=token, transport=transport)
        return data["entry"]
    if command == "add":
        body = {"product": args.product, "version": args.version,
                "kind": args.kind, "title": args.title,
                "description": args.description, "author": args.author,
                "metadata": parse_metadata(args.metadata)}
        if args.date is not None:
            body["released_at"] = args.date
        data = request(server, "/v1/entries", token=token, method="POST",
                       body=body, transport=transport)
        return data["entry"]["id"]
    if command == "edit":
        body = {field: getattr(args, field) for field in (
            "product", "version", "kind", "title", "description", "author")
            if getattr(args, field, None) is not None}
        if args.date is not None:
            body["released_at"] = args.date
        if args.metadata is not None:
            body["metadata"] = parse_metadata(args.metadata)
        if not body:
            raise ValueError("No valid update fields")
        request(server, f"/v1/entries/{args.id}", token=token, method="PATCH",
                body=body, transport=transport)
        return "Updated"
    if command == "delete":
        request(server, f"/v1/entries/{args.id}", token=token, method="DELETE",
                transport=transport)
        return "Deleted"
    raise ValueError("This CLI command operates on local storage, not the remote server")
