"""First-class release summaries and literal Markdown release notes."""
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
from goreecloud_changelogs.releases import list_releases, release_details, markdown_release
from goreecloud_changelogs.store import Store


TOKEN = "integration-test-" + "x" * 50


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "notes.sqlite3"
        self.store = Store(self.db)
        self.store.add("mesh", "1.0", "added", "Initial", released_at="2026-03-01",
                       description="<script>\n[unsafe](javascript:alert(1))")
        self.store.add("mesh", "1.0", "security", "Token guard", released_at="2026-03-02",
                       author="Operations")
        self.store.add("mesh", "2.0", "fixed", "Socket fix", released_at="2026-04-01")
        self.store.add("vpn", "1.0", "changed", "Config", released_at="2026-02-01")

    def tearDown(self):
        self.temp.cleanup()

    def test_aggregate_dates_kinds_and_order(self):
        releases = list_releases(self.store)
        self.assertEqual([(r["product"], r["version"]) for r in releases],
                         [("mesh", "2.0"), ("mesh", "1.0"), ("vpn", "1.0")])
        self.assertEqual(releases[1]["entries"], 2)
        self.assertEqual(releases[1]["first_released_at"], "2026-03-01")
        self.assertEqual(releases[1]["released_at"], "2026-03-02")
        self.assertEqual(releases[1]["by_kind"], {"added": 1, "security": 1})
        self.assertEqual(len(list_releases(self.store, product="mesh")), 2)
        self.assertEqual(list_releases(self.store, limit=1, offset=1)[0]["version"], "1.0")

    def test_notes_safe_markdown_and_json(self):
        release = release_details(self.store, "mesh", "1.0")
        self.assertEqual(len(release["entries"]), 2)
        text = markdown_release(release)
        self.assertIn("## Added", text)
        self.assertIn("## Security", text)
        self.assertNotIn("<script>", text)
        self.assertNotIn("[unsafe]", text)
        self.assertIn("Token guard", text)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["--db", str(self.db), "release-notes", "mesh", "1.0", "--format", "json"])
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["entries"]), 2)

    def test_invalid_or_missing_release(self):
        with self.assertRaisesRegex(ValueError, "Release not found"):
            release_details(self.store, "mesh", "404")
        with self.assertRaisesRegex(ValueError, "limit"):
            list_releases(self.store, limit=1001)
        with self.assertRaisesRegex(ValueError, "offset"):
            list_releases(self.store, offset=-1)
        with self.assertRaises(ValueError):
            release_details(self.store, " ", "1")

    def test_cli_release_summary(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["--db", str(self.db), "releases", "--product", "vpn"]), 0)
        self.assertEqual(json.loads(out.getvalue())[0]["product"], "vpn")

    def test_api_uses_token_and_strict_filters(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def get(route, authorized=True):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            headers = {"Authorization": "Bearer " + TOKEN} if authorized else {}
            try:
                conn.request("GET", route, headers=headers)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        try:
            self.assertEqual(get("/v1/releases", authorized=False)[0], 401)
            code, data = get("/v1/releases?product=mesh&limit=1")
            self.assertEqual(code, 200)
            self.assertEqual(len(data["releases"]), 1)
            self.assertTrue(data["has_more"])
            self.assertEqual(data["releases"][0]["version"], "2.0")
            self.assertEqual(get("/v1/releases?offset=-1")[0], 400)
            self.assertEqual(get("/v1/releases?q=unused")[0], 400)
            self.assertEqual(get("/v1/releases?product=x&product=y")[0], 400)
            self.assertEqual(get("/v1/releases?limit=1001")[0], 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
