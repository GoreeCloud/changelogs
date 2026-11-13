"""Complete exports, explicit chunking, portable JSON limits and no-clobber files."""
import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.importer import read_import
from goreecloud_changelogs.store import Store


class ExportSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "entries.sqlite3"
        self.store = Store(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", str(self.db), "export", *arguments])
        return code, out.getvalue(), err.getvalue()

    def bulk_insert(self, count, size=0):
        with self.store.connect() as db:
            records = [
                (f"product-{i % 3}", f"1.{i}", "added", f"Change {i}", "z" * size,
                 "", "2026-01-01", "{}", "2026-01-01", "2026-01-01")
                for i in range(count)
            ]
            db.executemany(
                """INSERT INTO entries
                   (product,version,kind,title,description,author,released_at,
                    metadata,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""", records
            )

    def test_default_json_exports_all_without_silent_truncation(self):
        self.bulk_insert(115)
        code, output, error = self.invoke("--format", "json")
        self.assertEqual((code, error), (0, ""))
        data = json.loads(output)
        self.assertEqual(len(data), 115)
        path = self.root / "export.json"
        path.write_text(output, encoding="utf-8")
        records, _ = read_import(path)
        self.assertEqual(len(records), 115)

    def test_default_rejects_more_than_import_cap_with_no_stdout(self):
        self.bulk_insert(5001)
        code, output, error = self.invoke("--format", "json")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("silently truncate", error)
        for offset, expected in ((0, 3000), (3000, 2001)):
            code, output, error = self.invoke(
                "--format", "json", "--limit", "3000", "--offset", str(offset)
            )
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(len(json.loads(output)), expected)

    def test_oversized_json_rejected_without_output_or_destination(self):
        self.bulk_insert(280, size=32768)
        destination = self.root / "private" / "large.json"
        code, output, error = self.invoke("--format", "json", "--output", str(destination))
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("8 MiB", error)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.parent.exists())

    def test_export_refuses_portably_invalid_existing_rows(self):
        self.store.add("mesh", "1", "added", "Valid")
        with self.store.connect() as db:
            db.execute("UPDATE entries SET kind = 'not-importable'")
        code, output, error = self.invoke("--format", "json")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("cannot be imported", error)

    def test_explicit_chunking_and_filters(self):
        self.bulk_insert(7)
        a = json.loads(self.invoke("--format", "json", "--limit", "3")[1])
        b = json.loads(self.invoke("--format", "json", "--limit", "3", "--offset", "3")[1])
        c = json.loads(self.invoke("--format", "json", "--limit", "3", "--offset", "6")[1])
        self.assertEqual(len({r["id"] for r in a+b+c}), 7)
        self.assertEqual(len(json.loads(
            self.invoke("--format", "json", "--product", "product-2")[1]
        )), 2)

    def test_atomic_no_clobber_output_and_file_mode(self):
        self.store.add("mesh", "1", "added", "Safe export")
        dest = self.root / "secure" / "portable.json"
        code, output, error = self.invoke("--format", "json", "--output", str(dest))
        self.assertEqual((code, output, error), (0, "", ""))
        self.assertEqual(json.loads(dest.read_text(encoding="utf-8"))[0]["title"],
                         "Safe export")
        self.assertEqual(list(dest.parent.glob(".portable.json.partial-*")), [])
        if os.name == "posix":
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            self.assertEqual(dest.parent.stat().st_mode & 0o777, 0o700)
        before = dest.read_bytes()
        code, output, error = self.invoke("--format", "json", "--output", str(dest))
        self.assertEqual(code, 1)
        self.assertEqual(dest.read_bytes(), before)
        self.assertIn("never overwritten", error)

    def test_rejects_offset_without_limit(self):
        self.store.add("mesh", "1", "added", "One")
        code, output, error = self.invoke("--offset", "1")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("requires an explicit", error)

    def test_markdown_escapes_untrusted_html_and_heading(self):
        self.store.add("mesh", "1", "added", "<img src=x onerror=alert(1)>",
                       description="# dangerous")
        code, output, error = self.invoke()
        self.assertEqual((code, error), (0, ""))
        self.assertNotIn("<img", output)
        self.assertNotIn("\n# dangerous", output)


if __name__ == "__main__":
    unittest.main()
