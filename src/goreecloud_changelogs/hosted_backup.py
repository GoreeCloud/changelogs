"""Host-owned SQLite changelog/account backup pair with strict verification.

Copies a consistent SQLite snapshot of each DB. Cross-database atomicity is
not guaranteed: callers must stop application writers before invoking this.
Backup account sessions are intentionally cleared so restores require login.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .backup import verify_backup
from .hosted_auth import AuthStore, ROLES
from .hosted_server import data_paths
from .store import audit_permissions

FILES = ("changelogs.sqlite3", "accounts.sqlite3", "manifest.json")
FORMAT = 1


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            block = source.read(256 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _read_only(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)


def _check_private(path, directory=False):
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("Backup path must not be a symbolic link")
    mode = candidate.stat().st_mode
    if directory:
        if not stat.S_ISDIR(mode):
            raise ValueError("Backup directory is invalid")
    elif not stat.S_ISREG(mode):
        raise ValueError("Backup file is invalid")
    if os.name == "posix" and mode & 0o077:
        raise ValueError("Backup files and directories must be owner-only")


def _verify_accounts(path):
    _check_private(path)
    with closing(_read_only(path)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Account backup failed SQLite integrity check")
        schema = {
            (row[0], row[1], row[2])
            for row in db.execute(
                "SELECT type,name,tbl_name FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        expected = {
            ("table", "users", "users"),
            ("table", "sessions", "sessions"),
            ("table", "failed_logins", "failed_logins"),
            ("index", "session_user", "sessions"),
        }
        if schema != expected:
            raise ValueError("Account backup schema is unsupported")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Account backup violates foreign-key constraints")
        users = db.execute(
            "SELECT role,salt,password_hash FROM users").fetchall()
        if not users or not any(role == "admin" for role, _, _ in users):
            raise ValueError("Account backup lacks an administrator")
        if any(role not in ROLES or len(salt) != 16 or len(password_hash) != 32
               for role, salt, password_hash in users):
            raise ValueError("Account backup contains invalid account material")
        sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        return {"users": len(users), "sessions": sessions}


def _sqlite_copy(source, target):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o600)
    os.close(fd)
    with closing(_read_only(source)) as incoming:
        with closing(sqlite3.connect(target)) as output:
            incoming.backup(output)
            output.execute("PRAGMA journal_mode=DELETE")
            output.commit()


def backup_host(directory, destination, *, offline_ack=False):
    """No-clobber backup of both DBs; offline maintenance acknowledgement required."""
    if offline_ack is not True:
        raise ValueError("Stop Changelogs writers and confirm --offline-ack first")
    data_path, account_path = data_paths(directory)
    if not audit_permissions(data_path)["secure"]:
        raise ValueError("Source changelog DB privacy audit failed")
    verify_backup(data_path)
    AuthStore(account_path)
    _verify_accounts(account_path)
    output = Path(destination).expanduser()
    if output.is_symlink() or output.exists() or output.parent.is_symlink():
        raise ValueError("Backup destination must be new, non-symlink directory")
    if not output.parent.is_dir():
        raise ValueError("Create and secure the destination parent first")
    _check_private(output.parent, directory=True)
    output.mkdir(mode=0o700, exist_ok=False)
    # On any failure, an incomplete directory remains for explicit inspection.
    # Never remove or overwrite user files as implicit cleanup.
    entries = output / FILES[0]
    accounts = output / FILES[1]
    _sqlite_copy(data_path, entries)
    _sqlite_copy(account_path, accounts)
    with closing(sqlite3.connect(accounts)) as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("DELETE FROM sessions")
        db.commit()
        db.execute("VACUUM")
        db.execute("PRAGMA journal_mode=DELETE")
        db.commit()
    counts = _verify_accounts(accounts)
    if counts["sessions"]:
        raise ValueError("Session purge failed in backup")
    data = verify_backup(entries)
    manifest = {
        "format": FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "entries": data["entries"],
        "users": counts["users"],
        "sessions_saved": 0,
        "sha256": {FILES[0]: _file_hash(entries), FILES[1]: _file_hash(accounts)},
    }
    payload = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = os.open(output / FILES[2], os.O_CREAT | os.O_EXCL | os.O_WRONLY
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
        fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    verify_host_backup(output)
    return {"created": True, "entries": manifest["entries"], "users": manifest["users"],
            "sessions_saved": 0, "sha256": manifest["sha256"]}


def verify_host_backup(directory):
    """Read-only checks of a complete, private, self-contained backup pair."""
    root = Path(directory).expanduser()
    _check_private(root, directory=True)
    if {item.name for item in root.iterdir()} != set(FILES):
        raise ValueError("Backup pair is incomplete or has unexpected files")
    for name in FILES:
        _check_private(root / name)
    file = root / FILES[2]
    if file.stat().st_size > 8192:
        raise ValueError("Backup manifest is too large")
    try:
        manifest = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid backup manifest") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "format", "created_at", "entries", "users", "sessions_saved", "sha256"
    } or manifest["format"] != FORMAT or manifest["sessions_saved"] != 0:
        raise ValueError("Unsupported backup manifest")
    hashes = manifest["sha256"]
    if not isinstance(hashes, dict) or set(hashes) != set(FILES[:2]):
        raise ValueError("Invalid backup digest manifest")
    for name in FILES[:2]:
        if hashes[name] != _file_hash(root / name):
            raise ValueError("Backup content does not match recorded SHA-256")
    counts = _verify_accounts(root / FILES[1])
    data = verify_backup(root / FILES[0])
    if (counts["sessions"] != 0 or counts["users"] != manifest["users"] or
        data["entries"] != manifest["entries"]):
        raise ValueError("Backup counts are inconsistent")
    return {"valid": True, "entries": data["entries"], "users": counts["users"],
            "sessions_saved": 0, "sha256": hashes}

def stage_host_restore(source, destination):
    """Stage a *verified* paired host backup as new private databases.

    This is a no-clobber, offline recovery rehearsal; it never modifies a
    running server or installs a service. On failure, the incomplete *new*
    directory is retained for explicit inspection.
    """
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    verified = verify_host_backup(source)
    if destination.is_symlink() or destination.exists() or destination.parent.is_symlink():
        raise ValueError("Staging destination must be a new, non-symlink directory")
    if not destination.parent.is_dir():
        raise ValueError("Create the staging parent first")
    _check_private(destination.parent, directory=True)
    source_real = source.resolve()
    target_real = destination.resolve(strict=False)
    if (source_real == target_real or source_real in target_real.parents
            or target_real in source_real.parents):
        raise ValueError("Staging directory must not overlap its backup source")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    destination.mkdir(mode=0o700, exist_ok=False)
    for name in FILES[:2]:
        # Create each file exclusively: do not follow a racing symlink,
        # invoke maintainer code, or overwrite an existing user database.
        target = destination / name
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as output:
            with open(source / name, "rb") as incoming:
                shutil.copyfileobj(incoming, output, length=256 * 1024)
            output.flush()
            os.fsync(output.fileno())
        if _file_hash(target) != manifest["sha256"][name]:
            raise ValueError("Copied recovery database failed SHA-256 readback")
    if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
        fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    from .hosted_diagnostics import diagnose_host
    report = diagnose_host(destination)
    if (not report["healthy"]
            or report["changelogs"]["entries"] != verified["entries"]
            or report["accounts"]["users"] != verified["users"]
            or report["accounts"]["active_session_hashes"] != 0):
        raise ValueError("Staged recovery failed independent host health checks")
    return {"staged": True, "entries": verified["entries"],
            "users": verified["users"], "sessions_saved": 0,
            "deployed": False}
