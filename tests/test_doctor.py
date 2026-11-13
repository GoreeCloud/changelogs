"""Non-mutating local diagnostics keep database initialization and repairs separate."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.store import Store


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "records"
        self.db = self.folder / "entries.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def doctor(self, target=None):
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(["--db", str(target or self.db), "doctor"])
        return code, json.loads(output.getvalue()), error.getvalue()

    def test_missing_db_does_not_create_paths(self):
        self.assertFalse(self.folder.exists())
        code, report, error = self.doctor()
        self.assertEqual(code, 1)
        self.assertFalse(report["healthy"])
        self.assertFalse(report["integrity"]["ok"])
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.db.exists())
        self.assertEqual(error, "")

    def test_valid_private_db_reports_counts_without_mutation(self):
        store = Store(self.db)
        store.add("mesh", "1.0", "added", "Stable sync")
        before = self.db.stat()
        code, report, error = self.doctor()
        self.assertEqual(code, 0)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["integrity"]["entries"], 1)
        self.assertTrue(report["permissions"]["secure"])
        self.assertEqual(self.db.stat().st_size, before.st_size)
        self.assertEqual(error, "")

    @unittest.skipUnless(os.name == "posix", "POSIX privacy modes")
    def test_exposed_directory_reports_failure_without_chmod(self):
        Store(self.db)
        os.chmod(self.folder, 0o755)
        code, report, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertTrue(report["integrity"]["ok"])
        self.assertFalse(report["permissions"]["secure"])
        self.assertTrue(any("directory:" in finding for finding in report["permissions"]["findings"]))
        self.assertEqual(self.folder.stat().st_mode & 0o777, 0o755)

    def test_malformed_sqlite_report_is_bounded(self):
        self.folder.mkdir()
        self.db.write_bytes(b"invalid-sqlite-bytes")
        code, report, _ = self.doctor()
        self.assertEqual(code, 1)
        self.assertFalse(report["integrity"]["ok"])
        self.assertIn(report["integrity"]["reason"],
                      ("DatabaseError", "OperationalError", "ValueError"))
        self.assertNotIn(str(self.db), json.dumps(report))
        self.assertEqual(self.db.read_bytes(), b"invalid-sqlite-bytes")


if __name__ == "__main__":
    unittest.main()
