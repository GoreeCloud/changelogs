"""Privacy defaults and read-only SQLite sidecar diagnostics."""
import os
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.backup import backup
from goreecloud_changelogs.store import Store, audit_permissions


@unittest.skipUnless(os.name == "posix", "POSIX permission modes")
class PrivacyDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_parent_is_private(self):
        directory = self.root / "database" / "private"
        db = directory / "entries.sqlite3"
        Store(db)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(db.stat().st_mode & 0o777, 0o600)
        self.assertTrue(audit_permissions(db)["secure"])

    def test_existing_parent_mode_is_never_silently_modified(self):
        directory = self.root / "existing"
        directory.mkdir(mode=0o755)
        os.chmod(directory, 0o755)
        db = directory / "entries.sqlite3"
        Store(db)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
        self.assertFalse(audit_permissions(db)["secure"])

    def test_sidecars_checked_without_mutation(self):
        db = self.root / "private" / "entries.sqlite3"
        Store(db)
        sidecar = Path(str(db) + "-wal")
        sidecar.write_text("placeholder", encoding="utf-8")
        os.chmod(sidecar, 0o644)
        result = audit_permissions(db)
        self.assertFalse(result["secure"])
        self.assertTrue(any("wal:" in s for s in result["findings"]))
        self.assertEqual(sidecar.stat().st_mode & 0o777, 0o644)
        os.chmod(sidecar, 0o600)
        self.assertTrue(audit_permissions(db)["secure"])
        sidecar.unlink()
        sidecar.symlink_to(db)
        self.assertFalse(audit_permissions(db)["secure"])

    def test_database_parent_symlink_is_refused(self):
        actual = self.root / "actual"
        actual.mkdir()
        link = self.root / "link"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "parent directory"):
            Store(link / "entries.sqlite3")
        self.assertFalse((actual / "entries.sqlite3").exists())

    def test_backup_creates_private_new_parent(self):
        db = self.root / "entries.sqlite3"
        store = Store(db)
        store.add("mesh", "1.0", "added", "Example")
        folder = self.root / "new-private"
        destination = folder / "backup.sqlite3"
        backup(store, destination)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_backup_parent_symlink_is_refused(self):
        db = self.root / "entries.sqlite3"
        store = Store(db)
        actual = self.root / "backup"
        actual.mkdir()
        link = self.root / "link"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "parent directory"):
            backup(store, link / "snapshot.sqlite3")
        self.assertFalse((actual / "snapshot.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
