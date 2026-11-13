"""Bounded loopback server concurrency and request-target regressions."""
import http.client
import socket
import tempfile
import time
import threading
import unittest
from pathlib import Path

from goreecloud_changelogs.api import BoundedHTTPServer, make_handler
from goreecloud_changelogs.store import Store

TOKEN = "bounded-server-test-" + "m" * 42


class BoundedServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "entries.sqlite3")
        self.store.add("mesh", "1", "added", "Entry")
        self.server = None
        self.thread = None

    def tearDown(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
        self.temp.cleanup()

    def start(self, handler=None, capacity=2):
        self.server = BoundedHTTPServer(("127.0.0.1", 0),
                                        handler or make_handler(self.store, TOKEN),
                                        max_connections=capacity, connection_timeout=1)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.server.server_port

    def request(self, path, token=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        try:
            headers = {"Authorization": "Bearer " + TOKEN} if token else {}
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_limit_rejects_excess_connections_without_spawning_worker(self):
        occupied = threading.Event()
        release = threading.Event()
        parent = make_handler(self.store, TOKEN)

        class Slow(parent):
            def do_GET(self):
                occupied.set()
                release.wait(5)
                super().do_GET()

        self.start(handler=Slow, capacity=1)
        first = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=4)
        first.settimeout(4)
        try:
            first.sendall(
                b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n" +
                ("Authorization: Bearer " + TOKEN + "\r\n\r\n").encode("ascii")
            )
            self.assertTrue(occupied.wait(3))
            status, body, headers = self.request("/health")
            self.assertEqual(status, 503)
            self.assertEqual(body, b"")
            self.assertEqual(headers["Cache-Control"], "no-store")
        finally:
            release.set()
            try:
                first.recv(4096)
            finally:
                first.close()
        # Let the worker release its semaphore before trying normal requests.
        for _ in range(100):
            if self.server._slots.acquire(blocking=False):
                self.server._slots.release()
                break
            time.sleep(0.01)
        else:
            self.fail("Server worker did not release its concurrency slot")
        self.assertEqual(self.request("/health")[0], 200)

    def test_long_request_target_is_refused_before_db_query(self):
        self.start()
        code, body, _ = self.request("/v1/entries?product=" + "z" * 5000)
        self.assertEqual(code, 414)
        self.assertIn(b"Request target too long", body)
        self.assertEqual(self.request("/health", token=False)[0], 401)
        self.assertEqual(self.request("/v1/releases")[0], 200)

    def test_invalid_capacity_is_refused(self):
        for value in (0, -1, 257, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    BoundedHTTPServer(("127.0.0.1", 0), make_handler(self.store, TOKEN),
                                      max_connections=value)


if __name__ == "__main__":
    unittest.main()
