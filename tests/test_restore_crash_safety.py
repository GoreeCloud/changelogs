"""Crash/exception injection on disposable SQLite restore databases.

Exercises the same `restore` function used by CLI, with small page steps so
the process can be interrupted during an incomplete SQLite backup transaction.
Never use production files in this suite.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from goreecloud_changelogs.backup import backup, restore, verify_backup
from goreecloud_changelogs.store import Store


class RestoreCrashSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.live = self.root / "live.sqlite3"
        self.snapshot = self.root / "snapshot.sqlite3"
        self.recovery = self.root / "recovery.sqlite3"
        self.store = Store(self.live)
        self.store.add("mesh", "1.0", "added", "Original live entry")
        upstream = Store(self.root / "incoming.sqlite3")
        # Many pages guarantee a partially copied transaction before the fault.
        for index in range(260):
            upstream.add("mesh", f"2.{index}", "fixed", f"Imported {index}",
                         description="x" * 2800)
        backup(upstream, self.snapshot)
        self.assertEqual(verify_backup(self.snapshot)["entries"], 260)

    def tearDown(self):
        self.temp.cleanup()

    def assert_live_intact(self):
        self.assertEqual(verify_backup(self.live)["entries"], 1)
        self.assertEqual(self.store.list()[0]["title"], "Original live entry")
        self.assertEqual(verify_backup(self.snapshot)["entries"], 260)

    def test_exception_during_restore_rolls_back_destination(self):
        def injected_failure(status, remaining, total):
            if remaining > 0:
                raise RuntimeError("Injected failure after partial page copy")
        with self.assertRaisesRegex(RuntimeError, "Injected failure"):
            restore(self.store, self.snapshot, page_batch=1, progress=injected_failure)
        self.assert_live_intact()

    def test_abrupt_child_exit_preserves_live_or_recoverable_snapshot(self):
        backup(self.store, self.recovery)
        script = """
import os
import sys
from goreecloud_changelogs.backup import restore
from goreecloud_changelogs.store import Store
def interrupt(status, remaining, total):
    if remaining > 0:
        os._exit(79)
restore(Store(sys.argv[1]), sys.argv[2], page_batch=1, progress=interrupt)
sys.exit(12)
"""
        process = subprocess.run(
            [sys.executable, "-c", script, str(self.live), str(self.snapshot)],
            capture_output=True, timeout=20, check=False
        )
        self.assertEqual(process.returncode, 79, process.stderr.decode(errors="replace"))
        # Open after the child exits to let SQLite perform journal recovery.
        self.assert_live_intact()
        self.assertEqual(verify_backup(self.recovery)["entries"], 1)
        restore(self.store, self.recovery)
        self.assert_live_intact()

    def test_invalid_page_batches_are_refused_without_mutation(self):
        for invalid in (0, -2, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    restore(self.store, self.snapshot, page_batch=invalid)
                self.assert_live_intact()


if __name__ == "__main__":
    unittest.main()
