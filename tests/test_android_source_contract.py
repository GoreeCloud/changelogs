"""Static Android source guards for session cancellation and paged reads.

Actual native behavior requires an Android emulator or physical-device test.
"""
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "android-app" / "app" / "src" / "main" / "java" / "com" / "goreecloud" / "changelogs" / "MainActivity.java"


class AndroidSessionSourceTests(unittest.TestCase):
    def test_session_and_request_invalidation_on_clear(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("++sessionVersion;", text)
        self.assertIn("++requestVersion;", text)
        self.assertIn("startSession != sessionVersion || startRequest != requestVersion", text)
        self.assertIn('bearerToken = "";', text)
        self.assertIn("executor.shutdownNow()", text)

    def test_pagination_is_bounded_and_read_only(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"/v1/entries?limit=40&offset="', text)
        self.assertIn('"/v1/search?limit=40&offset="', text)
        self.assertIn("requestedOffset + rows.length() <= 1000000", text)
        self.assertIn("render(rows, append)", text)
        self.assertIn("loadMore.setVisibility", text)
        self.assertIn('connection.setRequestMethod("GET")', text)
        self.assertNotIn('connection.setRequestMethod("POST")', text)

    def test_session_secrets_do_not_persist_or_redirect(self):
        text = SOURCE.read_text(encoding="utf-8")
        self.assertIn("tokenInput.setSaveEnabled(false)", text)
        self.assertIn("IMPORTANT_FOR_AUTOFILL_NO", text)
        self.assertIn("setInstanceFollowRedirects(false)", text)
        self.assertNotIn("SharedPreferences", text)


if __name__ == "__main__":
    unittest.main()
