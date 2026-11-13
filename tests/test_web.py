"""Optional web viewer and individual read-only entry tests."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.store import Store

TOKEN = "web-test-" + "w" * 40


class WebViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "web.sqlite3")
        self.id = self.store.add("mesh", "0.1.0", "added", "<script>alert(1)</script>",
                                 description="An example <tag> rendered as text")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0),
                                          make_handler(self.store, TOKEN, web=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def get(self, path, token=None, method="GET"):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Authorization": "Bearer " + token} if token else {}
        client.request(method, path, headers=headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        client.close()
        return result

    def test_web_assets_are_unprivileged_and_hardened(self):
        for path, content_type in (("/", "text/html"), ("/ui/app.js", "text/javascript"),
                                   ("/ui/app.css", "text/css")):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(content_type))
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertTrue(body)
        self.assertEqual(self.get("/v1/entries")[0], 401)

    def test_entry_detail_and_missing_or_malformed_id(self):
        status, _, body = self.get("/v1/entries/" + str(self.id), TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["entry"]["title"], "<script>alert(1)</script>")
        self.assertEqual(self.get("/v1/entries/999", TOKEN)[0], 404)
        self.assertEqual(self.get("/v1/entries/0", TOKEN)[0], 400)
        self.assertEqual(self.get("/v1/entries/1?anything=yes", TOKEN)[0], 400)
        self.assertEqual(self.get("/v1/entries/" + str(self.id))[0], 401)
        self.assertEqual(self.get("/v1/entries", TOKEN, "POST")[0], 405)

    def test_default_handler_does_not_serve_web_assets(self):
        no_web = make_handler(self.store, TOKEN)
        self.assertTrue(callable(no_web))
        self.assertFalse(getattr(no_web, "web", False))


if __name__ == "__main__":
    unittest.main()
