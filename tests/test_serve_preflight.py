"""Refused loopback listeners must not create local databases or directories."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goreecloud_changelogs.cli import main


class ServePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.db = self.base / "uncreated" / "entries.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, *args, token=""):
        with patch.dict(os.environ, {"GOREE_CHANGELOGS_API_TOKEN": token}):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = main(["--db", str(self.db), "serve", *args])
        self.assertFalse(self.db.exists())
        self.assertFalse(self.db.parent.exists())
        return result

    def test_missing_token_refused_without_storage_side_effect(self):
        self.assertEqual(self.invoke(), 1)

    def test_short_token_refused_without_storage_side_effect(self):
        self.assertEqual(self.invoke("--web", token="x" * 31), 1)

    def test_invalid_port_refused_without_storage_side_effect(self):
        self.assertEqual(self.invoke("--port", "-1", token="y" * 40), 1)
        self.assertEqual(self.invoke("--port", "65536", token="y" * 40), 1)


if __name__ == "__main__":
    unittest.main()
