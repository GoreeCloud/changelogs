"""Reject foreign SQLite objects and corrupt changelog metadata before restore."""
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.backup import backup, verify_backup, restore
from goreecloud_changelogs.store import Store


class BackupSchemaSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "live.sqlite3"
        self.store = Store(self.db)
        self.store.add("mesh", "1", "added", "Original")
        self.source = self.root / "backup.sqlite3"
        backup(self.store, self.source)

    def tearDown(self):
        self.temp.cleanup()

    def contaminated(self, name, script):
        path = self.root / (name + ".sqlite3")
        shutil.copyfile(self.source, path)
        with sqlite3.connect(path) as db:
            db.executescript(script)
        return path

    def assert_rejected_without_live_change(self, source):
        with self.assertRaises(ValueError):
            verify_backup(source)
        with self.assertRaises(ValueError):
            restore(self.store, source)
        self.assertEqual(verify_backup(self.source)["entries"], 1)
        self.assertEqual([entry["title"] for entry in self.store.list()], ["Original"])

    def test_canonical_backup_still_accepted(self):
        self.assertEqual(verify_backup(self.source)["entries"], 1)

    def test_reject_trigger_even_if_sqlite_integrity_is_ok(self):
        suspicious = self.contaminated("trigger", """
            CREATE TRIGGER unwanted AFTER INSERT ON entries BEGIN
                DELETE FROM entries WHERE id = NEW.id;
            END;
        """)
        self.assert_rejected_without_live_change(suspicious)

    def test_reject_extra_table_and_view(self):
        self.assert_rejected_without_live_change(
            self.contaminated("table", "CREATE TABLE unrelated (value TEXT);")
        )
        self.assert_rejected_without_live_change(
            self.contaminated("view", "CREATE VIEW leak AS SELECT * FROM entries;")
        )

    def test_reject_wrong_index_columns(self):
        self.assert_rejected_without_live_change(
            self.contaminated("index", """
                DROP INDEX entries_product_version;
                CREATE INDEX entries_product_version ON entries(kind);
            """)
        )

    def test_reject_invalid_kind_or_json_metadata(self):
        self.assert_rejected_without_live_change(
            self.contaminated("kind", "UPDATE entries SET kind='unexpected';")
        )
        self.assert_rejected_without_live_change(
            self.contaminated("metadata", "UPDATE entries SET metadata='[1,2]';")
        )
        self.assert_rejected_without_live_change(
            self.contaminated("nan", "UPDATE entries SET metadata='{\"bad\": NaN}';")
        )


if __name__ == "__main__":
    unittest.main()
