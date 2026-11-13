"""Read-only self-hosted preflight for both private databases.

Avoids Store() initialization and any schema migration, chmod or correction.
Reports sanitized outcomes rather than private names, paths or exception text.
"""
from __future__ import annotations

from .backup import verify_backup
from .hosted_auth import AuthStore
from .hosted_backup import _verify_accounts
from .hosted_server import data_paths
from .store import audit_permissions


def diagnose_host(data_dir):
    report = {
        "healthy": False,
        "changelogs": {"ok": False},
        "accounts": {"ok": False},
        "permissions": {"ok": False},
    }
    try:
        records, credentials = data_paths(data_dir)
    except (ValueError, OSError, TypeError) as error:
        report["permissions"]["error_type"] = type(error).__name__
        return report
    try:
        result = audit_permissions(records)
        report["permissions"]["ok"] = result["secure"]
        report["permissions"]["findings"] = result["findings"]
    except (ValueError, OSError, TypeError) as error:
        report["permissions"]["error_type"] = type(error).__name__
    try:
        info = verify_backup(records)
        report["changelogs"] = {"ok": True, "entries": info["entries"]}
    except Exception as error:
        report["changelogs"] = {"ok": False, "error_type": type(error).__name__}
    try:
        AuthStore(credentials)
        info = _verify_accounts(credentials)
        report["accounts"] = {
            "ok": True,
            "users": info["users"],
            "active_session_hashes": info["sessions"],
        }
    except Exception as error:
        report["accounts"] = {"ok": False, "error_type": type(error).__name__}
    report["healthy"] = all(report[key]["ok"] for key in
                            ("changelogs", "accounts", "permissions"))
    return report
