"""Hosted grouped release browsing and role-scoped API regression tests."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from goreecloud_changelogs.hosted_auth import AuthStore
from goreecloud_changelogs.hosted_server import make_hosted_handler
from goreecloud_changelogs.store import Store

ORIGIN = "https://changelog.test.invalid"
PASSWORD = "test-password-0123456789"


class HostedReleaseBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "service"
        root.mkdir(mode=0o700)
        store = Store(root / "changelogs.sqlite3")
        store.add("mesh", "1.0", "added", "First", released_at="2026-01-01")
        store.add("mesh", "1.0", "security", "Guard", released_at="2026-01-02")
        store.add("mesh", "2.0", "fixed", "Patch", released_at="2026-02-01")
        self.accounts = AuthStore(root / "accounts.sqlite3", initialize=True)
        self.accounts.bootstrap("admin", PASSWORD)
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_hosted_handler(store, self.accounts, ORIGIN, allow_test_loopback_host=True)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        headers = {"Authorization": "Bearer " + token} if token else {}
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_authenticated_releases_and_product_version_drilldown(self):
        principal = self.accounts.authenticate("admin", PASSWORD)
        token = self.accounts.issue(principal["id"], "token")[0]
        self.assertEqual(self.request("/v1/releases")[0], 401)
        code, data = self.request("/v1/releases?limit=1", token)
        self.assertEqual(code, 200)
        self.assertTrue(data["has_more"])
        self.assertEqual(data["releases"][0]["version"], "2.0")
        code, data = self.request("/v1/releases?product=mesh&offset=1", token)
        self.assertEqual(code, 200)
        self.assertEqual(data["releases"][0]["entries"], 2)
        self.assertEqual(data["releases"][0]["by_kind"], {"added": 1, "security": 1})
        code, data = self.request("/v1/entries?product=mesh&version=1.0", token)
        self.assertEqual(code, 200)
        self.assertEqual(len(data["entries"]), 2)
        self.assertEqual(self.request("/v1/releases?kind=added", token)[0], 400)

    def test_browser_binds_safe_api_and_toggles_without_html_injection(self):
        root = files("goreecloud_changelogs").joinpath("hosted_web")
        html = root.joinpath("index.html").read_text(encoding="utf-8")
        js = root.joinpath("app.js").read_text(encoding="utf-8")
        for value in ('id="view-releases"', 'id="view-entries"',
                      'id="clear-version"', 'aria-pressed="false"'):
            self.assertIn(value, html)
        self.assertIn('path = "/v1/releases?"', js)
        self.assertIn('params.set("version", versionFilter)', js)
        self.assertIn('fragment.append(renderRelease(entry))', js)
        self.assertIn('node("span", "release-kind"', js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("localStorage", js)


if __name__ == "__main__":
    unittest.main()
