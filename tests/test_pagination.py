"""Bounded offset pagination regression tests."""
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

TOKEN = "test-" + "x" * 40

class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "records.sqlite3"
        self.store = Store(self.db)
        for i in range(5):
            self.store.add("mesh", "1", "added", "Change %d" % i)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pages_do_not_overlap(self):
        first = self.store.list(limit=2, offset=0)
        second = self.store.list(limit=2, offset=2)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertTrue({r["id"] for r in first}.isdisjoint({r["id"] for r in second}))
        self.assertEqual(len(self.store.search("Change", limit=2, offset=4)), 1)

    def test_invalid_offset(self):
        for value in (-1, 1000001, "1"):
            with self.assertRaises(ValueError):
                self.store.list(offset=value)
            with self.assertRaises(ValueError):
                self.store.search("Change", offset=value)

    def test_cli_offset(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.db), "list", "--limit", "2", "--offset", "2"]), 0)
        self.assertEqual(len(json.loads(output.getvalue())), 2)

    def test_api_offset_and_validation(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path, expected in (("/v1/entries?limit=2&offset=2", 200),
                                   ("/v1/search?q=Change&limit=2&offset=4", 200),
                                   ("/v1/entries?offset=-1", 400),
                                   ("/v1/summary?offset=1", 400)):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                conn.request("GET", path, headers={"Authorization": "Bearer " + TOKEN})
                response = conn.getresponse()
                self.assertEqual(response.status, expected)
                if expected == 200:
                    body = json.loads(response.read())
                    self.assertIn("offset", body)
                else:
                    response.read()
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

if __name__ == "__main__":
    unittest.main()
