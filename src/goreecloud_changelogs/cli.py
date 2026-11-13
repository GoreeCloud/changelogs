"""Command-line interface for GoreeCloud Changelogs."""
import argparse
import getpass
import os
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
import sys
from .store import Store, KINDS, default_path, audit_permissions
from .backup import backup, restore, verify_backup
from .importer import read_import, import_records
from .metadata import parse_metadata
from .releases import list_releases, release_details, markdown_release
from .exporter import export_rows, encode_export, write_export, markdown as safe_markdown

def parser():
    p = argparse.ArgumentParser(prog="goree-changelogs", description="Self-hosted changelog management")
    p.add_argument("--db", help="SQLite database path (or GOREE_CHANGELOGS_DB)")
    p.add_argument("--server", default=os.environ.get("GOREE_CHANGELOGS_SERVER_URL"),
                   help="Self-hosted HTTPS server origin; selects shared server instead of local DB")
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
    listing.add_argument("--kind", choices=sorted(KINDS))
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    search = sub.add_parser("search", help="Search changelog text")
    search.add_argument("query")
    search.add_argument("--product")
    search.add_argument("--kind", choices=sorted(KINDS))
    search.add_argument("--limit", type=int, default=100)
    search.add_argument("--offset", type=int, default=0)
    releases = sub.add_parser("releases", help="List releases grouped by product and version")
    releases.add_argument("--product")
    releases.add_argument("--limit", type=int, default=100)
    releases.add_argument("--offset", type=int, default=0)
    notes = sub.add_parser("release-notes", help="Render one release as safe Markdown or JSON")
    notes.add_argument("product")
    notes.add_argument("version")
    notes.add_argument("--format", choices=("markdown", "json"), default="markdown")
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
    export.add_argument("--limit", type=int, default=None,
                        help="Explicit maximum rows (partial exports; default requires all to fit)")
    export.add_argument("--offset", type=int, default=0,
                        help="Entry offset; requires --limit")
    export.add_argument("--output", help="Write a private, atomic, never-overwritten file")
    imp = sub.add_parser("import", help="Preview or atomically import a bounded JSON changelog export")
    imp.add_argument("source", help="UTF-8 JSON array from 'export --format json'")
    imp.add_argument("--expect-sha256", help="Pin source bytes to a reviewed preview SHA-256")
    confirm = imp.add_mutually_exclusive_group()
    confirm.add_argument("--yes", action="store_true", help="Write validated entries; duplicates are skipped")
    confirm.add_argument("--dry-run", action="store_true", help="Validate only (the default)")
    b = sub.add_parser('backup', help='Create a consistent SQLite backup without overwriting')
    b.add_argument('destination')
    r = sub.add_parser('restore', help='Restore a validated backup (replaces existing entries)')
    r.add_argument('source')
    r.add_argument('--yes', action='store_true', help='Explicitly acknowledge replacement')
    r.add_argument('--dry-run', action='store_true', help='Validate restore source without changing or initializing the live database')
    r.add_argument('--recovery-backup', help='Create a verified, non-overwriting pre-restore snapshot at this path')
    sub.add_parser("audit-permissions", help="Read-only database and parent directory privacy audit")
    sub.add_parser("doctor", help="Read-only SQLite health and filesystem privacy diagnostics")
    v = sub.add_parser("verify-backup", help="Read-only backup integrity and schema check")
    v.add_argument("source")
    migrate = sub.add_parser("migrate", help="Preview/send existing local CLI entries to self-hosted server")
    migrate.add_argument("--source", required=True, help="Existing local SQLite changelog database")
    migrate.add_argument("--limit", type=int, default=None, help="Explicit bounded migration chunk")
    migrate.add_argument("--offset", type=int, default=0)
    migrate.add_argument("--expect-sha256", help="Pin reviewed preview to exact SQLite snapshot")
    migrate.add_argument("--yes", action="store_true", help="Confirm HTTPS upload to self-hosted server")
    login = sub.add_parser("login", help="Sign in to configured self-hosted server")
    login.add_argument("--username", required=True)
    host = sub.add_parser("host", help="Initialize or run the self-hosted multi-client server")
    host_sub = host.add_subparsers(dest="host_command", required=True)
    host_init = host_sub.add_parser("init", help="Bootstrap a self-hosted administrator")
    host_init.add_argument("--data-dir", required=True)
    host_init.add_argument("--username", default="admin")
    host_add = host_sub.add_parser("user-add", help="Locally add a reader or administrator")
    host_add.add_argument("--data-dir", required=True)
    host_add.add_argument("--username", required=True)
    host_add.add_argument("--role", choices=("reader", "admin"), default="reader")
    host_pass = host_sub.add_parser("user-password", help="Rotate local user password and revoke sessions")
    host_pass.add_argument("--data-dir", required=True)
    host_pass.add_argument("--username", required=True)
    host_remove = host_sub.add_parser("user-remove", help="Remove a local account and revoke sessions")
    host_remove.add_argument("--data-dir", required=True)
    host_remove.add_argument("--username", required=True)
    host_backup = host_sub.add_parser("backup",
        help="Offline, private no-clobber backup of server data and account DBs")
    host_backup.add_argument("--data-dir", required=True)
    host_backup.add_argument("--destination", required=True)
    host_backup.add_argument("--offline-ack", action="store_true",
                             help="Confirm all server writers are stopped")
    host_verify = host_sub.add_parser("verify-backup",
        help="Read-only verification of a complete self-hosted backup pair")
    host_verify.add_argument("--source", required=True)
    host_serve = host_sub.add_parser("serve", help="Run authenticated web/API listener on loopback")
    host_serve.add_argument("--data-dir", required=True)
    host_serve.add_argument("--origin", default=os.environ.get("GOREE_CHANGELOGS_PUBLIC_ORIGIN"),
                            help="Exact public HTTPS origin at your reviewed ingress")
    host_serve.add_argument("--port", type=int, default=8876)
    server = sub.add_parser("serve", help="Start token-authenticated loopback read-only API")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--web", action="store_true", help="Serve the optional local read-only web viewer")
    return p

def markdown(rows):
    return safe_markdown(rows)

def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "host":
            if args.server or args.db:
                raise ValueError("Host commands use --data-dir, not --server or --db")
            from .hosted_server import data_paths, serve_hosted
            if args.host_command == "verify-backup":
                from .hosted_backup import verify_host_backup
                print(json.dumps(verify_host_backup(args.source), indent=2))
                return 0
            if args.host_command == "backup":
                from .hosted_backup import backup_host
                result = backup_host(args.data_dir, args.destination,
                                     offline_ack=args.offline_ack)
                print(json.dumps(result, indent=2))
                return 0
            if args.host_command == "serve":
                serve_hosted(args.data_dir, args.origin, args.port)
                return 0
            from .hosted_auth import AuthStore
            db, account_path = data_paths(args.data_dir)
            if args.host_command in ("user-add", "user-password", "user-remove"):
                accounts = AuthStore(account_path)
                if args.host_command in ("user-add", "user-password"):
                    password = getpass.getpass("New password (minimum 14 UTF-8 bytes): ")
                    if password != getpass.getpass("Confirm new password: "):
                        raise ValueError("Passwords do not match")
                    if args.host_command == "user-add":
                        accounts.add_user(args.username, password, args.role)
                    else:
                        accounts.change_password(args.username, password)
                    print("Account updated; active sessions revoked on password change.")
                    return 0
                if not sys.stdin.isatty():
                    raise ValueError("Account removal requires interactive confirmation")
                if input(f"Remove account {args.username}? Type 'remove': ") != "remove":
                    print("Cancelled")
                    return 1
                accounts.remove_user(args.username)
                print("Account removed; sessions revoked.")
                return 0
            if db.exists() or account_path.exists():
                raise ValueError("Host data directory is already initialized")
            password = getpass.getpass("Choose administrator password (14+ characters): ")
            confirm = getpass.getpass("Confirm administrator password: ")
            if password != confirm:
                raise ValueError("Passwords do not match")
            from .hosted_auth import _password_bytes
            _password_bytes(password)
            account_store = AuthStore(account_path, initialize=True)
            account_store.bootstrap(args.username, password)
            Store(db)
            print("Self-hosted workspace initialized. Configure HTTPS ingress before remote access.")
            return 0
        if args.command == "migrate":
            if not args.server or args.db:
                raise ValueError("Migration requires --server and --source (not --db)")
            from .hosted_client import origin
            from .hosted_migration import preview, upload
            import hmac
            remote = origin(args.server)
            rows, parts, report = preview(args.source, args.limit, args.offset)
            if not args.yes:
                print(json.dumps(report, indent=2))
                return 0
            digest = (args.expect_sha256 or "").lower()
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or not hmac.compare_digest(
                digest, report["sha256"]
            ):
                raise ValueError("Migration records changed since reviewed SHA-256 preview")
            result = upload(remote, os.environ.get("GOREE_CHANGELOGS_REMOTE_TOKEN"), parts)
            print(json.dumps({"dry_run": False, "sha256": digest, **result}, indent=2))
            return 0
        if args.server:
            if args.db:
                raise ValueError("Do not combine remote --server with local --db")
            from .hosted_client import origin, execute, login as remote_login
            server = origin(args.server)
            if args.command == "login":
                password = getpass.getpass("Self-hosted Changelogs password: ")
                token = remote_login(server, args.username, password)
                # This token is shown once, never written to disk by the CLI.
                print(token)
                return 0
            if args.command not in ("add", "list", "search", "releases",
                                    "summary", "show", "edit", "delete"):
                raise ValueError("This command is local-only; unset --server")
            if args.command == "delete" and not args.yes:
                if not sys.stdin.isatty():
                    raise ValueError("Use --yes for noninteractive remote deletion")
                if input(f"Delete remote entry {args.id}? Type 'delete' to confirm: ") != "delete":
                    print("Cancelled")
                    return 1
            result = execute(args)
            print(json.dumps(result, indent=2) if isinstance(result, (dict, list)) else result)
            return 0
        if args.command == "login":
            raise ValueError("Specify --server to log in to the self-hosted workspace")
        if args.command == "audit-permissions":
            result = audit_permissions(args.db)
            print(json.dumps(result, indent=2))
            return 0 if result["secure"] else 1
        if args.command == "doctor":
            # No Store() construction: never initialize or chmod a missing live DB.
            selected = Path(args.db).expanduser() if args.db else default_path()
            permissions = audit_permissions(selected)
            try:
                verified = verify_backup(selected)
                integrity = {"ok": True, "entries": verified["entries"]}
            except (ValueError, OSError, sqlite3.DatabaseError) as exc:
                # Avoid displaying raw DB content, sensitive paths or SQLite error strings.
                integrity = {"ok": False, "reason": type(exc).__name__}
            healthy = permissions["secure"] and integrity["ok"]
            print(json.dumps({"healthy": healthy, "integrity": integrity,
                              "permissions": permissions}, indent=2))
            return 0 if healthy else 1
        if args.command == "verify-backup":
            print(json.dumps(verify_backup(args.source), indent=2))
            return 0
        if args.command == "restore":
            # Reject unsafe or unconfirmed restores before Store() can create a database.
            if args.dry_run and args.recovery_backup:
                raise ValueError("--dry-run cannot be combined with --recovery-backup")
            if not args.dry_run and not args.yes:
                raise ValueError("Restore replaces existing entries; pass --yes to confirm")
            result = verify_backup(args.source)
            selected_db = Path(args.db).expanduser() if args.db else default_path()
            source_path = Path(args.source).expanduser()
            if source_path.resolve() == selected_db.resolve() or (
                    selected_db.is_file() and source_path.samefile(selected_db)):
                raise ValueError("Source and destination databases must differ (including hard links)")
            if args.dry_run:
                print(json.dumps({"dry_run": True, **result}, indent=2))
                return 0
            if args.recovery_backup:
                recovery = Path(args.recovery_backup).expanduser()
                if recovery.resolve() in (selected_db.resolve(), source_path.resolve()):
                    raise ValueError("Recovery backup must differ from source and destination")
                if recovery.exists() or recovery.is_symlink():
                    raise ValueError("Recovery backup must not already exist")
                if selected_db.is_file() and recovery.is_file() and recovery.samefile(selected_db):
                    raise ValueError("Recovery backup must differ from live database")
            store = Store(args.db)
            if args.recovery_backup:
                backup(store, args.recovery_backup)
            print(restore(store, args.source))
            return 0
        if args.command == "import":
            entries, digest = read_import(args.source)
            if args.expect_sha256 is not None:
                expected = args.expect_sha256.lower()
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise ValueError("--expect-sha256 requires exactly 64 hexadecimal characters")
                if expected != digest:
                    raise ValueError("Import source differs from expected SHA-256; no data imported")
            if not args.yes:
                print(json.dumps({"dry_run": True, "validated": len(entries), "sha256": digest}, indent=2))
                return 0
            result = import_records(Store(args.db), entries)
            print(json.dumps({"dry_run": False, **result, "sha256": digest}, indent=2))
            return 0
        if args.command == "serve":
            from .api import serve
            serve(args.db, args.port, web=args.web)
            return 0
        # Reject malformed or unconfirmed mutations before Store() can
        # initialize a previously missing database and parent directories.
        add_metadata = None
        edit_fields = None
        if args.command == "add":
            if not all(value.strip() for value in (args.product, args.version, args.title)):
                raise ValueError("Product, version and title are required")
            if args.date:
                datetime.fromisoformat(args.date.replace("Z", "+00:00"))
            add_metadata = parse_metadata(args.metadata)
        elif args.command == "edit":
            edit_fields = {
                key: getattr(args, key)
                for key in ("product", "version", "kind", "title", "description", "author")
                if getattr(args, key) is not None
            }
            for key in ("product", "version", "title"):
                if key in edit_fields and not edit_fields[key].strip():
                    raise ValueError(f"{key} cannot be empty")
            if args.date is not None:
                datetime.fromisoformat(args.date.replace("Z", "+00:00"))
                edit_fields["released_at"] = args.date
            if args.metadata is not None:
                edit_fields["metadata"] = parse_metadata(args.metadata)
            if not edit_fields:
                raise ValueError("No valid update fields")
        elif args.command == "delete" and not args.yes:
            if not sys.stdin.isatty():
                raise ValueError("Use --yes for noninteractive deletion")
            if input(f"Delete entry {args.id}? Type 'delete' to confirm: ") != "delete":
                print("Cancelled")
                return 1
            args.yes = True
        store = Store(args.db)
        if args.command == "backup":
            print(backup(store, args.destination))
        elif args.command == "add":
            entry_id = store.add(args.product, args.version, args.kind, args.title,
                                 args.description, args.author, args.date, add_metadata)
            print(entry_id)
        elif args.command == "list":
            print(json.dumps(store.list(args.product, args.version, args.limit, args.offset, kind=args.kind), indent=2))
        elif args.command == "search":
            print(json.dumps(store.search(args.query, args.product, args.limit, args.offset, kind=args.kind), indent=2))
        elif args.command == "summary":
            print(json.dumps(store.summary(args.product), indent=2))
        elif args.command == "releases":
            print(json.dumps(list_releases(store, args.product, args.limit, args.offset), indent=2))
        elif args.command == "release-notes":
            release = release_details(store, args.product, args.version)
            print(json.dumps(release, indent=2) if args.format == "json"
                  else markdown_release(release), end="")
        elif args.command == "show":
            entry = store.get(args.id)
            if entry is None:
                raise ValueError("Entry not found")
            print(json.dumps(entry, indent=2))
        elif args.command == "edit":
            if not store.update(args.id, **edit_fields):
                raise ValueError("Entry not found")
            print("Updated")
        elif args.command == "delete":
            if not store.delete(args.id):
                raise ValueError("Entry not found")
            print("Deleted")
        elif args.command == "export":
            rows = export_rows(store, args.product, args.version,
                               args.format, args.limit, args.offset)
            content = encode_export(rows, args.format)
            if args.output:
                write_export(args.output, content)
            else:
                print(content, end="")
        return 0
    except (ValueError, OSError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
