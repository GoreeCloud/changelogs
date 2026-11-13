"""Regression tests for CLI backup and restore confirmation."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from goreecloud_changelogs.cli import main
from goreecloud_changelogs.store import Store

class CLIRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "records.sqlite3"
        self.snapshot = self.root / "snapshot.sqlite3"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(["--db", str(self.db), *args])

    def test_restore_requires_confirmation(self):
        self.store.add("mesh", "1", "added", "Before")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        self.store.add("mesh", "2", "fixed", "After")
        self.assertEqual(self.invoke("restore", str(self.snapshot)), 1)
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.invoke("restore", str(self.snapshot), "--yes"), 0)
        self.assertEqual([r["title"] for r in self.store.list()], ["Before"])

    def test_recovery_snapshot_before_restore(self):
        self.store.add("mesh", "1", "added", "Before")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        self.store.add("mesh", "2", "fixed", "After")
        recovery = self.root / "recovery.sqlite3"
        self.assertEqual(self.invoke("restore", str(self.snapshot), "--yes", "--recovery-backup", str(recovery)), 0)
        self.assertEqual([r["title"] for r in self.store.list()], ["Before"])
        from goreecloud_changelogs.backup import verify_backup, restore
        self.assertEqual(verify_backup(recovery)["entries"], 2)
        restore(self.store, recovery)
        self.assertEqual(len(self.store.list()), 2)

    def test_recovery_snapshot_collision_blocks_restore(self):
        self.store.add("mesh", "1", "added", "Before")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        self.store.add("mesh", "2", "fixed", "After")
        self.assertEqual(self.invoke("restore", str(self.snapshot), "--yes", "--recovery-backup", str(self.snapshot)), 1)
        self.assertEqual(len(self.store.list()), 2)
        self.assertEqual(self.invoke("restore", str(self.snapshot), "--yes", "--recovery-backup", str(self.db)), 1)
        self.assertEqual(len(self.store.list()), 2)

    def test_invalid_source_does_not_create_recovery(self):
        self.store.add("mesh", "1", "added", "Preserve")
        invalid = self.root / "invalid.sqlite3"
        invalid.write_bytes(b"invalid")
        recovery = self.root / "recovery.sqlite3"
        self.assertEqual(self.invoke("restore", str(invalid), "--yes", "--recovery-backup", str(recovery)), 1)
        self.assertFalse(recovery.exists())
        self.assertEqual([r["title"] for r in self.store.list()], ["Preserve"])

    def test_restore_dry_run_does_not_create_live_database(self):
        self.store.add("mesh", "1", "added", "Snapshot")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        missing = self.root / "missing-live.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["--db", str(missing), "restore", str(self.snapshot), "--dry-run"])
        self.assertEqual(result, 0)
        self.assertFalse(missing.exists())
        self.assertEqual(len(self.store.list()), 1)

    def test_restore_dry_run_rejects_invalid_source(self):
        invalid = self.root / "corrupt.sqlite3"
        invalid.write_bytes(b"not sqlite")
        missing = self.root / "missing-live.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["--db", str(missing), "restore", str(invalid), "--dry-run"])
        self.assertEqual(result, 1)
        self.assertFalse(missing.exists())

    def test_dry_run_rejects_live_hardlink_alias(self):
        if not hasattr(os, "link"):
            self.skipTest("hard links unavailable")
        self.store.add("mesh", "1", "added", "Preserve")
        alias = self.root / "alias.sqlite3"
        os.link(self.db, alias)
        self.assertEqual(self.invoke("restore", str(alias), "--dry-run"), 1)
        self.assertEqual(len(self.store.list()), 1)

    def test_dry_run_rejects_recovery_backup_option(self):
        self.store.add("mesh", "1", "added", "Preserve")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        recovery = self.root / "unused-recovery.sqlite3"
        self.assertEqual(self.invoke("restore", str(self.snapshot), "--dry-run", "--recovery-backup", str(recovery)), 1)
        self.assertFalse(recovery.exists())

    def test_restore_without_confirmation_does_not_create_live_db(self):
        self.store.add("mesh", "1", "added", "Source")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        missing = self.root / "never-created" / "live.sqlite3"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = main(["--db", str(missing), "restore", str(self.snapshot)])
        self.assertEqual(code, 1)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())

    def test_invalid_confirmed_restore_does_not_create_live_db(self):
        invalid = self.root / "corrupt.sqlite3"
        invalid.write_bytes(b"invalid database")
        missing = self.root / "never-created" / "live.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["--db", str(missing), "restore", str(invalid), "--yes"])
        self.assertEqual(code, 1)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())

    def test_recovery_destination_collision_preflight(self):
        self.store.add("mesh", "1", "added", "Source")
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        other = self.root / "existing.sqlite3"
        other.write_text("do not overwrite", encoding="utf-8")
        missing = self.root / "never-created" / "live.sqlite3"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = main(["--db", str(missing), "restore", str(self.snapshot),
                         "--yes", "--recovery-backup", str(other)])
        self.assertEqual(code, 1)
        self.assertFalse(missing.exists())
        self.assertFalse(missing.parent.exists())
        self.assertEqual(other.read_text(encoding="utf-8"), "do not overwrite")

    def test_backup_refuses_overwrite(self):
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 1)

if __name__ == "__main__":
    unittest.main()
