"""Command-line interface for GoreeCloud Changelogs."""
import argparse
import json
import sqlite3
from pathlib import Path
import sys
from .store import Store, KINDS
from .backup import backup, restore, verify_backup

def parser():
    p = argparse.ArgumentParser(prog="goree-changelogs", description="Self-hosted changelog management")
    p.add_argument("--db", help="SQLite database path (or GOREE_CHANGELOGS_DB)")
    sub = p.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="Create a changelog entry")
    add.add_argument("product")
    add.add_argument("version")
    add.add_argument("kind", choices=sorted(KINDS))
    add.add_argument("title")
    add.add_argument("--description", default="")
    add.add_argument("--author", default="")
    add.add_argument("--date", help="ISO 8601 release date")
    add.add_argument("--metadata", default="{}", help="JSON object")
    listing = sub.add_parser("list", help="List entries")
    listing.add_argument("--product")
    listing.add_argument("--version")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    search = sub.add_parser("search", help="Search changelog text")
    search.add_argument("query")
    search.add_argument("--product")
    search.add_argument("--limit", type=int, default=100)
    search.add_argument("--offset", type=int, default=0)
    summary = sub.add_parser("summary", help="Summarize entries by product and kind")
    summary.add_argument("--product")
    show = sub.add_parser("show", help="Show one entry")
    show.add_argument("id", type=int)
    edit = sub.add_parser("edit", help="Update an entry")
    edit.add_argument("id", type=int)
    for name in ("product", "version", "title", "description", "author"):
        edit.add_argument("--" + name)
    edit.add_argument("--kind", choices=sorted(KINDS))
    edit.add_argument("--date")
    edit.add_argument("--metadata")
    delete = sub.add_parser("delete", help="Delete an entry")
    delete.add_argument("id", type=int)
    delete.add_argument("--yes", action="store_true", help="Confirm deletion noninteractively")
    export = sub.add_parser("export", help="Export entries")
    export.add_argument("--product")
    export.add_argument("--version")
    export.add_argument("--format", choices=("json", "markdown"), default="markdown")
    export.add_argument("--limit", type=int, default=10000)
    b = sub.add_parser('backup', help='Create a consistent SQLite backup without overwriting')
    b.add_argument('destination')
    r = sub.add_parser('restore', help='Restore a validated backup (replaces existing entries)')
    r.add_argument('source')
    r.add_argument('--yes', action='store_true', help='Explicitly acknowledge replacement')
    r.add_argument('--recovery-backup', help='Create a verified, non-overwriting pre-restore snapshot at this path')
    v = sub.add_parser("verify-backup", help="Read-only backup integrity and schema check")
    v.add_argument("source")
    server = sub.add_parser("serve", help="Start token-authenticated loopback read-only API")
    server.add_argument("--port", type=int, default=8765)
    return p

def markdown(rows):
    out = ["# Changelog", ""]
    for row in rows:
        out.extend([f"## {row['product']} {row['version']} — {row['released_at']}",
                    f"### {row['kind'].capitalize()}: {row['title']}", ""])
        if row["description"]:
            out.extend([row["description"], ""])
        if row["author"]:
            out.extend([f"Author: {row['author']}", ""])
    return "\n".join(out).rstrip() + "\n"

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "verify-backup":
            print(json.dumps(verify_backup(args.source), indent=2))
            return 0
        store = Store(args.db)
        if args.command == "serve":
            from .api import serve
            serve(args.db, args.port)
        elif args.command == "backup":
            print(backup(store, args.destination))
        elif args.command == "restore":
            if not args.yes:
                raise ValueError("Restore replaces existing entries; pass --yes to confirm")
            if args.recovery_backup:
                # Validate the incoming snapshot before creating a recovery copy.
                verify_backup(args.source)
                if Path(args.recovery_backup).expanduser().resolve() == store.path.resolve():
                    raise ValueError("Recovery backup must differ from the live database")
                if Path(args.recovery_backup).expanduser().resolve() == Path(args.source).expanduser().resolve():
                    raise ValueError("Recovery backup must differ from the restore source")
                backup(store, args.recovery_backup)
            print(restore(store, args.source))
        elif args.command == "add":
            entry_id = store.add(args.product, args.version, args.kind, args.title,
                                 args.description, args.author, args.date, json.loads(args.metadata))
            print(entry_id)
        elif args.command == "list":
            print(json.dumps(store.list(args.product, args.version, args.limit, args.offset), indent=2))
        elif args.command == "search":
            print(json.dumps(store.search(args.query, args.product, args.limit, args.offset), indent=2))
        elif args.command == "summary":
            print(json.dumps(store.summary(args.product), indent=2))
        elif args.command == "show":
            entry = store.get(args.id)
            if entry is None:
                raise ValueError("Entry not found")
            print(json.dumps(entry, indent=2))
        elif args.command == "edit":
            fields = {key: getattr(args, key) for key in ("product", "version", "kind", "title", "description", "author") if getattr(args, key) is not None}
            if args.date is not None:
                fields["released_at"] = args.date
            if args.metadata is not None:
                fields["metadata"] = json.loads(args.metadata)
            if not store.update(args.id, **fields):
                raise ValueError("Entry not found")
            print("Updated")
        elif args.command == "delete":
            if not args.yes:
                if not sys.stdin.isatty():
                    raise ValueError("Use --yes for noninteractive deletion")
                if input(f"Delete entry {args.id}? Type 'delete' to confirm: ") != "delete":
                    print("Cancelled")
                    return 1
            if not store.delete(args.id):
                raise ValueError("Entry not found")
            print("Deleted")
        elif args.command == "export":
            rows = store.list(args.product, args.version, args.limit)
            print(json.dumps(rows, indent=2) if args.format == "json" else markdown(rows), end="")
        return 0
    except (ValueError, OSError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
