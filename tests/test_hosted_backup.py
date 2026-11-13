"""Disposable two-database host backups and account-session sanitization."""
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
from goreecloud_changelogs.hosted_backup import backup_host, verify_host_backup
from goreecloud_changelogs.store import Store


class HostedBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="changelogs-host-backup-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "server"
        self.data.mkdir(mode=0o700)
        self.entries = Store(self.data / "changelogs.sqlite3")
        self.entries.add("mesh", "1", "fixed", "Host backup test")
        self.accounts = AuthStore(self.data / "accounts.sqlite3", initialize=True)
        self.accounts.bootstrap("admin", "test-password-long-enough")
        admin = self.accounts.authenticate("admin", "test-password-long-enough")
        self.token, _, _ = self.accounts.issue(admin["id"], "token")
        self.out_parent = self.root / "private-backups"
        self.out_parent.mkdir(mode=0o700)
        self.output = self.out_parent / "snapshot-1"

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_ack_required_without_side_effects(self):
        with self.assertRaisesRegex(ValueError, "offline-ack"):
            backup_host(self.data, self.output)
        self.assertFalse(self.output.exists())
        self.assertIsNotNone(self.accounts.resolve(self.token, "token"))

    def test_backup_is_private_complete_and_session_free(self):
        result = backup_host(self.data, self.output, offline_ack=True)
        self.assertTrue(result["created"])
        self.assertEqual((result["entries"], result["users"], result["sessions_saved"]),
                         (1, 1, 0))
        valid = verify_host_backup(self.output)
        self.assertTrue(valid["valid"])
        self.assertEqual(valid["entries"], 1)
        self.assertTrue((self.output / "manifest.json").is_file())
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
            for name in ("changelogs.sqlite3","accounts.sqlite3","manifest.json"):
                self.assertEqual((self.output/name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.entries.list()[0]["title"], "Host backup test")
        # The source still has its active session, but the verified backup does not.
        self.assertIsNotNone(self.accounts.resolve(self.token, "token"))
        recovered = AuthStore(self.output / "accounts.sqlite3")
        self.assertIsNone(recovered.resolve(self.token, "token"))
        self.assertEqual(recovered.authenticate("admin", "test-password-long-enough")
                         ["role"], "admin")

    def test_no_overwrite_and_tamper_detection(self):
        backup_host(self.data, self.output, offline_ack=True)
        old = (self.output / "manifest.json").read_bytes()
        with self.assertRaises(ValueError):
            backup_host(self.data, self.output, offline_ack=True)
        self.assertEqual((self.output / "manifest.json").read_bytes(), old)
        with (self.output / "changelogs.sqlite3").open("ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            verify_host_backup(self.output)

    def test_incomplete_snapshot_and_extra_files_refused(self):
        self.output.mkdir(mode=0o700)
        (self.output / "changelogs.sqlite3").write_bytes(b"sqlite not complete")
        with self.assertRaises(ValueError):
            verify_host_backup(self.output)
        self.assertFalse((self.output / "manifest.json").exists())

    def test_source_database_exposure_blocks_snapshot(self):
        if os.name != "posix":
            self.skipTest("POSIX mode checks")
        os.chmod(self.entries.path, 0o644)
        with self.assertRaisesRegex(ValueError, "privacy"):
            backup_host(self.data, self.output, offline_ack=True)
        self.assertFalse(self.output.exists())

    def test_extra_source_schema_object_refused(self):
        with closing(sqlite3.connect(self.data / "accounts.sqlite3")) as db:
            db.execute("CREATE VIEW unexpected_auth_view AS SELECT username FROM users")
        with self.assertRaisesRegex(ValueError, "schema"):
            backup_host(self.data, self.output, offline_ack=True)
        self.assertFalse(self.output.exists())

    def test_cli_host_backup_and_verify_use_no_staged_secrets(self):
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(["host", "backup", "--data-dir", str(self.data),
                         "--destination", str(self.output), "--offline-ack"])
        self.assertEqual(code, 0, error.getvalue())
        self.assertEqual(json.loads(output.getvalue())["users"], 1)
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(["host", "verify-backup", "--source", str(self.output)])
        self.assertEqual(code, 0, error.getvalue())
        self.assertTrue(json.loads(output.getvalue())["valid"])
        self.assertNotIn("test-password-long-enough", output.getvalue())
        self.assertNotIn(self.token, output.getvalue())


if __name__ == "__main__":
    unittest.main()
