"""Strict portable metadata and SHA-pinned imports avoid silent corruption."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.importer import read_import
from goreecloud_changelogs.metadata import parse_metadata, encode_metadata
from goreecloud_changelogs.store import Store


class StrictMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "existing.sqlite3"
        self.store = Store(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args, db=None):
        out, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
            result = main(["--db", str(db or self.db), *args])
        return result, out.getvalue(), error.getvalue()

    def test_duplicate_nested_keys_and_nonfinite_are_rejected(self):
        for metadata in ('{"x": 1, "x": 2}', '{"nested": {"a": 1, "a": 2}}',
                         '{"x": NaN}', '{"x": Infinity}', '[1,2]'):
            with self.subTest(metadata=metadata):
                code, _, error = self.invoke("add", "mesh", "1", "added", "Title",
                                             "--metadata", metadata)
                self.assertEqual(code, 1)
                self.assertIn("Error:", error)
                self.assertEqual(self.store.list(), [])

    def test_valid_nested_json_roundtrip(self):
        code, out, _ = self.invoke("add", "mesh", "1", "added", "Title",
                                   "--metadata", '{"z": [true, null], "a": {"b": 7}}')
        self.assertEqual(code, 0)
        self.assertEqual(self.store.get(int(out))["metadata"],
                         {"a": {"b": 7}, "z": [True, None]})

    def test_invalid_edit_keeps_original_metadata(self):
        entry_id = self.store.add("mesh", "1", "added", "Entry", metadata={"safe": True})
        code, _, _ = self.invoke("edit", str(entry_id), "--metadata", '{"x": -Infinity}')
        self.assertEqual(code, 1)
        self.assertEqual(self.store.get(entry_id)["metadata"], {"safe": True})

    def test_direct_store_rejects_nonfinite_and_oversized(self):
        for metadata in ({"nan": float("nan")}, {"inf": float("inf")},
                         {"large": "x" * 66000}, {"bad": object()}):
            with self.subTest(metadata=repr(metadata)[:60]):
                with self.assertRaises(ValueError):
                    self.store.add("mesh", "1", "added", "Entry", metadata=metadata)
                self.assertEqual(len(self.store.list()), 0)

    def test_sha256_pin_detects_changed_source_pre_init(self):
        self.store.add("mesh", "1", "added", "Source")
        path = self.root / "records.json"
        path.write_text(json.dumps(self.store.list()), encoding="utf-8")
        _, digest = read_import(path)
        destination = self.root / "not-created" / "new.sqlite3"
        code, output, error = self.invoke("import", str(path), "--yes",
                                          "--expect-sha256", digest, db=destination)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["inserted"], 1)
        self.assertEqual(error, "")
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        new_destination = self.root / "never-created" / "db.sqlite3"
        code, _, error = self.invoke("import", str(path), "--yes", "--expect-sha256",
                                     digest, db=new_destination)
        self.assertEqual(code, 1)
        self.assertIn("differs from expected", error)
        self.assertFalse(new_destination.parent.exists())
        self.assertFalse(new_destination.exists())

    def test_invalid_sha256_pin_and_valid_new_source(self):
        self.store.add("mesh", "1", "added", "Source")
        path = self.root / "records.json"
        path.write_text(json.dumps(self.store.list()), encoding="utf-8")
        destination = self.root / "never-created" / "db.sqlite3"
        code, _, error = self.invoke("import", str(path), "--yes",
                                     "--expect-sha256", "not-a-hash", db=destination)
        self.assertEqual(code, 1)
        self.assertIn("64 hexadecimal", error)
        self.assertFalse(destination.parent.exists())

    def test_encode_metadata_is_canonical_and_bounded(self):
        self.assertEqual(encode_metadata({"z": 1, "a": 2}), '{"a":2,"z":1}')
        self.assertEqual(parse_metadata('{"x":"y"}'), {"x": "y"})


if __name__ == "__main__":
    unittest.main()
