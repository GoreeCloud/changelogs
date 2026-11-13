import sqlite3
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from goreecloud_changelogs.backup import backup, restore, verify_backup
from goreecloud_changelogs.cli import main
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

    def test_private_backup_and_no_temp_files(self):
        destination = self.base / "snapshot.sqlite3"
        backup(self.store, destination)
        self.assertEqual(list(self.base.glob("snapshot.sqlite3.partial-*")), [])
        if os.name == "posix":
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

    def test_verify_backup_read_only_without_creating_database(self):
        self.store.add("mesh", "1", "added", "One")
        destination = self.base / "snapshot.sqlite3"
        backup(self.store, destination)
        self.assertEqual(verify_backup(destination), {"valid": True, "entries": 1})
        unused_db = self.base / "unused.sqlite3"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--db", str(unused_db), "verify-backup", str(destination)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"valid": True, "entries": 1})
        self.assertFalse(unused_db.exists())

    def test_verify_rejects_invalid_backup(self):
        invalid = self.base / "not-sqlite"
        invalid.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            verify_backup(invalid)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["verify-backup", str(invalid)]), 1)

    def test_reject_invalid_database(self):
        invalid = self.base / "invalid.sqlite3"
        with sqlite3.connect(invalid) as db:
            db.execute("CREATE TABLE other (id INTEGER)")
        with self.assertRaises(ValueError):
            restore(self.store, invalid)

if __name__ == "__main__":
    unittest.main()
