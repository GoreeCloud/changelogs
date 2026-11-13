"""Malformed/unconfirmed CLI mutations must not initialize a missing DB."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.store import Store


class MutationPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "not-created" / "data.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *parts):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = main(["--db", str(self.db), *parts])
        return result, out.getvalue(), err.getvalue()

    def assert_no_initialization(self):
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())

    def test_invalid_add_metadata_refuses_before_store(self):
        code, output, error = self.invoke(
            "add", "mesh", "1", "added", "Name", "--metadata", '{"x":NaN}'
        )
        self.assertEqual(code, 1)
        self.assertIn("Error:", error)
        self.assert_no_initialization()

    def test_invalid_add_product_or_date_refuses_before_store(self):
        for args in (
            ("add", "   ", "1", "added", "Name"),
            ("add", "mesh", "1", "added", "Name", "--date", "not-a-date"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args)[0], 1)
                self.assert_no_initialization()

    def test_empty_or_invalid_edit_fields_refuse_before_store(self):
        for args in (
            ("edit", "7"),
            ("edit", "7", "--title", " "),
            ("edit", "7", "--metadata", '{"x":Infinity}'),
            ("edit", "7", "--date", "invalid"),
        ):
            with self.subTest(args=args):
                code, _, error = self.invoke(*args)
                self.assertEqual(code, 1)
                self.assertIn("Error:", error)
                self.assert_no_initialization()

    def test_noninteractive_delete_refused_without_storage(self):
        with patch("goreecloud_changelogs.cli.sys.stdin", io.StringIO()):
            code, _, error = self.invoke("delete", "7")
        self.assertEqual(code, 1)
        self.assertIn("noninteractive deletion", error)
        self.assert_no_initialization()

    def test_interactive_cancel_does_not_create_storage(self):
        class DummyTTY:
            def isatty(self):
                return True
        with patch("goreecloud_changelogs.cli.sys.stdin", DummyTTY()):
            with patch("builtins.input", return_value="no"):
                code, output, _ = self.invoke("delete", "7")
        self.assertEqual(code, 1)
        self.assertIn("Cancelled", output)
        self.assert_no_initialization()

    def test_confirmed_add_edit_and_delete_work(self):
        code, out, err = self.invoke(
            "add", "mesh", "1", "added", "Initial",
            "--metadata", '{"info":{"safe":true}}'
        )
        self.assertEqual((code, err), (0, ""))
        entry_id = int(out)
        self.assertTrue(self.db.exists())
        store = Store(self.db)
        self.assertEqual(store.get(entry_id)["metadata"], {"info": {"safe": True}})
        code, out, _ = self.invoke("edit", str(entry_id), "--title", "Updated")
        self.assertEqual(code, 0)
        self.assertEqual(store.get(entry_id)["title"], "Updated")
        code, out, _ = self.invoke("delete", str(entry_id), "--yes")
        self.assertEqual(code, 0)
        self.assertIsNone(store.get(entry_id))


if __name__ == "__main__":
    unittest.main()
