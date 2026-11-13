"""Preview-first migration of legacy local CLI rows to the self-hosted server.

Uses SQLite read-only mode and a single read transaction. Never initializes,
changes or deletes the source. Confirmation pins a new snapshot to reviewed SHA.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import quote

from .hosted_client import request, origin
from .importer import MAX_BYTES, MAX_ENTRIES, _normalize

MAX_UPLOAD = 60 * 1024
BATCH_MAX = 100
MAX_OFFSET = 1_000_000


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def read_snapshot(source, *, limit=None, offset=0):
    """Read an existing local DB read-only, validating all outbound records."""
    path = Path(source).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Migration source must be an existing regular non-symlink SQLite file")
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise ValueError("Migration offset must be 0-1000000")
    if limit is None and offset:
        raise ValueError("--offset requires an explicit --limit")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= MAX_ENTRIES):
        raise ValueError("Migration limit must be 1-5000")
    # A URI-escaped absolute path prevents SQLite URI query injection.
    uri = "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            total = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            if limit is None and total > MAX_ENTRIES:
                raise ValueError("Migration exceeds 5000 entries; use explicit --limit and --offset")
            rows = db.execute(
                "SELECT * FROM entries ORDER BY released_at DESC, id DESC "
                "LIMIT ? OFFSET ?", (limit or MAX_ENTRIES, offset)).fetchall()
            records = []
            for row in rows:
                record = dict(row)
                record["metadata"] = json.loads(record["metadata"])
                _normalize(record)
                records.append(record)
    except (sqlite3.DatabaseError, OSError, KeyError, TypeError,
            json.JSONDecodeError) as exc:
        raise ValueError("Migration source has invalid or incompatible changelog records") from exc
    canonical = _json(records)
    if len(canonical) > MAX_BYTES:
        raise ValueError("Migration exceeds 8 MiB; use explicit smaller bounded chunks")
    return records, hashlib.sha256(canonical).hexdigest()


def batches(entries):
    """Validate an entire migration before yielding bounded HTTP batches."""
    chunks = []
    current = []
    for entry in entries:
        candidate = current + [entry]
        payload = _json({"entries": candidate})
        if len(candidate) > BATCH_MAX or len(payload) > MAX_UPLOAD:
            if not current:
                raise ValueError("One changelog record exceeds the server batch limit")
            chunks.append(current)
            current = [entry]
            if len(_json({"entries": current})) > MAX_UPLOAD:
                raise ValueError("One changelog record exceeds the server batch limit")
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def preview(source, limit=None, offset=0):
    rows, digest = read_snapshot(source, limit=limit, offset=offset)
    parts = batches(rows)
    return rows, parts, {
        "dry_run": True, "validated": len(rows), "batches": len(parts),
        "sha256": digest, "offset": offset
    }


def upload(server, token, parts, *, transport=None):
    """Each HTTP batch is atomic/idempotent, the overall migration is resumable."""
    server = origin(server)
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii():
        raise ValueError("Set GOREE_CHANGELOGS_REMOTE_TOKEN to a short-lived login token")
    totals = {"validated": 0, "inserted": 0, "skipped_existing": 0, "batches": 0}
    for entries in parts:
        result = request(server, "/v1/import", token=token, method="POST",
                         body={"entries": entries}, transport=transport)
        number = len(entries)
        if any(type(result.get(field)) is not int or result[field] < 0 for field in
               ("validated", "inserted", "skipped_existing")) or (
            result["validated"] != number or
            result["inserted"] + result["skipped_existing"] != number
        ):
            raise ValueError("Server returned invalid migration acknowledgement")
        for field in ("validated", "inserted", "skipped_existing"):
            totals[field] += result[field]
        totals["batches"] += 1
    return totals
