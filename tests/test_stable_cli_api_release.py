"""Release-gate integration of the actual local-only CLI HTTP process.

No production data, host configuration, devices or non-loopback network access.
"""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from goreecloud_changelogs.store import Store

TOKEN = "goreecloud-local-release-acceptance-" + "x" * 44


class StableCLIApiReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="goreecloud-stable-")
        cls.db = Path(cls.temp.name) / "data" / "entries.sqlite3"
        store = Store(cls.db)
        store.add("mesh", "1.0.0", "security", "Token enforcement",
                  description="Local test data only")
        store.add("mesh", "1.0.0", "fixed", "Page limit")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = dict(os.environ)
        env["GOREE_CHANGELOGS_API_TOKEN"] = TOKEN
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "goreecloud_changelogs.cli",
             "--db", str(cls.db), "serve", "--port", str(cls.port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for _ in range(100):
                if cls.process.poll() is not None:
                    raise AssertionError("CLI server exited before becoming ready")
                try:
                    status, _, body = cls.request("/health", auth=True)
                    if status == 200 and json.loads(body)["status"] == "ok":
                        break
                except (OSError, http.client.HTTPException):
                    pass
                time.sleep(0.05)
            else:
                raise AssertionError("Local CLI API did not start")
        except BaseException:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, method="GET", auth=False, token=TOKEN):
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=4)
        headers = {"Authorization": "Bearer " + token} if auth else {}
        try:
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_only_authenticated_local_reads_succeed(self):
        for path in ("/health", "/v1/entries", "/v1/releases", "/v1/summary",
                     "/v1/search?q=security"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 401)
                code, headers, body = self.request(path, auth=True)
                self.assertEqual(code, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Frame-Options"], "DENY")
                self.assertNotIn("Access-Control-Allow-Origin", headers)
                self.assertIsInstance(json.loads(body), dict)

    def test_invalid_token_cannot_read_records(self):
        code, _, body = self.request("/v1/entries", auth=True, token="bad" * 20)
        self.assertEqual(code, 401)
        self.assertNotIn(b"Token enforcement", body)

    def test_web_preview_is_not_enabled_in_stable_api_mode(self):
        self.assertEqual(self.request("/", auth=True)[0], 404)
        self.assertEqual(self.request("/ui/app.js", auth=True)[0], 404)

    def test_write_methods_all_refused_and_rows_preserved(self):
        before = Store(self.db).list(limit=100)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                code, _, body = self.request("/v1/entries", method=method, auth=True)
                self.assertEqual(code, 405)
                self.assertIn(b"Read-only API", body)
        self.assertEqual(Store(self.db).list(limit=100), before)

    def test_search_filters_and_exact_paging(self):
        code, _, body = self.request(
            "/v1/entries?product=mesh&kind=security&limit=1", auth=True)
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(len(data["entries"]), 1)
        self.assertFalse(data["has_more"])
        code, _, body = self.request("/v1/releases?limit=1", auth=True)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["has_more"])

    def test_invalid_or_too_long_query_is_bounded(self):
        self.assertEqual(self.request("/v1/entries?kind=UNKNOWN", auth=True)[0], 400)
        self.assertEqual(self.request("/v1/entries?product=" + "x" * 4100,
                                      auth=True)[0], 414)


if __name__ == "__main__":
    unittest.main()
