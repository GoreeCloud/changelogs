"""Bounded, atomic and idempotent JSON import across local CLI databases."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.importer import read_import
from goreecloud_changelogs.store import Store


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "source.sqlite3"
        self.target = self.root / "destination.sqlite3"
        self.source = Store(self.db)
        self.source.add("mesh", "1.0", "added", "Initial sync",
                        metadata={"nested": {"a": 1, "b": 2}},
                        description="Local-only data")
        self.source.add("vpn", "2.0", "fixed", "Fixed failover",
                        author="GoreeCloud")
        self.export = self.root / "export.json"
        self.export.write_text(json.dumps(self.source.list()), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, *args, db=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--db", str(db or self.target), "import", str(self.export), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_preview_does_not_initialize_database_or_dirs(self):
        missing_db = self.root / "not-created" / "no.sqlite3"
        result, output, _ = self.command(db=missing_db)
        self.assertEqual(result, 0)
        info = json.loads(output)
        self.assertTrue(info["dry_run"])
        self.assertEqual(info["validated"], 2)
        self.assertEqual(len(info["sha256"]), 64)
        self.assertFalse(missing_db.parent.exists())

    def test_roundtrip_preserves_fields_and_idempotency(self):
        self.assertEqual(self.command("--yes")[0], 0)
        target = Store(self.target)
        self.assertEqual(len(target.list()), 2)
        old = sorted(self.source.list(), key=lambda x: x["title"])
        new = sorted(target.list(), key=lambda x: x["title"])
        for original, restored in zip(old, new):
            for key in ("product", "version", "kind", "title", "description",
                        "author", "released_at", "created_at", "updated_at", "metadata"):
                self.assertEqual(original[key], restored[key])
        code, output, _ = self.command("--yes")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["inserted"], 0)
        self.assertEqual(json.loads(output)["skipped_existing"], 2)
        self.assertEqual(len(target.list()), 2)

    def test_metadata_key_order_is_not_a_duplicate(self):
        Store(self.target).add("mesh", "1.0", "added", "Initial sync",
                               metadata={"nested": {"b": 2, "a": 1}},
                               description="Local-only data",
                               released_at=self.source.list(product="mesh")[0]["released_at"])
        code, output, _ = self.command("--yes")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["skipped_existing"], 1)
        self.assertEqual(len(Store(self.target).list()), 2)

    def test_invalid_row_does_not_partially_write(self):
        entries = json.loads(self.export.read_text())
        entries[1]["kind"] = "invalid-kind"
        self.export.write_text(json.dumps(entries), encoding="utf-8")
        code, _, error = self.command("--yes")
        self.assertEqual(code, 1)
        self.assertIn("Invalid entry at index 1", error)
        self.assertFalse(self.target.exists())

    def test_duplicate_source_entries_refused(self):
        entries = json.loads(self.export.read_text())
        entries.append(dict(entries[0], id=9999))
        self.export.write_text(json.dumps(entries), encoding="utf-8")
        code, _, error = self.command("--yes")
        self.assertEqual(code, 1)
        self.assertIn("Duplicate source entry", error)
        self.assertFalse(self.target.exists())

    def test_requires_yes_to_write(self):
        self.assertEqual(self.command()[0], 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.command("--dry-run")[0], 0)

    def test_rejects_duplicate_keys_and_nonfinite_json(self):
        self.export.write_text('[{"product":"x","product":"y"}]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
            read_import(self.export)
        self.export.write_text('[NaN]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            read_import(self.export)

    def test_rejects_nonregular_symlink_and_oversized_sources(self):
        if hasattr(os, "symlink"):
            alias = self.root / "alias.json"
            alias.symlink_to(self.export)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                read_import(alias)
        self.export.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            read_import(self.export)

    def test_valid_import_does_not_overwrite_existing_data(self):
        store = Store(self.target)
        store.add("gateway", "7.0", "security", "Preserve me")
        code, output, _ = self.command("--yes")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["inserted"], 2)
        self.assertEqual(len(store.list()), 3)


if __name__ == "__main__":
    unittest.main()
