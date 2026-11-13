"""Regression tests for CLI backup and restore confirmation."""
import contextlib
import io
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

    def test_backup_refuses_overwrite(self):
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 0)
        self.assertEqual(self.invoke("backup", str(self.snapshot)), 1)

if __name__ == "__main__":
    unittest.main()
