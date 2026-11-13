import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.store import Store

TOKEN = "test-only-token-" + "x" * 40

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.sqlite3")
        self.store.add("mesh", "1.0", "added", "Secure synchronization")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request(self, method, path, authorized=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Authorization": "Bearer " + TOKEN} if authorized else {}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        status, headers, body = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, headers, json.loads(body)

    def test_requires_bearer_token_even_for_health(self):
        self.assertEqual(self.request("GET", "/health", False)[0], 401)
        self.assertEqual(self.request("GET", "/health")[2]["status"], "ok")

    def test_lists_filtered_entries(self):
        status, headers, body = self.request("GET", "/v1/entries?product=mesh&limit=1")
        self.assertEqual(status, 200)
        self.assertEqual(body["entries"][0]["title"], "Secure synchronization")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_rejects_writes_and_invalid_queries(self):
        self.assertEqual(self.request("POST", "/v1/entries")[0], 405)
        self.assertEqual(self.request("GET", "/v1/entries?limit=100000")[0], 400)
        self.assertEqual(self.request("GET", "/v1/entries?unexpected=1")[0], 400)
        self.assertEqual(self.request("GET", "/v1/entries?product=a&product=b")[0], 400)

if __name__ == "__main__":
    unittest.main()
