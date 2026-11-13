"""Complete-by-default, read-only exports with bounded portable JSON files."""
import json
import os
import tempfile
from pathlib import Path

from .importer import MAX_BYTES, MAX_ENTRIES, _normalize
from .releases import _plain_markdown

MAX_MARKDOWN_ENTRIES = 10000
MAX_OFFSET = 1000000


def export_rows(store, product=None, version=None, fmt="markdown", limit=None, offset=0):
    """Return one consistent SQLite read snapshot, refusing silent truncation.

    Supplying an explicit limit opts into partial export. For stable multi-file
    pagination, use an offline SQLite backup and export from that snapshot.
    """
    if fmt not in ("json", "markdown"):
        raise ValueError("Unsupported export format")
    cap = MAX_ENTRIES if fmt == "json" else MAX_MARKDOWN_ENTRIES
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise ValueError("Export offset must be between 0 and 1000000")
    if limit is None and offset:
        raise ValueError("Export --offset requires an explicit --limit")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= cap):
        raise ValueError(f"Export limit must be between 1 and {cap}")
    clauses, params = [], []
    for column, value in (("product", product), ("version", version)):
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"{column} must be text")
            clauses.append(f"{column} = ?")
            params.append(value)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with store.connect() as db:
        db.execute("BEGIN")
        count = db.execute("SELECT COUNT(*) FROM entries" + where, params).fetchone()[0]
        if limit is None and count > cap:
            raise ValueError(
                f"Export would silently truncate {count} entries (maximum {cap} per file); "
                "pass --limit and --offset to export explicit chunks from a frozen backup"
            )
        selected = cap if limit is None else limit
        rows = db.execute(
            "SELECT * FROM entries" + where +
            " ORDER BY released_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, selected, offset)
        ).fetchall()
        decoded = [store._decode(row) for row in rows]
        # Keep the validator aligned with the import format. Never emit JSON
        # that our own importer would reject in a portability workflow.
        if fmt == "json":
            for record in decoded:
                try:
                    _normalize(record)
                except (ValueError, TypeError, OverflowError) as exc:
                    raise ValueError(
                        f"Entry {record['id']} cannot be imported as portable JSON: {exc}"
                    ) from exc
        return decoded


def markdown(rows):
    out = ["# Changelog", ""]
    for record in rows:
        out.extend([
            f"## {_plain_markdown(record['product'])} "
            f"{_plain_markdown(record['version'])} — "
            f"{_plain_markdown(record['released_at'])}",
            f"### {_plain_markdown(record['kind'].capitalize())}: "
            f"{_plain_markdown(record['title'])}", ""
        ])
        if record["description"]:
            out.extend([_plain_markdown(record["description"]), ""])
        if record["author"]:
            out.extend(["Author: " + _plain_markdown(record["author"]), ""])
    return "\n".join(out).rstrip() + "\n"


def encode_export(rows, fmt):
    if fmt == "json":
        content = json.dumps(rows, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
        if len(content.encode("utf-8")) > MAX_BYTES:
            raise ValueError(
                "Portable JSON export exceeds 8 MiB; use explicit "
                "--limit/--offset chunks or a consistent SQLite backup"
            )
        return content
    return markdown(rows)


def write_export(destination, content):
    """Private, fsync'ed, no-clobber file install on the same filesystem."""
    dest = Path(destination).expanduser()
    if dest.is_symlink() or dest.exists():
        raise ValueError("Export destination exists; files are never overwritten")
    if dest.parent.is_symlink():
        raise ValueError("Export parent directory must not be a symbolic link")
    dest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if dest.parent.is_symlink():
        raise ValueError("Export parent directory must not be a symbolic link")
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix="." + dest.name + ".partial-",
                                        dir=dest.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        # link() atomically installs a new name only when it does not exist.
        # This cannot overwrite a preexisting destination or symlink.
        os.link(temporary, dest)
        if hasattr(os, "O_DIRECTORY") and os.name == "posix":
            dfd = os.open(dest.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
