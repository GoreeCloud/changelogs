import tempfile
import os
import unittest
from pathlib import Path
from goreecloud_changelogs.store import Store, audit_permissions
from goreecloud_changelogs.cli import markdown, main

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lifecycle(self):
        eid = self.store.add("mesh", "1.0.0", "added", "Sync", metadata={"issue": 4})
        self.assertEqual(self.store.get(eid)["metadata"], {"issue": 4})
        self.assertEqual(len(self.store.list(product="mesh")), 1)
        self.assertTrue(self.store.update(eid, title="Secure sync"))
        self.assertEqual(self.store.get(eid)["title"], "Secure sync")
        self.assertIn("Secure sync", markdown(self.store.list()))
        self.assertTrue(self.store.delete(eid))
        self.assertIsNone(self.store.get(eid))

    def test_owner_only_new_database_and_existing_mode_preserved(self):
        if os.name != "posix":
            self.skipTest("POSIX permission bits")
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        os.chmod(self.db, 0o640)
        Store(self.db)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o640)

    def test_read_only_permission_audit(self):
        if os.name != "posix":
            self.skipTest("POSIX permission bits")
        directory = self.db.parent
        os.chmod(directory, 0o700)
        self.assertTrue(audit_permissions(self.db)["secure"])
        os.chmod(self.db, 0o644)
        result = audit_permissions(self.db)
        self.assertFalse(result["secure"])
        self.assertTrue(any("database:" in item for item in result["findings"]))
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o644)
        os.chmod(self.db, 0o600)
        os.chmod(directory, 0o755)
        self.assertFalse(audit_permissions(self.db)["secure"])
        missing = directory / "never-created.sqlite3"
        self.assertEqual(main(["--db", str(missing), "audit-permissions"]), 1)
        self.assertFalse(missing.exists())

    def test_invalid(self):
        with self.assertRaises(ValueError):
            self.store.add("mesh", "1", "unknown", "x")
        with self.assertRaises(ValueError):
            self.store.update(999, title="")
        with self.assertRaises(ValueError):
            self.store.list(limit=-1)

    def test_cli_noninteractive_delete_refused(self):
        self.assertEqual(main(["--db", str(self.db), "delete", "1"]), 1)

if __name__ == "__main__":
    unittest.main()
