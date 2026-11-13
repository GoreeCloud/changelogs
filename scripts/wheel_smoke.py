"""Smoke checks that operate on the INSTALLED wheel outside the source tree.

Run from a temporary directory in GitHub Actions, after building/installing the
wheel. Never imports from source or modifies a real user's database.
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

import goreecloud_changelogs
from goreecloud_changelogs.api import make_handler
from goreecloud_changelogs.store import Store

TOKEN = "wheel-smoke-token-" + "z" * 48


def check():
    checkout = os.environ.get("GITHUB_WORKSPACE")
    location = Path(goreecloud_changelogs.__file__).resolve()
    if checkout and location.is_relative_to(Path(checkout).resolve()):
        raise AssertionError("Imported package from source tree, not the installed wheel")
    for asset in ("index.html", "app.css", "app.js"):
        path = files("goreecloud_changelogs").joinpath("web", asset)
        assert path.is_file(), f"Missing bundled asset: {asset}"
        assert path.read_bytes(), f"Empty bundled asset: {asset}"

    with tempfile.TemporaryDirectory(prefix="goree-changelogs-wheel-") as tmp:
        root = Path(tmp)
        db = root / "library" / "changelog.sqlite3"

        def cli(*args):
            process = subprocess.run(
                ["goree-changelogs", "--db", str(db), *args],
                cwd=root, text=True, capture_output=True, check=True, timeout=20
            )
            return process.stdout.strip()

        entry = cli("add", "mesh", "1.0", "added", "Wheel installation",
                    "--description", "Offline smoke test")
        assert entry.isdecimal()
        assert len(json.loads(cli("list", "--product", "mesh"))) == 1
        assert json.loads(cli("releases", "--product", "mesh"))[0]["version"] == "1.0"
        assert "Wheel installation" in cli("release-notes", "mesh", "1.0")
        assert json.loads(cli("doctor"))["healthy"]

        payload = cli("export", "--format", "json")
        import_file = root / "portable.json"
        import_file.write_text(payload, encoding="utf-8")
        target = root / "imported" / "new.sqlite3"
        result = subprocess.run(
            ["goree-changelogs", "--db", str(target), "import", str(import_file), "--yes"],
            cwd=root, capture_output=True, text=True, timeout=20, check=True
        )
        assert json.loads(result.stdout)["inserted"] == 1

        # Validate assets and protected release API from the installed package.
        server = ThreadingHTTPServer(("127.0.0.1", 0),
                                     make_handler(Store(db), TOKEN, web=True))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def request(route, token=""):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=4
                )
                headers = {"Authorization": "Bearer " + token} if token else {}
                try:
                    connection.request("GET", route, headers=headers)
                    response = connection.getresponse()
                    return response.status, response.read()
                finally:
                    connection.close()
            assert request("/")[0] == 200
            assert request("/v1/releases")[0] == 401
            code, body = request("/v1/releases?product=mesh", TOKEN)
            assert code == 200
            assert json.loads(body)["releases"][0]["version"] == "1.0"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("Installed wheel CLI, JSON import, release API and web assets: PASS")


if __name__ == "__main__":
    check()
