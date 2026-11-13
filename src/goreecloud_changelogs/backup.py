"""Consistent SQLite backups and guarded restoration."""
import os
import sqlite3
from pathlib import Path

REQUIRED_COLUMNS = {"id", "product", "version", "kind", "title", "description", "author", "released_at", "metadata", "created_at", "updated_at"}

def _validate_source(path):
    path = Path(path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise ValueError("Backup must be an existing regular file, not a symlink")
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise ValueError("Backup failed SQLite integrity check")
        columns = {row[1] for row in db.execute("PRAGMA table_info(entries)")}
        if not REQUIRED_COLUMNS.issubset(columns):
            raise ValueError("Backup does not contain a compatible changelog schema")
    return path

def backup(store, destination):
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination already exists; backups never overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".partial-" + str(os.getpid()))
    if temp.exists() or temp.is_symlink():
        raise ValueError("Temporary backup path already exists")
    try:
        with store.connect() as source:
            with sqlite3.connect(temp) as target:
                source.backup(target)
        _validate_source(temp)
        os.chmod(temp, 0o600)
        # Exclusive publication; never silently replace a preexisting backup.
        os.link(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination

def restore(store, source):
    source = _validate_source(source)
    if source.resolve() == store.path.resolve():
        raise ValueError("Source and destination databases must differ")
    # sqlite3 backup API copies a consistent snapshot into the existing database.
    # Caller must explicitly acknowledge that current records will be replaced.
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as incoming:
        with sqlite3.connect(store.path) as target:
            incoming.backup(target)
    return store.path
