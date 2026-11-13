"""SQLite-backed changelog store. No network access or third-party dependencies."""
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"added", "changed", "fixed", "removed", "security", "deprecated", "other"}

def default_path():
    return Path(os.environ.get("GOREE_CHANGELOGS_DB", str(Path.home() / ".local" / "share" / "goreecloud" / "changelogs.sqlite3"))).expanduser()

def audit_permissions(path=None):
    """Read-only POSIX privacy audit; never create or chmod any path."""
    database = Path(path).expanduser() if path else default_path()
    findings = []
    for label, candidate, expected_directory in (
        ("directory", database.parent, True),
        ("database", database, False),
        ("wal", Path(str(database) + "-wal"), False),
        ("shared-memory", Path(str(database) + "-shm"), False),
        ("journal", Path(str(database) + "-journal"), False),
    ):
        if candidate.is_symlink():
            findings.append(f"{label}: symbolic link")
            continue
        try:
            mode = candidate.stat().st_mode
        except FileNotFoundError:
            if label in ("directory", "database"):
                findings.append(f"{label}: missing")
            continue
        if expected_directory and not stat.S_ISDIR(mode):
            findings.append(f"{label}: not a directory")
        elif not expected_directory and not stat.S_ISREG(mode):
            findings.append(f"{label}: not a regular file")
        elif os.name == "posix" and mode & (0o077 if expected_directory else 0o077):
            findings.append(f"{label}: group/other access permitted")
    return {"secure": not findings, "findings": findings}


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        # New parent directories should default to private, regardless of umask.
        # Do not modify modes of directories or databases that already exist.
        if self.path.parent.is_symlink():
            raise ValueError("Database parent directory must not be a symbolic link")
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.path.parent.is_symlink():
            raise ValueError("Database parent directory must not be a symbolic link")
        if self.path.is_symlink():
            raise ValueError("Database path must not be a symbolic link")
        self._secure_new_database()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product TEXT NOT NULL,
                    version TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    released_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entries_product_version ON entries(product, version);
            """)

    def _secure_new_database(self):
        """Create the database with owner-only permissions without changing existing files."""
        if self.path.exists():
            if not self.path.is_file():
                raise ValueError("Database path must be a regular file")
            return
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError:
            if self.path.is_symlink() or not self.path.is_file():
                raise ValueError("Database path must be a regular file")
        else:
            os.close(fd)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, product, version, kind, title, description="", author="", released_at=None, metadata=None):
        if kind not in KINDS:
            raise ValueError("Invalid change kind")
        if not all(isinstance(v, str) and v.strip() for v in (product, version, title)):
            raise ValueError("Product, version and title are required")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("Metadata must be a JSON object")
        now = datetime.now(timezone.utc).isoformat()
        date = released_at or now[:10]
        datetime.fromisoformat(date.replace("Z", "+00:00"))
        with self.connect() as db:
            cur = db.execute("""INSERT INTO entries
                (product,version,kind,title,description,author,released_at,metadata,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (product.strip(), version.strip(), kind, title.strip(), description, author, date, json.dumps(metadata), now, now))
            return cur.lastrowid

    def list(self, product=None, version=None, limit=100, offset=0):
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise ValueError("Limit must be between 1 and 10000")
        if not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise ValueError("Offset must be between 0 and 1000000")
        clauses, params = [], []
        for key, value in (("product", product), ("version", version)):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM entries" + where + " ORDER BY released_at DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
            return [self._decode(row) for row in rows]

    def search(self, query, product=None, limit=100, offset=0):
        """Literal case-insensitive search across changelog text fields."""
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ValueError("Search query must contain 1-256 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
        if not isinstance(offset, int) or not 0 <= offset <= 1000000:
            raise ValueError("Offset must be between 0 and 1000000")
        needle = query.strip().lower()
        # instr() performs literal matching; unlike LIKE, % and _ are not wildcards.
        params = [needle] * 5
        sql = """SELECT * FROM entries WHERE
            (instr(lower(product), ?) > 0 OR instr(lower(version), ?) > 0 OR
             instr(lower(title), ?) > 0 OR instr(lower(description), ?) > 0 OR
             instr(lower(author), ?) > 0)"""
        if product is not None:
            sql += " AND product = ?"
            params.append(product)
        sql += " ORDER BY released_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend((limit, offset))
        with self.connect() as db:
            return [self._decode(row) for row in db.execute(sql, params).fetchall()]

    def summary(self, product=None):
        """Aggregate release activity without loading individual metadata."""
        with self.connect() as db:
            where = " WHERE product = ?" if product is not None else ""
            params = (product,) if product is not None else ()
            total = db.execute("SELECT COUNT(*) FROM entries" + where, params).fetchone()[0]
            kinds = db.execute("SELECT kind, COUNT(*) AS count FROM entries" + where +
                               " GROUP BY kind ORDER BY kind", params).fetchall()
            products = db.execute("SELECT product, COUNT(*) AS count FROM entries" + where +
                                  " GROUP BY product ORDER BY count DESC, product LIMIT 100", params).fetchall()
            return {"total": total, "by_kind": {r["kind"]: r["count"] for r in kinds},
                    "by_product": {r["product"]: r["count"] for r in products}}

    def get(self, entry_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
            return self._decode(row) if row else None

    def update(self, entry_id, **fields):
        allowed = {"product", "version", "kind", "title", "description", "author", "released_at", "metadata"}
        if not fields or set(fields) - allowed:
            raise ValueError("No valid update fields")
        if "kind" in fields and fields["kind"] not in KINDS:
            raise ValueError("Invalid change kind")
        for field in ("product", "version", "title"):
            if field in fields and (not isinstance(fields[field], str) or not fields[field].strip()):
                raise ValueError(f"{field} cannot be empty")
        if "released_at" in fields:
            datetime.fromisoformat(fields["released_at"].replace("Z", "+00:00"))
        if "metadata" in fields:
            if not isinstance(fields["metadata"], dict):
                raise ValueError("Metadata must be a JSON object")
            fields["metadata"] = json.dumps(fields["metadata"])
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.connect() as db:
            result = db.execute(f"UPDATE entries SET {assignments} WHERE id = ?", (*fields.values(), entry_id))
            return result.rowcount > 0

    def delete(self, entry_id):
        with self.connect() as db:
            result = db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            return result.rowcount > 0

    @staticmethod
    def _decode(row):
        record = dict(row)
        record["metadata"] = json.loads(record["metadata"])
        return record
