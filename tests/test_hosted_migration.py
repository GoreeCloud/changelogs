"""Preview-first legacy SQLite migration into the authenticated shared server."""
import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.hosted_auth import AuthStore
from goreecloud_changelogs.hosted_server import make_hosted_handler
from goreecloud_changelogs.hosted_migration import batches, preview, upload, read_snapshot
from goreecloud_changelogs.store import Store

ORIGIN = "https://changelogs.example.test"
PASSWORD = "example-operator-long-password"


class HostedMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        data = self.root / "private"
        data.mkdir(mode=0o700)
        self.local = Store(self.root / "local" / "entries.sqlite3")
        self.hosted = Store(data / "changelogs.sqlite3")
        self.auth = AuthStore(data / "accounts.sqlite3", initialize=True)
        self.auth.bootstrap("admin", PASSWORD)
        self.host = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_hosted_handler(self.hosted, self.auth, ORIGIN,
                                allow_test_loopback_host=True)
        )
        self.thread = threading.Thread(target=self.host.serve_forever, daemon=True)
        self.thread.start()
        self.local.add("mesh", "1.0", "added", "Previously local CLI change",
                       description="Migrate once, see everywhere")
        admin = self.auth.authenticate("admin", PASSWORD)
        self.token, _, _ = self.auth.issue(admin["id"], "token")

    def tearDown(self):
        self.host.shutdown()
        self.host.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def fake_https(self, request):
        url = urlsplit(request.full_url)
        connection = http.client.HTTPConnection("127.0.0.1", self.host.server_port,
                                                timeout=4)
        try:
            connection.request(
                request.get_method(),
                url.path + ("?" + url.query if url.query else ""),
                body=request.data, headers=dict(request.header_items())
            )
            result = connection.getresponse()
            return result.status, result.read()
        finally:
            connection.close()

    def test_preview_never_uploads_or_modifies_source(self):
        before = self.local.list()
        snapshot, chunks, report = preview(self.local.path)
        self.assertEqual(report["validated"], 1)
        self.assertEqual(report["batches"], 1)
        self.assertEqual(len(report["sha256"]), 64)
        self.assertEqual(self.hosted.list(), [])
        self.assertEqual(self.local.list(), before)
        self.assertEqual(chunks[0][0]["title"], "Previously local CLI change")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--server", ORIGIN, "migrate", "--source",
                         str(self.local.path)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["dry_run"])
        self.assertEqual(self.hosted.list(), [])

    def test_authenticated_migration_is_idempotent_and_readable(self):
        rows, parts, report = preview(self.local.path)
        first = upload(ORIGIN, self.token, parts, transport=self.fake_https)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(self.hosted.list()[0]["title"], rows[0]["title"])
        second = upload(ORIGIN, self.token, parts, transport=self.fake_https)
        self.assertEqual(second["skipped_existing"], 1)
        self.assertEqual(len(self.hosted.list()), 1)
        self.assertEqual(len(self.local.list()), 1)

    def test_reader_cannot_import(self):
        self.auth.add_user("reader", "reader-only-long-password")
        reader = self.auth.authenticate("reader", "reader-only-long-password")
        token, _, _ = self.auth.issue(reader["id"], "token")
        _, chunks, _ = preview(self.local.path)
        with self.assertRaisesRegex(ValueError, "Unexpected server response"):
            upload(ORIGIN, token, chunks, transport=self.fake_https)
        self.assertEqual(self.hosted.list(), [])

    def test_malformed_batch_is_atomic(self):
        rows, chunks, _ = preview(self.local.path)
        original = rows[0]
        connection = http.client.HTTPConnection("127.0.0.1", self.host.server_port,
                                                timeout=4)
        data = json.dumps({"entries": [original, {**original, "kind": "not-real"}]}).encode()
        try:
            connection.request("POST", "/v1/import", body=data, headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json"
            })
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            connection.close()
        self.assertEqual(self.hosted.list(), [])

    def test_batched_upload_splits_at_hundred(self):
        with self.local.connect() as db:
            db.executemany(
                "INSERT INTO entries (product,version,kind,title,description,author,"
                "released_at,metadata,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                [("mesh","2","added",f"Row {i}","","","2026-01-01","{}",
                  "2026-01-01","2026-01-01") for i in range(105)]
            )
        rows, parts, report = preview(self.local.path)
        self.assertEqual(len(rows), 106)
        self.assertEqual([len(chunk) for chunk in parts], [100, 6])
        result = upload(ORIGIN, self.token, parts, transport=self.fake_https)
        self.assertEqual(result["inserted"], 106)
        self.assertEqual(result["batches"], 2)

    def test_digest_mismatch_rejected_without_network(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("goreecloud_changelogs.hosted_migration.upload") as mock:
            with patch.dict(os.environ, {"GOREE_CHANGELOGS_REMOTE_TOKEN": self.token}):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(["--server", ORIGIN, "migrate",
                                 "--source", str(self.local.path),
                                 "--yes", "--expect-sha256", "0" * 64])
            mock.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("reviewed", err.getvalue())
        self.assertEqual(self.hosted.list(), [])

    def test_missing_or_symlink_source_not_initialized(self):
        missing = self.root / "missing" / "entries.sqlite3"
        with self.assertRaises(ValueError):
            read_snapshot(missing)
        self.assertFalse(missing.parent.exists())
        link = self.root / "symlink.sqlite3"
        link.symlink_to(self.local.path)
        with self.assertRaises(ValueError):
            read_snapshot(link)


if __name__ == "__main__":
    unittest.main()
