"""Self-hosted local-account authentication for Changelogs.

Persistent account/session store stays separate from the changelog SQLite
database so the existing v1.0.0 backup schema remains compatible. Account
creation is local-operator-only; never provide a public registration endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ROLES = frozenset(("admin", "reader"))
ITERATIONS = 600_000
SESSION_TTL = 12 * 3600
COOKIE = "__Host-gc_changelogs_session"
MAX_FAILED = 5
LOCKOUT_SECONDS = 120
MAX_UNKNOWN_FAILURE_ROWS = 256


class AuthFailed(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _password_bytes(value):
    if not isinstance(value, str):
        raise ValueError("Password must be text")
    raw = value.encode("utf-8")
    if not 14 <= len(raw) <= 1024 or not value.strip():
        raise ValueError("Password must be 14 to 1024 UTF-8 bytes")
    return raw


class AuthStore:
    def __init__(self, path, *, initialize=False):
        self.path = Path(path).expanduser()
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise ValueError("Account database cannot be a symbolic link")
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = None
            try:
                fd = os.open(self.path,
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                if not self.path.is_file() or self.path.is_symlink():
                    raise ValueError("Account database must be a regular file")
            finally:
                if fd is not None:
                    os.close(fd)
        elif not self.path.is_file():
            raise ValueError("Initialize a self-hosted account before starting the server")
        if os.name == "posix":
            if self.path.stat().st_mode & 0o077:
                raise ValueError("Account database must not permit group/other access")
            if self.path.parent.stat().st_mode & 0o077:
                raise ValueError("Account directory must not permit group/other access")
        with closing(self.connect()) as db:
            if initialize:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS users(
                      id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                      salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                      role TEXT NOT NULL, created_at INTEGER NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sessions(
                      token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                      csrf_hash TEXT NOT NULL, kind TEXT NOT NULL,
                      expires_at INTEGER NOT NULL,
                      FOREIGN KEY(user_id) REFERENCES users(id)
                    );
                    CREATE INDEX IF NOT EXISTS session_user ON sessions(user_id);
                    CREATE TABLE IF NOT EXISTS failed_logins(
                      username TEXT PRIMARY KEY,
                      failures INTEGER NOT NULL, locked_until INTEGER NOT NULL
                    );
                """)
            else:
                required = {"users", "sessions", "failed_logins"}
                present = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )}
                if not required.issubset(present):
                    raise ValueError("Account database schema is incomplete")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def bootstrap(self, username, password):
        """Exactly one first account, administrator, created locally."""
        user = self.validate_username(username)
        raw = _password_bytes(password)
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", raw, salt, ITERATIONS)
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise ValueError("Initial administrator already exists")
            db.execute("INSERT INTO users(username,salt,password_hash,role,created_at)"
                       " VALUES(?,?,?,?,?)", (user, salt, digest, "admin", int(time.time())))
            db.commit()

    def add_user(self, username, password, role="reader"):
        """Local-only user provisioning; never exposed as a public endpoint."""
        if role not in ROLES:
            raise ValueError("Invalid account role")
        user = self.validate_username(username)
        raw = _password_bytes(password)
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", raw, salt, ITERATIONS)
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ValueError("Bootstrap the first administrator before adding accounts")
            db.execute("INSERT INTO users(username,salt,password_hash,role,created_at)"
                       " VALUES(?,?,?,?,?)", (user, salt, digest, role, int(time.time())))
            db.commit()

    def change_password(self, username, password):
        """Rotate a local password and revoke all existing login sessions."""
        user = self.validate_username(username)
        raw = _password_bytes(password)
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", raw, salt, ITERATIONS)
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute("SELECT id FROM users WHERE username=?", (user,)).fetchone()
            if record is None:
                raise ValueError("Account not found")
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?",
                       (salt, digest, record["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (record["id"],))
            db.execute("DELETE FROM failed_logins WHERE username=?", (user,))
            db.commit()

    def remove_user(self, username):
        """Remove a user and revoke their sessions; preserve last administrator."""
        user = self.validate_username(username)
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            record = db.execute(
                "SELECT id,role FROM users WHERE username=?", (user,)).fetchone()
            if record is None:
                raise ValueError("Account not found")
            if record["role"] == "admin" and db.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] <= 1:
                raise ValueError("Cannot remove the last administrator")
            db.execute("DELETE FROM sessions WHERE user_id=?", (record["id"],))
            db.execute("DELETE FROM failed_logins WHERE username=?", (user,))
            db.execute("DELETE FROM users WHERE id=?", (record["id"],))
            db.commit()

    @staticmethod
    def validate_username(username):
        if not isinstance(username, str) or not USERNAME.fullmatch(username.lower()):
            raise ValueError("Username must be 3-64 ASCII letters/digits/._-")
        return username.lower()

    def authenticate(self, username, password):
        """Rate-limited verification, generic errors, persistent lockout."""
        user = self.validate_username(username)
        try:
            raw = _password_bytes(password)
        except ValueError as exc:
            raise AuthFailed("Invalid credentials") from exc
        now = int(time.time())
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute(
                "SELECT failures,locked_until FROM failed_logins WHERE username=?",
                (user,)).fetchone()
            if attempt and attempt["locked_until"] > now:
                raise AuthFailed("Invalid credentials")
            row = db.execute("SELECT * FROM users WHERE username=?", (user,)).fetchone()
            salt = row["salt"] if row else b"\0" * 16
            expected = row["password_hash"] if row else b"\0" * 32
            observed = hashlib.pbkdf2_hmac("sha256", raw, salt, ITERATIONS)
            if row is None or not hmac.compare_digest(observed, expected):
                failures = (attempt["failures"] if attempt else 0) + 1
                locked = now + LOCKOUT_SECONDS if failures >= MAX_FAILED else 0
                db.execute(
                    "INSERT INTO failed_logins(username,failures,locked_until)"
                    " VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET"
                    " failures=excluded.failures,locked_until=excluded.locked_until",
                    (user, failures, locked))
                if row is None:
                    # Limit persistent records for never-provisioned identities.
                    # Existing account lockouts are never evicted by this bound.
                    # No client IP addresses or request details are stored.
                    db.execute(
                        "DELETE FROM failed_logins WHERE username IN ("
                        "SELECT f.username FROM failed_logins AS f "
                        "LEFT JOIN users AS u ON u.username=f.username "
                        "WHERE u.id IS NULL ORDER BY f.rowid DESC "
                        "LIMIT -1 OFFSET ?)",
                        (MAX_UNKNOWN_FAILURE_ROWS,),
                    )
                db.commit()
                raise AuthFailed("Invalid credentials")
            db.execute("DELETE FROM failed_logins WHERE username=?", (user,))
            db.commit()
            return {"id": row["id"], "username": row["username"], "role": row["role"]}

    def issue(self, user_id, kind):
        if kind not in ("web", "token"):
            raise ValueError("Invalid session kind")
        token = secrets.token_urlsafe(48)
        csrf = self.csrf_for(token)
        expires = int(time.time()) + SESSION_TTL
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            # Keep no more than 10 active credentials per account and kind.
            db.execute(
                "DELETE FROM sessions WHERE token_hash IN "
                "(SELECT token_hash FROM sessions WHERE user_id=? AND kind=? "
                "ORDER BY expires_at DESC, rowid DESC LIMIT -1 OFFSET 9)",
                (user_id, kind))
            db.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_hash,kind,expires_at)"
                " VALUES(?,?,?,?,?)", (_digest(token), user_id, _digest(csrf), kind, expires))
            db.commit()
        return token, csrf, SESSION_TTL

    def resolve(self, token, kind):
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or (
            not token.isascii()
        ) or kind not in ("web", "token"):
            return None
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT users.username, users.role, users.id, "
                "sessions.csrf_hash FROM sessions JOIN users ON "
                "sessions.user_id=users.id WHERE sessions.token_hash=? AND "
                "sessions.kind=? AND sessions.expires_at>?",
                (_digest(token), kind, int(time.time()))).fetchone()
            return dict(row) if row is not None else None

    @staticmethod
    def csrf_for(token):
        # Stable only for one high-entropy HttpOnly session token; never expose
        # the session token itself to client-side JavaScript.
        return hashlib.sha256(("gc-changelogs-csrf:" + token).encode("ascii")).hexdigest()

    def csrf_valid(self, session, value):
        return isinstance(value, str) and 32 <= len(value) <= 256 and value.isascii() and (
            hmac.compare_digest(_digest(value), session["csrf_hash"])
        )

    def revoke(self, token):
        if not isinstance(token, str) or len(token) > 256 or not token.isascii():
            return
        with closing(self.connect()) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))
            db.commit()
