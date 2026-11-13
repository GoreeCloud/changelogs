"""Self-hosted account, web-login, CLI writes and Android API integration tests.

All HTTP is disposable loopback, never public or a production credential.
"""
import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from goreecloud_changelogs.cli import parser, main
from goreecloud_changelogs.hosted_auth import AuthFailed, AuthStore
from goreecloud_changelogs.hosted_server import make_hosted_handler, validate_origin
from goreecloud_changelogs.hosted_client import execute, request
from goreecloud_changelogs.store import Store

ORIGIN = "https://changelogs.example.test"
PASSWORD = "correct-very-long-passphrase-2048"


class SelfHostedServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "server"
        self.root.mkdir(mode=0o700)
        self.entries = Store(self.root / "changelogs.sqlite3")
        self.accounts = AuthStore(self.root / "accounts.sqlite3", initialize=True)
        self.accounts.bootstrap("Admin", PASSWORD)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_hosted_handler(self.entries, self.accounts, ORIGIN, allow_test_loopback_host=True)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
        try:
            conn.request(method, path, body=body, headers=request_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def login(self, browser=False, username="admin", password=PASSWORD):
        path = "/v1/auth/session" if browser else "/v1/auth/token"
        headers = {"Origin": ORIGIN} if browser else {}
        code, response_headers, body = self.call(
            "POST", path, {"username": username, "password": password}, headers)
        return code, response_headers, json.loads(body)

    def test_central_cli_write_is_immediately_visible_to_web_and_api(self):
        code, _, login = self.login()
        self.assertEqual(code, 200)
        token = login["token"]
        self.assertGreaterEqual(len(token), 32)

        def synthetic_tls(request):
            # Stub HTTPS transport only. The real client uses certificate-verified
            # HTTPS and refuses redirects; the backend here is disposable loopback.
            from urllib.parse import urlsplit
            url = urlsplit(request.full_url)
            status, headers, data = self.call(
                request.get_method(), url.path + ("?" + url.query if url.query else ""),
                request.data, dict(request.header_items()))
            return status, data

        args = parser().parse_args([
            "--server", ORIGIN, "add", "mesh", "1.2", "added", "Created via remote CLI",
            "--description", "One authoritative workspace"
        ])
        new_id = execute(args, token=token, transport=synthetic_tls)
        self.assertEqual(new_id, 1)
        code, headers, result = self.call(
            "GET", "/v1/entries?product=mesh",
            headers={"Authorization": "Bearer " + token})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(result)["entries"][0]["title"], "Created via remote CLI")
        self.assertEqual(self.entries.get(1)["product"], "mesh")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        args = parser().parse_args(["--server", ORIGIN, "list", "--product", "mesh"])
        self.assertEqual(execute(args, token=token, transport=synthetic_tls)[0]["id"], 1)

    def test_real_browser_cookie_signin_and_logout(self):
        code, headers, login = self.login(browser=True)
        self.assertEqual(code, 200)
        self.assertEqual(login["username"], "admin")
        cookie = headers["Set-Cookie"]
        for attribute in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(attribute, cookie)
        cookie = cookie.split(";", 1)[0]
        code, _, me_raw = self.call("GET", "/v1/me", headers={"Cookie": cookie})
        self.assertEqual(code, 200)
        csrf = json.loads(me_raw)["csrf"]
        self.assertEqual(csrf, login["csrf"])
        code, _, _ = self.call("POST", "/v1/entries",
                               {"product":"mesh","version":"1","kind":"fixed","title":"X"},
                               {"Cookie": cookie, "Origin": ORIGIN})
        self.assertEqual(code, 403)
        code, _, _ = self.call(
            "POST", "/v1/entries",
            {"product":"mesh","version":"1","kind":"fixed","title":"Browser change"},
            {"Cookie": cookie, "Origin": ORIGIN, "X-GoreeCloud-CSRF": csrf})
        self.assertEqual(code, 201)
        code, _, _ = self.call("POST", "/v1/auth/logout", {},
                              {"Cookie": cookie, "Origin": ORIGIN,
                               "X-GoreeCloud-CSRF": csrf})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/v1/me", headers={"Cookie": cookie})[0], 401)
        self.assertEqual(self.entries.list()[0]["title"], "Browser change")

    def test_unauthenticated_requests_and_wrong_origin_fail(self):
        for path in ("/v1/me", "/v1/entries", "/v1/releases", "/v1/summary"):
            self.assertEqual(self.call("GET",path)[0],401)
        code, _, _ = self.call(
            "POST", "/v1/auth/session", {"username":"admin","password":PASSWORD},
            {"Origin":"https://evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(self.call("POST", "/v1/auth/token",
                                  {"username":"admin","password":"not-right"})[0], 401)

    def test_token_login_and_writes_can_be_revoked(self):
        token = self.login()[2]["token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.call("GET","/v1/me",headers=headers)[0],200)
        code, _, _ = self.call("POST","/v1/auth/logout",{},headers)
        self.assertEqual(code,200)
        self.assertEqual(self.call("GET","/v1/me",headers=headers)[0],401)

    def test_input_bounds_and_web_asset_safety(self):
        code, _, html = self.call("GET", "/")
        self.assertEqual(code,200)
        self.assertIn(b"Sign in to Changelogs", html)
        for path in ("/app.js","/app.css"):
            self.assertEqual(self.call("GET", path)[0],200)
        code, _, script = self.call("GET","/app.js")
        self.assertNotIn(b"localStorage",script)
        self.assertNotIn(b"innerHTML",script)
        self.assertIn(b'credentials: "same-origin"',script)
        self.assertEqual(self.call("GET","/does-not-exist")[0],404)
        token = self.login()[2]["token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.call("GET","/v1/entries?kind=UNSUPPORTED",
                                   headers=headers)[0],400)
        self.assertEqual(self.call("POST","/v1/entries",
                                   {"product":"mesh","version":"1",
                                    "kind":"not-valid","title":"Unsafe"},
                                   headers)[0],400)

    def test_untrusted_host_rejected_before_login_or_assets(self):
        strict = ThreadingHTTPServer(("127.0.0.1", 0),
                      make_hosted_handler(self.entries, self.accounts, ORIGIN))
        thread = threading.Thread(target=strict.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", strict.server_port, timeout=3)
            conn.request("GET", "/")
            response = conn.getresponse()
            self.assertEqual(response.status, 421)
            response.read()
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", strict.server_port, timeout=3)
            conn.request("GET", "/", headers={"Host": "changelogs.example.test"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()
        finally:
            strict.shutdown()
            strict.server_close()
            thread.join(timeout=5)

    def test_non_https_public_origin_refused(self):
        for url in ("http://0.0.0.0","http://localhost:8876",
                    "https://user:pass@host.example",
                    "https://host.example/a","https://host.example/?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_origin(url)

    def test_reader_can_view_but_never_mutate_shared_history(self):
        self.accounts.add_user("viewer", "reader-password-long-enough-2026")
        code, _, result = self.login(username="viewer",
                                     password="reader-password-long-enough-2026")
        self.assertEqual(code, 200)
        self.assertEqual(result["role"], "reader")
        headers = {"Authorization": "Bearer " + result["token"]}
        self.assertEqual(self.call("GET", "/v1/entries", headers=headers)[0], 200)
        self.assertEqual(
            self.call("POST", "/v1/entries",
                      {"product":"mesh","version":"1","kind":"added","title":"Unauthorized"},
                      headers)[0], 403)
        self.assertEqual(
            self.call("PATCH", "/v1/entries/1", {"title":"Unauthorized"}, headers)[0], 403)
        self.assertEqual(
            self.call("DELETE", "/v1/entries/1", headers=headers)[0], 403)
        self.assertEqual(self.entries.list(), [])

    @unittest.skipUnless(os.name == "posix", "POSIX permission inspection")
    def test_serving_refuses_exposed_database_permissions(self):
        from goreecloud_changelogs.hosted_server import serve_hosted
        os.chmod(self.entries.path, 0o644)
        with self.assertRaisesRegex(ValueError, "permissions"):
            serve_hosted(self.root, ORIGIN, 8876)
        self.assertEqual(self.entries.path.stat().st_mode & 0o777, 0o644)

    def test_password_lockout_persists_across_restart(self):
        for _ in range(5):
            with self.assertRaises(AuthFailed):
                self.accounts.authenticate("admin", "a-very-long-wrong-password")
        reopened = AuthStore(self.root / "accounts.sqlite3")
        with self.assertRaises(AuthFailed):
            reopened.authenticate("admin", PASSWORD)

    def test_local_host_init_requires_interactive_password_and_no_external_port(self):
        other = Path(self.temp.name) / "second-server"
        out, error = io.StringIO(), io.StringIO()
        with patch("getpass.getpass", side_effect=[PASSWORD, PASSWORD]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
                result = main(["host","init","--data-dir",str(other)])
        self.assertEqual((result,error.getvalue()),(0,""))
        self.assertTrue((other/"accounts.sqlite3").exists())
        self.assertTrue((other/"changelogs.sqlite3").exists())
        with patch("getpass.getpass", side_effect=[PASSWORD, PASSWORD]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
                result = main(["host","init","--data-dir",str(other)])
        self.assertEqual(result,1)


if __name__ == "__main__":
    unittest.main()
