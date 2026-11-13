"""A missing or damaged hosted workspace must fail preflight without mutation."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.hosted_auth import AuthStore
from goreecloud_changelogs.hosted_diagnostics import diagnose_host
from goreecloud_changelogs.store import Store


class HostedDoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "workspace"

    def tearDown(self):
        self.tmp.cleanup()

    def setup_workspace(self):
        self.data.mkdir(mode=0o700)
        records = Store(self.data / "changelogs.sqlite3")
        records.add("mesh", "1.0", "fixed", "A private change")
        users = AuthStore(self.data / "accounts.sqlite3", initialize=True)
        users.bootstrap("admin", "very-long-operator-password")
        return records, users

    def run_doctor(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["host", "doctor", "--data-dir", str(self.data)])
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_missing_workspace_is_never_created(self):
        code, report, stderr = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertFalse(report["healthy"])
        self.assertFalse(self.data.exists())
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_valid_host_data_and_auth_status(self):
        rows, users = self.setup_workspace()
        before = rows.list()
        code, report, stderr = self.run_doctor()
        self.assertEqual(code, 0, stderr)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["changelogs"]["entries"], 1)
        self.assertEqual(report["accounts"]["users"], 1)
        self.assertEqual(report["accounts"]["active_session_hashes"], 0)
        self.assertEqual(rows.list(), before)
        self.assertNotIn("A private change", json.dumps(report))
        self.assertNotIn("admin", json.dumps(report))

    @unittest.skipUnless(os.name == "posix", "POSIX permission check")
    def test_world_readable_database_fails_without_chmod(self):
        rows, _ = self.setup_workspace()
        os.chmod(rows.path, 0o644)
        code, report, _ = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertFalse(report["permissions"]["ok"])
        self.assertEqual(rows.path.stat().st_mode & 0o777, 0o644)

    def test_missing_account_database_does_not_initialize_accounts(self):
        self.data.mkdir(mode=0o700)
        Store(self.data / "changelogs.sqlite3")
        code, report, _ = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertTrue(report["changelogs"]["ok"])
        self.assertFalse(report["accounts"]["ok"])
        self.assertFalse((self.data / "accounts.sqlite3").exists())

    def test_incompatible_account_schema_does_not_modify_data(self):
        _, users = self.setup_workspace()
        with closing(sqlite3.connect(users.path)) as db:
            db.execute("CREATE VIEW suspicious_view AS SELECT username FROM users")
        code, report, _ = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertFalse(report["accounts"]["ok"])
        self.assertNotIn("suspicious", json.dumps(report).lower())


if __name__ == "__main__":
    unittest.main()
