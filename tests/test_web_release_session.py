"""Bundled viewer release navigation and session-privacy source contract smoke checks.

These are packaged asset/API checks, not headless browser acceptance tests.
"""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.store import Store

TOKEN = "web-session-test-" + "a" * 44


class WebReleaseSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "viewer.sqlite3")
        self.store.add("mesh", "1", "added", "<script>text</script>", released_at="2026-01-01")
        self.store.add("mesh", "2", "fixed", "Fix", released_at="2026-02-01")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          make_handler(self.store, TOKEN, web=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def get(self, path, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            headers = {"Authorization": "Bearer " + token} if token else {}
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            connection.close()

    def test_release_viewer_controls_and_safe_asset_delivery(self):
        code, page = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn('id="view-releases"', page)
        self.assertIn('id="view-entries"', page)
        self.assertIn('data-gc-theme="dark"', page)
        _, script = self.get("/ui/app.js")
        for fragment in ("new AbortController()", "sessionEpoch", "requestSequence",
                         '"/v1/releases?"', 'element("button"', "textContent",
                         "abortRequest()", "versionFilter"):
            self.assertIn(fragment, script)
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        _, style = self.get("/ui/app.css")
        self.assertIn("--gc-brand", style)
        self.assertIn("prefers-reduced-transparency", style)

    def test_release_api_requires_token_and_filters_values(self):
        self.assertEqual(self.get("/v1/releases")[0], 401)
        code, body = self.get("/v1/releases?product=mesh", TOKEN)
        self.assertEqual(code, 200)
        records = json.loads(body)["releases"]
        self.assertEqual([r["version"] for r in records], ["2", "1"])
        self.assertEqual(self.get("/v1/releases?product=mesh&q=ignored", TOKEN)[0], 400)


if __name__ == "__main__":
    unittest.main()
