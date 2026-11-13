"""Known-kind filters on CLI, store, API and web viewer."""
import contextlib
import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.cli import main
from goreecloud_changelogs.store import Store

TOKEN = "kind-filter-test-" + "w" * 46


class KindFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "items.sqlite3"
        self.store = Store(self.db)
        self.store.add("mesh", "1", "security", "Token validation")
        self.store.add("mesh", "1", "fixed", "Token update")
        self.store.add("vpn", "2", "security", "Firewall policy")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.store, TOKEN, web=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def api(self, path, auth=True):
        con = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            headers = {"Authorization": "Bearer " + TOKEN} if auth else {}
            con.request("GET", path, headers=headers)
            response = con.getresponse()
            return response.status, response.read().decode("utf-8")
        finally:
            con.close()

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--db", str(self.db), *args])
        return code, json.loads(out.getvalue())

    def test_store_list_and_search_filters_are_parameterized(self):
        self.assertEqual(len(self.store.list(kind="security")), 2)
        self.assertEqual(len(self.store.list(product="mesh", kind="security")), 1)
        self.assertEqual(len(self.store.search("token", kind="fixed")), 1)
        self.assertEqual(self.store.search("token", kind="security")[0]["title"],
                         "Token validation")
        with self.assertRaises(ValueError):
            self.store.list(kind="nonexistent")
        with self.assertRaises(ValueError):
            self.store.search("token", kind="security' OR 1=1 --")

    def test_cli_kind_filter(self):
        self.assertEqual(self.cli("list", "--kind", "security")[0], 0)
        self.assertEqual(len(self.cli("list", "--kind", "security")[1]), 2)
        code, rows = self.cli("search", "token", "--product", "mesh", "--kind", "fixed")
        self.assertEqual(code, 0)
        self.assertEqual([row["title"] for row in rows], ["Token update"])

    def test_api_kind_filter_auth_and_rejections(self):
        code, _ = self.api("/v1/entries?kind=security", auth=False)
        self.assertEqual(code, 401)
        code, data = self.api("/v1/entries?kind=security&product=mesh&limit=1")
        self.assertEqual(code, 200)
        entries = json.loads(data)
        self.assertEqual(len(entries["entries"]), 1)
        self.assertFalse(entries["has_more"])
        code, data = self.api("/v1/search?q=token&kind=fixed")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)["entries"][0]["title"], "Token update")
        for path in ("/v1/entries?kind=invalid",
                     "/v1/search?q=token&kind=invalid",
                     "/v1/entries?kind=security&kind=fixed",
                     "/v1/releases?kind=security", "/v1/summary?kind=security"):
            with self.subTest(path=path):
                self.assertEqual(self.api(path)[0], 400)

    def test_web_controls_use_semantic_kind_values(self):
        html = self.api("/")[1]
        script = self.api("/ui/app.js")[1]
        self.assertIn('id="kind-input"', html)
        self.assertIn('value="security"', html)
        self.assertIn('params.set("kind", kind)', script)
        self.assertIn('byId("kind-input").disabled', script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
