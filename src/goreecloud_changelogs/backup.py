"""Consistent SQLite backups and guarded restoration."""
import os
import sqlite3
from .metadata import parse_metadata
from .store import KINDS
import tempfile
from contextlib import closing
from pathlib import Path

REQUIRED_COLUMNS = {"id", "product", "version", "kind", "title", "description", "author", "released_at", "metadata", "created_at", "updated_at"}

def _validate_source(path):
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError("Backup must be an existing regular file, not a symlink")
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        result = db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("Backup failed SQLite integrity check")
        # Reject unexpected executable schema objects such as triggers and
        # views before restoring a snapshot into the writable live database.
        objects = {
            (row[0], row[1], row[2])
            for row in db.execute(
                "SELECT type, name, tbl_name FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        expected_objects = {
            ("table", "entries", "entries"),
            ("index", "entries_product_version", "entries"),
        }
        if objects != expected_objects:
            raise ValueError("Backup contains an unsupported schema object or missing index")
        info = list(db.execute("PRAGMA table_info(entries)"))
        columns = {row[1] for row in info}
        if columns != REQUIRED_COLUMNS or len(info) != len(REQUIRED_COLUMNS):
            raise ValueError("Backup does not contain a compatible changelog schema")
        for row in info:
            name, sql_type, required, primary_key = row[1], row[2], row[3], row[5]
            if name == "id":
                if sql_type.upper() != "INTEGER" or primary_key != 1:
                    raise ValueError("Backup entry primary key is incompatible")
            elif sql_type.upper() != "TEXT" or required != 1 or primary_key:
                raise ValueError("Backup entry column types or constraints are incompatible")
        index_fields = [
            row[2] for row in db.execute("PRAGMA index_info(entries_product_version)")
        ]
        if index_fields != ["product", "version"]:
            raise ValueError("Backup contains an incompatible product/version index")
        # Metadata and kind validation closes the gap between SQLite integrity
        # (valid pages) and application-level correctness (valid changelog rows).
        for entry_id, kind, metadata in db.execute(
                "SELECT id, kind, metadata FROM entries"):
            if kind not in KINDS:
                raise ValueError(f"Backup entry {entry_id} has an invalid change kind")
            try:
                parse_metadata(metadata)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Backup entry {entry_id} has invalid JSON metadata") from exc
    return path

def verify_backup(source):
    """Validate an existing backup without modifying it or creating a live database."""
    path = _validate_source(source)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        count = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    return {"valid": True, "entries": count}


def backup(store, destination):
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination already exists; backups never overwrite")
    if destination.parent.is_symlink():
        raise ValueError("Backup parent directory must not be a symbolic link")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination.parent.is_symlink():
        raise ValueError("Backup parent directory must not be a symbolic link")
    # Atomic, unpredictable creation prevents predictable-name symlink races.
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".partial-", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with store.connect() as source:
            with closing(sqlite3.connect(temp)) as target:
                source.backup(target)
                # A WAL-mode source can transfer WAL mode to the snapshot.
                # Normalize the standalone backup before publishing it.
                target.execute("PRAGMA journal_mode=DELETE")
        _validate_source(temp)
        # Exclusive publication; never silently replace a preexisting backup.
        os.link(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination

def restore(store, source, *, page_batch=-1, progress=None):
    """Restore via SQLite online backup API.

    page_batch and progress are optional injection points for deterministic
    recovery testing; CLI callers use SQLite's default full backup.
    """
    if type(page_batch) is not int or (page_batch != -1 and page_batch < 1):
        raise ValueError("page_batch must be -1 or a positive integer")
    source = _validate_source(source)
    if source.samefile(store.path):
        raise ValueError("Source and destination databases must differ (including hard links)")
    # sqlite3 backup API copies a consistent snapshot into the existing database.
    # Caller must explicitly acknowledge that current records will be replaced.
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as incoming:
        with closing(sqlite3.connect(store.path)) as target:
            incoming.backup(target, pages=page_batch, progress=progress)
    return store.path
