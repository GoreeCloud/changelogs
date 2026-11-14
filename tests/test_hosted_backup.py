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
from goreecloud_changelogs.hosted_backup import backup_host, verify_host_backup, stage_host_restore
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

    def test_stage_restore_private_two_database_readback_without_live_mutation(self):
        backup_host(self.data, self.output, offline_ack=True)
        target = self.root / "stage-new"
        result = stage_host_restore(self.output, target)
        self.assertEqual(result, {"staged": True, "entries": 1,
                                  "users": 1, "sessions_saved": 0,
                                  "deployed": False})
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ["accounts.sqlite3", "changelogs.sqlite3"])
        if os.name == "posix":
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600
                                for p in target.iterdir()))
        from goreecloud_changelogs.hosted_diagnostics import diagnose_host
        report = diagnose_host(target)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["changelogs"]["entries"], 1)
        self.assertEqual(report["accounts"]["active_session_hashes"], 0)
        self.assertIsNotNone(self.accounts.resolve(self.token, "token"))
        self.assertEqual(self.entries.list()[0]["title"], "Host backup test")

    def test_stage_restore_rejects_existing_target_and_tampered_database(self):
        backup_host(self.data, self.output, offline_ack=True)
        target = self.root / "stage-existing"
        target.mkdir(mode=0o700)
        sentinel = target / "preserve.txt"
        sentinel.write_text("owner file")
        with self.assertRaisesRegex(ValueError, "new"):
            stage_host_restore(self.output, target)
        self.assertEqual(sentinel.read_text(), "owner file")
        fresh = self.root / "stage-refused"
        with (self.output / "changelogs.sqlite3").open("ab") as stream:
            stream.write(b"genuine tampering")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            stage_host_restore(self.output, fresh)
        self.assertFalse(fresh.exists())
        self.assertEqual(self.entries.list()[0]["title"], "Host backup test")

    def test_cli_stage_restore_returns_no_credentials_and_never_overwrites(self):
        backup_host(self.data, self.output, offline_ack=True)
        target = self.root / "cli-staged"
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(["host", "stage-restore", "--source", str(self.output),
                         "--destination", str(target)])
        self.assertEqual(code, 0, error.getvalue())
        self.assertTrue(json.loads(output.getvalue())["staged"])
        self.assertNotIn(self.token, output.getvalue())
        self.assertNotIn("test-password-long-enough", output.getvalue())
        self.assertEqual(len(list(target.iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
