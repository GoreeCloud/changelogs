"""Aggregate summary regression tests."""
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

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite3"
        self.store = Store(self.db)
        self.store.add("mesh", "1", "added", "Sync")
        self.store.add("mesh", "2", "fixed", "Repair")
        self.store.add("gateway", "1", "added", "Routing")

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_aggregates_and_filters(self):
        all_rows = self.store.summary()
        self.assertEqual(all_rows["total"], 3)
        self.assertEqual(all_rows["by_kind"], {"added": 2, "fixed": 1})
        self.assertEqual(all_rows["by_product"]["mesh"], 2)
        self.assertEqual(self.store.summary("mesh")["total"], 2)
        self.assertEqual(self.store.summary("missing")["total"], 0)

    def test_cli_summary(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--db", str(self.db), "summary", "--product", "mesh"]), 0)
        self.assertEqual(json.loads(out.getvalue())["total"], 2)

    def test_api_summary_requires_auth(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request("GET", "/v1/summary?product=mesh")
            self.assertEqual(conn.getresponse().status, 401)
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request("GET", "/v1/summary?product=mesh", headers={"Authorization": "Bearer " + TOKEN})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["total"], 2)
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

if __name__ == "__main__":
    unittest.main()
