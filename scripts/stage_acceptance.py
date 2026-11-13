"""Opt-in, read-only staging acceptance for a selected local Changelogs database.

No database initialization, writes, backup/restore, network exposure, API token
logging or host auto-remediation. API checks connect to loopback only.
"""
import argparse
import http.client
import json
import os
import sys
from pathlib import Path

from goreecloud_changelogs.backup import verify_backup
from goreecloud_changelogs.store import audit_permissions


def _probe(port, token, method, path, authenticated=True):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Authorization": "Bearer " + token} if authenticated else {}
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read(262145)
        if len(body) > 262144:
            raise ValueError("API response exceeds 256 KiB")
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def check(db_path, api_port=None, token=None):
    """Check an existing private SQLite database and optional local-only API."""
    selected = Path(db_path).expanduser()
    permissions = audit_permissions(selected)
    output = {"passed": False, "permissions": permissions,
              "sqlite": {"passed": False}, "api": {"checked": False}}
    try:
        verified = verify_backup(selected)
        output["sqlite"] = {"passed": True, "entries": verified["entries"]}
    except Exception as exc:
        # Do not include paths, DB bytes or potentially sensitive SQLite messages.
        output["sqlite"] = {"passed": False, "error_type": type(exc).__name__}
    if api_port is not None:
        status = {"checked": True, "passed": False}
        output["api"] = status
        if not isinstance(token, str) or len(token) < 32:
            status["error_type"] = "TokenMissingOrShort"
        else:
            try:
                unauth, _, _ = _probe(api_port, token, "GET", "/health",
                                     authenticated=False)
                health, headers, body = _probe(api_port, token, "GET", "/health")
                releases, _, _ = _probe(api_port, token, "GET", "/v1/releases?limit=1")
                entries, _, _ = _probe(api_port, token, "GET", "/v1/entries?limit=1")
                blocked, _, _ = _probe(api_port, token, "POST", "/v1/entries")
                health_ok = json.loads(body).get("status") == "ok"
                controls = (headers.get("Cache-Control") == "no-store" and
                            headers.get("X-Frame-Options") == "DENY" and
                            "Access-Control-Allow-Origin" not in headers)
                status.update({
                    "authentication_enforced": unauth == 401,
                    "read_only": blocked == 405,
                    "list_available": entries == 200,
                    "releases_available": releases == 200,
                    "security_headers": controls,
                    "health": health == 200 and health_ok,
                })
                status["passed"] = all(value for name, value in status.items()
                                       if name not in ("checked", "passed"))
            except Exception as exc:
                status["error_type"] = type(exc).__name__
    output["passed"] = (permissions["secure"] and output["sqlite"]["passed"]
                        and (api_port is None or output["api"]["passed"]))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only staged Changelogs filesystem, SQLite and optional loopback API checks"
    )
    parser.add_argument("--db", required=True, help="Existing local SQLite database (never initialized)")
    parser.add_argument("--api-port", type=int,
                        help="Optionally probe loopback API 127.0.0.1 on this port")
    parser.add_argument("--token-env", default="GOREE_CHANGELOGS_API_TOKEN",
                        help="Environment-variable name containing API token; never print it")
    args = parser.parse_args(argv)
    result = check(args.db, args.api_port, os.environ.get(args.token_env))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
