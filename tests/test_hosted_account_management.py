"""Host-only account administration and session-revocation integration tests."""
import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from goreecloud_changelogs.cli import main
from goreecloud_changelogs.hosted_auth import AuthFailed, AuthStore, MAX_UNKNOWN_FAILURE_ROWS

ADMIN_PASSWORD = "admin-secret-with-adequate-length"
READER_PASSWORD = "reader-password-secret-2026"
UPDATED_PASSWORD = "updated-password-secret-2026"


class HostedAccountManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "private"
        self.root.mkdir(mode=0o700)
        self.auth = AuthStore(self.root / "accounts.sqlite3", initialize=True)
        self.auth.bootstrap("admin", ADMIN_PASSWORD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reader_account_and_expiring_revocable_session(self):
        self.auth.add_user("reader", READER_PASSWORD, "reader")
        person = self.auth.authenticate("reader", READER_PASSWORD)
        self.assertEqual(person["role"], "reader")
        token, csrf, ttl = self.auth.issue(person["id"], "token")
        self.assertGreaterEqual(ttl, 3600)
        self.assertEqual(self.auth.resolve(token, "token")["username"], "reader")
        self.assertIsNone(self.auth.resolve(token, "web"))
        self.auth.revoke(token)
        self.assertIsNone(self.auth.resolve(token, "token"))

    def test_password_rotation_invalidates_every_session(self):
        self.auth.add_user("reader", READER_PASSWORD)
        person = self.auth.authenticate("reader", READER_PASSWORD)
        web, csrf, _ = self.auth.issue(person["id"], "web")
        token, _, _ = self.auth.issue(person["id"], "token")
        self.assertTrue(self.auth.csrf_valid(self.auth.resolve(web, "web"), csrf))
        self.auth.change_password("reader", UPDATED_PASSWORD)
        self.assertIsNone(self.auth.resolve(web, "web"))
        self.assertIsNone(self.auth.resolve(token, "token"))
        with self.assertRaises(AuthFailed):
            self.auth.authenticate("reader", READER_PASSWORD)
        self.assertEqual(self.auth.authenticate("reader", UPDATED_PASSWORD)["id"],
                         person["id"])

    def test_reader_removal_revokes_login_and_preserves_admin(self):
        self.auth.add_user("reader", READER_PASSWORD)
        reader = self.auth.authenticate("reader", READER_PASSWORD)
        token, _, _ = self.auth.issue(reader["id"], "token")
        self.auth.remove_user("reader")
        self.assertIsNone(self.auth.resolve(token, "token"))
        with self.assertRaises(AuthFailed):
            self.auth.authenticate("reader", READER_PASSWORD)
        self.assertEqual(self.auth.authenticate("admin", ADMIN_PASSWORD)["role"], "admin")
        with self.assertRaisesRegex(ValueError, "last administrator"):
            self.auth.remove_user("admin")

    def test_unsupported_roles_and_unknown_users_fail(self):
        with self.assertRaises(ValueError):
            self.auth.add_user("reader", READER_PASSWORD, "superuser")
        with self.assertRaises(ValueError):
            self.auth.change_password("absent", UPDATED_PASSWORD)
        with self.assertRaises(ValueError):
            self.auth.remove_user("absent")
        with self.assertRaises((sqlite3.DatabaseError, ValueError)):
            self.auth.add_user("admin", READER_PASSWORD, "reader")

    def test_unknown_account_lockout_storage_is_bounded_without_evicting_admin(self):
        # Faster deterministic PBKDF2 substitute for storage-shape testing;
        # production iterations and authentication are tested elsewhere.
        with patch("goreecloud_changelogs.hosted_auth.hashlib.pbkdf2_hmac",
                   return_value=bytes(32)):
            for _ in range(3):
                with self.assertRaises(AuthFailed):
                    self.auth.authenticate("admin", "incorrect-password-2026")
            for n in range(MAX_UNKNOWN_FAILURE_ROWS + 75):
                with self.assertRaises(AuthFailed):
                    self.auth.authenticate("absent-%04d" % n,
                                           "incorrect-password-2026")
        with self.auth.connect() as db:
            unknown = db.execute(
                "SELECT COUNT(*) FROM failed_logins AS f "
                "LEFT JOIN users AS u ON u.username=f.username "
                "WHERE u.id IS NULL").fetchone()[0]
            admin = db.execute(
                "SELECT failures FROM failed_logins WHERE username='admin'"
            ).fetchone()[0]
        self.assertEqual(unknown, MAX_UNKNOWN_FAILURE_ROWS)
        self.assertEqual(admin, 3)
        # Normal credentials still work, clearing that account's failures.
        self.assertEqual(self.auth.authenticate("admin", ADMIN_PASSWORD)["role"],
                         "admin")

    def test_unknown_username_repeated_failures_still_lock(self):
        with patch("goreecloud_changelogs.hosted_auth.hashlib.pbkdf2_hmac",
                   return_value=bytes(32)):
            for _ in range(6):
                with self.assertRaises(AuthFailed):
                    self.auth.authenticate("not-provisioned",
                                           "incorrect-password-2026")
        with self.auth.connect() as db:
            row = db.execute(
                "SELECT failures,locked_until FROM failed_logins "
                "WHERE username='not-provisioned'").fetchone()
        self.assertEqual(row["failures"], 5)
        self.assertGreater(row["locked_until"], 0)

    def test_cli_password_prompts_and_local_account_creation(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("getpass.getpass", side_effect=[READER_PASSWORD, READER_PASSWORD]):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = main(["host", "user-add", "--data-dir", str(self.root),
                             "--username", "reader", "--role", "reader"])
        self.assertEqual(code, 0, errors.getvalue())
        self.assertEqual(self.auth.authenticate("reader", READER_PASSWORD)["role"], "reader")
        with patch("getpass.getpass", side_effect=[UPDATED_PASSWORD, UPDATED_PASSWORD]):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                code = main(["host", "user-password", "--data-dir", str(self.root),
                             "--username", "reader"])
        self.assertEqual(code, 0, errors.getvalue())
        self.assertEqual(self.auth.authenticate("reader", UPDATED_PASSWORD)["role"], "reader")

    def test_host_user_remove_refused_noninteractive(self):
        self.auth.add_user("reader", READER_PASSWORD)
        out, err = io.StringIO(), io.StringIO()
        with patch("goreecloud_changelogs.cli.sys.stdin", io.StringIO()):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["host", "user-remove", "--data-dir", str(self.root),
                             "--username", "reader"])
        self.assertEqual(code, 1)
        self.assertIn("interactive", err.getvalue())
        self.assertEqual(self.auth.authenticate("reader", READER_PASSWORD)["role"], "reader")

    def test_web_and_android_signout_source_controls(self):
        android = (Path(__file__).resolve().parents[1] / "android-app" / "app" / "src"
                   / "main" / "java" / "com" / "goreecloud" / "changelogs"
                   / "HostedActivity.java").read_text(encoding="utf-8")
        self.assertIn('call(server, "/v1/auth/logout", priorToken, new JSONObject())', android)
        self.assertIn("++sessionGeneration", android)
        self.assertIn('token = "";', android)
        self.assertIn("server revocation unconfirmed", android)


if __name__ == "__main__":
    unittest.main()
