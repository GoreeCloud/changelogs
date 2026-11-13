"""SQLite-backed changelog store. No network access or third-party dependencies."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"added", "changed", "fixed", "removed", "security", "deprecated", "other"}

def default_path():
    return Path(os.environ.get("GOREE_CHANGELOGS_DB", str(Path.home() / ".local" / "share" / "goreecloud" / "changelogs.sqlite3"))).expanduser()

class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Database path must not be a symbolic link")
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

    def list(self, product=None, version=None, limit=100):
        if not 1 <= limit <= 10000:
            raise ValueError("Limit must be between 1 and 10000")
        clauses, params = [], []
        for key, value in (("product", product), ("version", version)):
            if value is not None:
                clauses.append(f"{key} = ?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM entries" + where + " ORDER BY released_at DESC, id DESC LIMIT ?", (*params, limit)).fetchall()
            return [self._decode(row) for row in rows]

    def search(self, query, product=None, limit=100):
        """Literal case-insensitive search across changelog text fields."""
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ValueError("Search query must contain 1-256 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
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
        sql += " ORDER BY released_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            return [self._decode(row) for row in db.execute(sql, params).fetchall()]

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
