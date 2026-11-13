import sqlite3
import tempfile
import unittest
from pathlib import Path
from goreecloud_changelogs.backup import backup, restore
from goreecloud_changelogs.store import Store

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.store = Store(self.base / "live.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.store.add("mesh", "1.0", "added", "First")
        destination = self.base / "snapshot.sqlite3"
        backup(self.store, destination)
        self.store.add("mesh", "1.1", "fixed", "Second")
        restore(self.store, destination)
        self.assertEqual([r["title"] for r in self.store.list()], ["First"])

    def test_no_clobber(self):
        destination = self.base / "snapshot.sqlite3"
        backup(self.store, destination)
        with self.assertRaises(ValueError):
            backup(self.store, destination)

    def test_reject_invalid_database(self):
        invalid = self.base / "invalid.sqlite3"
        with sqlite3.connect(invalid) as db:
            db.execute("CREATE TABLE other (id INTEGER)")
        with self.assertRaises(ValueError):
            restore(self.store, invalid)

if __name__ == "__main__":
    unittest.main()
