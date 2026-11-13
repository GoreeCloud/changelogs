"""Exact lookahead pagination across filtered entries, search and release groups."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.pagination import entries_page
from goreecloud_changelogs.releases import page_releases
from goreecloud_changelogs.store import Store

TOKEN = "api-pagination-tests-" + "z" * 45


class ExactPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "entries.sqlite3")
        for i in range(4):
            self.store.add("mesh", "1" if i < 2 else "2", "added",
                           f"Match {i}", released_at="2026-01-02")
        self.store.add("vpn", "3", "fixed", "Unrelated", released_at="2026-01-01")
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.store, TOKEN))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def get(self, url):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", url, headers={"Authorization": "Bearer " + TOKEN})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_exactly_full_last_page_is_false(self):
        code, data = self.get("/v1/entries?product=mesh&limit=2&offset=2")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["entries"]), 2)
        self.assertFalse(data["has_more"])
        code, data = self.get("/v1/entries?product=mesh&limit=2&offset=0")
        self.assertEqual(code, 200)
        self.assertTrue(data["has_more"])
        self.assertEqual([r["id"] for r in data["entries"]],
                         sorted([r["id"] for r in data["entries"]], reverse=True))

    def test_search_and_versions_are_filtered_before_lookahead(self):
        self.assertTrue(self.get("/v1/search?q=match&limit=2")[1]["has_more"])
        self.assertFalse(self.get("/v1/search?q=match&limit=2&offset=2")[1]["has_more"])
        self.assertFalse(self.get("/v1/entries?version=3&limit=1")[1]["has_more"])
        self.assertFalse(self.get("/v1/search?q=Unrelated&limit=1")[1]["has_more"])

    def test_releases_uses_correct_group_lookahead(self):
        first = self.get("/v1/releases?product=mesh&limit=1")[1]
        self.assertTrue(first["has_more"])
        second = self.get("/v1/releases?product=mesh&limit=1&offset=1")[1]
        self.assertFalse(second["has_more"])
        self.assertEqual(len(second["releases"]), 1)
        self.assertFalse(self.get("/v1/releases?product=vpn&limit=1")[1]["has_more"])

    def test_empty_pages_and_boundary_limits(self):
        for endpoint in ("/v1/entries", "/v1/search?q=match", "/v1/releases"):
            sep = "&" if "?" in endpoint else "?"
            code, data = self.get(endpoint + sep + "offset=100&limit=2")
            self.assertEqual(code, 200)
            self.assertFalse(data["has_more"])
        rows, more = entries_page(self.store, product="mesh", limit=2, offset=1000000)
        self.assertEqual(rows, [])
        self.assertFalse(more)
        r, more = page_releases(self.store, limit=1, offset=1000000)
        self.assertEqual(r, [])
        self.assertFalse(more)

    def test_search_maximum_limit_uses_internal_lookahead(self):
        with self.store.connect() as db:
            db.executemany(
                "INSERT INTO entries (product,version,kind,title,description,author,"
                "released_at,metadata,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [("bulk", str(i), "added", f"Needle {i}", "", "",
                  "2026-01-01", "{}", "2026-01-01", "2026-01-01")
                 for i in range(1001)]
            )
        code, data = self.get("/v1/search?q=needle&limit=1000")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["entries"]), 1000)
        self.assertTrue(data["has_more"])
        code, data = self.get("/v1/search?q=needle&limit=1000&offset=1000")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["entries"]), 1)
        self.assertFalse(data["has_more"])


if __name__ == "__main__":
    unittest.main()
