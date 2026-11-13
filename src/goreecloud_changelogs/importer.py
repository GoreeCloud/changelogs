"""Bounded, non-executable JSON changelog imports with transactional deduplication.

Imports the row-list format produced by `goree-changelogs export --format json`.
IDs are database-local and never imported. Records are fully validated before
opening a writable database. Re-importing the same change is idempotent.
"""
import hashlib
import json
import os
import stat
from datetime import date, datetime, timezone
from pathlib import Path

from .store import KINDS

MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 5000
INPUT_FIELDS = frozenset({
    "id", "product", "version", "kind", "title", "description", "author",
    "released_at", "metadata", "created_at", "updated_at"
})
FINGERPRINT_FIELDS = (
    "product", "version", "kind", "title", "description", "author",
    "released_at", "metadata"
)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON number is not supported")


def _required_text(value, name, maximum, mandatory=True):
    if not isinstance(value, str) or len(value) > maximum or (
            mandatory and not value.strip()):
        raise ValueError(f"Invalid {name}; expected nonempty text of up to {maximum} characters")
    return value


def _iso(value, name):
    value = _required_text(value, name, 64)
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {name}; use ISO 8601") from exc
    return value


def _canonical_metadata(value):
    if not isinstance(value, dict):
        raise ValueError("metadata must be a JSON object")
    result = json.dumps(value, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=False, allow_nan=False)
    if len(result.encode("utf-8")) > 65536:
        raise ValueError("metadata exceeds 64 KiB")
    return result


def _normalize(entry):
    if not isinstance(entry, dict):
        raise ValueError("Each changelog entry must be a JSON object")
    if set(entry) - INPUT_FIELDS:
        raise ValueError("Unsupported changelog entry fields")
    if "id" in entry and (type(entry["id"]) is not int or entry["id"] < 1):
        raise ValueError("id must be a positive integer when present")
    for field in ("product", "version", "kind", "title", "released_at"):
        if field not in entry:
            raise ValueError(f"Missing required field: {field}")
    product = _required_text(entry["product"], "product", 128)
    version = _required_text(entry["version"], "version", 96)
    kind = entry["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Invalid change kind")
    title = _required_text(entry["title"], "title", 256)
    description = _required_text(entry.get("description", ""), "description", 32768, False)
    author = _required_text(entry.get("author", ""), "author", 128, False)
    released_at = _iso(entry["released_at"], "released_at")
    metadata = _canonical_metadata(entry.get("metadata", {}))
    now = datetime.now(timezone.utc).isoformat()
    created_at = _iso(entry.get("created_at", now), "created_at")
    updated_at = _iso(entry.get("updated_at", now), "updated_at")
    return {
        "product": product, "version": version, "kind": kind, "title": title,
        "description": description, "author": author, "released_at": released_at,
        "metadata": metadata, "created_at": created_at, "updated_at": updated_at
    }


def _fingerprint(record):
    return tuple(record[field] for field in FINGERPRINT_FIELDS)


def read_import(path):
    """Read one regular file once with an 8 MiB byte cap; never follow symlinks."""
    source = Path(path).expanduser()
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if source.is_symlink():
        raise ValueError("Import source cannot be a symbolic link")
    descriptor = os.open(source, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Import source must be a regular file")
        if info.st_size > MAX_BYTES:
            raise ValueError("Import source exceeds 8 MiB")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("Import source exceeds 8 MiB")
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw.decode("utf-8"),
                           object_pairs_hook=_unique_pairs,
                           parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Import must be valid UTF-8 JSON") from exc
    if not isinstance(value, list):
        raise ValueError("Import JSON must be a list of changelog entries")
    if len(value) > MAX_ENTRIES:
        raise ValueError("Import exceeds 5000 entries")
    normalized = []
    seen = set()
    for index, entry in enumerate(value):
        try:
            record = _normalize(entry)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Invalid entry at index {index}: {exc}") from exc
        fingerprint = _fingerprint(record)
        if fingerprint in seen:
            raise ValueError(f"Duplicate source entry at index {index}")
        seen.add(fingerprint)
        normalized.append(record)
    return normalized, hashlib.sha256(raw).hexdigest()


def import_records(store, entries):
    """Import atomically; skip equivalent existing entries, preserving DB-local IDs."""
    inserted = 0
    skipped = 0
    fields = (
        "product", "version", "kind", "title", "description", "author",
        "released_at", "metadata", "created_at", "updated_at"
    )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for record in entries:
            candidates = db.execute(
                """SELECT metadata FROM entries WHERE
                   product = ? AND version = ? AND kind = ? AND
                   title = ? AND description = ? AND author = ? AND released_at = ?""",
                tuple(record[name] for name in FINGERPRINT_FIELDS[:-1])
            )
            metadata = json.loads(record["metadata"])
            if any(json.loads(row["metadata"]) == metadata for row in candidates):
                skipped += 1
                continue
            db.execute(
                "INSERT INTO entries (" + ", ".join(fields) + ") VALUES (" +
                ", ".join("?" for _ in fields) + ")",
                tuple(record[field] for field in fields)
            )
            inserted += 1
    return {"validated": len(entries), "inserted": inserted, "skipped_existing": skipped}
