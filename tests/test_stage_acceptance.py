"""Disposable acceptance rehearsal; never touch real device or production data."""
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.store import Store
from scripts.stage_acceptance import check, main

TOKEN = "staging-acceptance-only-" + "x" * 46


class StageAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "private" / "data.sqlite3"
        self.server = None
        self.thread = None

    def tearDown(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
        self.temp.cleanup()

    def _start_api(self):
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(Store(self.db), TOKEN, web=True))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_port

    def test_missing_path_not_created_or_logged(self):
        result = check(self.db)
        self.assertFalse(result["passed"])
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_valid_snapshot_does_not_modify_rows(self):
        store = Store(self.db)
        store.add("mesh", "1", "added", "Private entry")
        before = store.list()
        result = check(self.db)
        self.assertTrue(result["passed"])
        self.assertEqual(result["sqlite"]["entries"], 1)
        self.assertFalse(result["api"]["checked"])
        self.assertEqual(store.list(), before)
        self.assertNotIn("Private entry", json.dumps(result))

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_exposed_mode_fails_without_repair(self):
        Store(self.db)
        os.chmod(self.db, 0o644)
        result = check(self.db)
        self.assertFalse(result["passed"])
        self.assertTrue(result["sqlite"]["passed"])
        self.assertFalse(result["permissions"]["secure"])
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o644)

    def test_loopback_api_controls_and_unchanged_data(self):
        store = Store(self.db)
        store.add("mesh", "1", "added", "Do not disclose")
        before = store.list()
        result = check(self.db, self._start_api(), TOKEN)
        self.assertTrue(result["passed"])
        self.assertTrue(result["api"]["authentication_enforced"])
        self.assertFalse(result["api"]["write_methods_tested"])
        self.assertTrue(result["api"]["security_headers"])
        self.assertNotIn("Do not disclose", json.dumps(result))
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertEqual(store.list(), before)

    def test_api_probes_never_send_write_method(self):
        from scripts import stage_acceptance as acceptance
        source = Path(acceptance.__file__).read_text(encoding="utf-8")
        self.assertIn('connection.request("GET", path, headers=headers)', source)
        self.assertNotIn('connection.request("POST"', source)
        self.assertNotIn('connection.request(method,', source)

    def test_wrong_token_cannot_pass_api_verification(self):
        Store(self.db)
        result = check(self.db, self._start_api(), "z" * 44)
        self.assertFalse(result["passed"])
        self.assertFalse(result["api"]["health"])
        self.assertNotIn("z" * 44, json.dumps(result))

    def test_cli_reports_sanitized_json_and_exit_status(self):
        Store(self.db)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--db", str(self.db)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["passed"])
        self.assertNotIn(str(self.root), out.getvalue())


if __name__ == "__main__":
    unittest.main()
