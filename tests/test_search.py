"""Search behavior shared by local storage, CLI, and authenticated API."""
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

TOKEN = "test-only-" + "x" * 40

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "changes.sqlite3"
        self.store = Store(self.db)
        self.store.add("mesh", "1.0", "added", "Sync 100%", description="Works_with local devices")
        self.store.add("gateway", "1.0", "fixed", "Gateway routing")

    def tearDown(self):
        self.tmp.cleanup()

    def test_literal_case_insensitive_matching(self):
        self.assertEqual(len(self.store.search("SYNC")), 1)
        self.assertEqual(len(self.store.search("%")), 1)
        self.assertEqual(len(self.store.search("_")), 1)
        self.assertEqual(self.store.search("gateway", product="mesh"), [])
        with self.assertRaises(ValueError):
            self.store.search(" ")
        with self.assertRaises(ValueError):
            self.store.search("x" * 257)

    def test_cli_search(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--db", str(self.db), "search", "sync"]), 0)
        self.assertEqual(json.loads(output.getvalue())[0]["product"], "mesh")

    def test_authenticated_search_api(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            conn.request("GET", "/v1/search?q=SYNC", headers={"Authorization": "Bearer " + TOKEN})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["entries"][0]["product"], "mesh")
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

if __name__ == "__main__":
    unittest.main()
