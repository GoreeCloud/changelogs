# GoreeCloud Changelogs

Self-hosted, local-first changelog management for applications, services, APIs, and infrastructure.

**Status:** 0.1.0 development CLI. A read-only, loopback HTTP API is available for local integrations. Optional loopback web viewer and native Android reader sources are included; neither is a remotely exposed or production-deployed service.

## Install

Python 3.10+:

```sh
python -m pip install .
goree-changelogs --help
```

## Usage

```sh
goree-changelogs add goreecloud-mesh 0.1.0 added "Initial sync engine" --description "Local-first synchronization" --author GoreeCloud
goree-changelogs list --product goreecloud-mesh --limit 50 --offset 0
goree-changelogs search "synchronization" --product goreecloud-mesh
goree-changelogs summary --product goreecloud-mesh
goree-changelogs show 1
goree-changelogs edit 1 --description "Updated release details"
goree-changelogs export --format markdown > CHANGELOG.md
goree-changelogs export --format json > changelogs.json
goree-changelogs delete 1
```

Deletion requires typing `delete` interactively, or explicitly passing `--yes` for automation. Back up the database before deletion.

Database defaults to `~/.local/share/goreecloud/changelogs.sqlite3`. Set `GOREE_CHANGELOGS_DB` or global `--db` to override. SQLite stores entries with product, version, kind, title, description, author, release date, JSON metadata, and creation/update timestamps. Filtering by product and version is supported. JSON metadata is a strictly parsed object; duplicate keys, NaN/Infinity, non-JSON values and metadata larger than 64 KiB are rejected before insertion or update.

## Release notes and version history

View all versions grouped by product, or filter one application/service. Release groups are ordered by latest recorded release date; versions are treated as literal strings (not assumed to follow semantic versioning):

```sh
goree-changelogs releases --product goreecloud-mesh --limit 25 --offset 0
goree-changelogs release-notes goreecloud-mesh 0.1.0
goree-changelogs release-notes goreecloud-mesh 0.1.0 --format json
goree-changelogs release-notes goreecloud-mesh 0.1.0 > RELEASE_NOTES.md
```

The `releases` command reports each version's earliest and latest recorded release date, entry count, and counts by change kind. `release-notes` groups individual changes in familiar Added/Changed/Deprecated/Removed/Fixed/Security sections, escaping content as literal Markdown text to prevent accidental rendered HTML. A missing version or release larger than 10,000 entries fails rather than silently returning incomplete notes. The loopback API adds authenticated `GET /v1/releases?product=...&limit=...&offset=...`, keeping all endpoints read-only. Release notes contain whatever product names, authors and descriptions you recorded—review before publishing them.

## Portable JSON import (preview-first)

Export your entries to inert UTF-8 JSON. Preview a JSON import **without creating a database** and then explicitly opt in to adding validated entries:

```sh
goree-changelogs export --format json > changelogs.json
goree-changelogs --db ./restored.sqlite3 import changelogs.json
goree-changelogs --db ./restored.sqlite3 import changelogs.json --yes --expect-sha256 YOUR_PREVIEW_SHA256
```

The default import mode is a read-only validation preview (equivalent to `--dry-run`) showing the validated record count and SHA-256 of the input bytes. Pass that 64-character value with `--expect-sha256` when using `--yes` to reject a changed source before opening or initializing the destination database; omit the option only when input pinning is not needed. `--yes` opens the target SQLite database only after all rows pass validation. A single transaction imports entries without overwriting existing rows; an exact match of product, version, kind, title, description, author, release date, and JSON metadata is skipped, even if metadata key order differs. IDs remain database-local; exported creation and modification times are preserved. Duplicate records *within the source* are rejected rather than silently collapsed.

To limit untrusted imports, the importer requires a regular, non-symlink file, valid UTF-8, a JSON array of at most 5,000 entries and at most 8 MiB, known entry fields, a JSON metadata object, valid ISO 8601 dates, and bounded field lengths. Duplicate JSON keys and non-finite values are rejected. The importer does not evaluate data as code or access the network. Preview does not ensure that a later import will have the same duplicate count if the destination is modified in between. Inspect the data before importing; do not include credentials or private information in a public changelog export.

## Backups and recovery

Create a consistent SQLite backup without overwriting an existing file:

```sh
goree-changelogs backup ./snapshot.sqlite3
goree-changelogs verify-backup ./snapshot.sqlite3
```

Preflight a restore without creating or modifying the live database:

```sh
goree-changelogs restore ./snapshot.sqlite3 --dry-run
```

Restore from a validated backup (replaces all current entries; back up the live database first):

```sh
goree-changelogs restore ./snapshot.sqlite3 --yes --recovery-backup ./before-restore.sqlite3
```

Backups are checked for SQLite page integrity, the exact supported entries schema/index (rejecting extra triggers, views and tables), valid change kinds, and strict JSON metadata. The checks are for this application's restore format, not a certification that arbitrary third-party SQLite files are safe to inspect. `verify-backup` performs a non-mutating check and prints JSON containing `valid` and `entries`; it does not initialize a live database. A dry run validates the source and reports its entry count but does not lock the live database or guarantee that a subsequent restore will succeed. A refused restore (missing confirmation, invalid source, self-alias, or existing recovery path) is checked before the CLI initializes a missing live database. The restore command requires explicit confirmation. The optional `--recovery-backup` creates a validated, non-overwriting snapshot of the current database before replacing records. This is not an automatic rollback mechanism, and concurrent writers must be stopped during recovery. These commands operate on the selected local database; no remote backup or cloud synchronization is implied.

## Local privacy audit

Check the database and its containing directory without modifying either path:

```sh
goree-changelogs audit-permissions
```

On POSIX, the audit flags group/other access, missing paths, symbolic links, and unexpected file types, including present SQLite `-wal`, `-shm`, and `-journal` sidecars. Newly created database and backup parent directories are initialized private (`0700` on POSIX); existing directory permissions remain unchanged. It returns JSON and exits nonzero when findings exist. This is a privacy check, not a complete filesystem security audit: review ancestor directories, ACLs, ownership, backups, and encryption separately. No automatic permission changes are performed.

## Local database doctor

Inspect SQLite integrity, schema compatibility, record count and POSIX filesystem privacy in one JSON report:

```sh
goree-changelogs doctor
goree-changelogs --db ./archive.sqlite3 doctor
```

Exit code `0` means both the SQLite integrity check and the applicable local permission audit passed. Exit code `1` signals missing/invalid data, exposed directory or file permissions, or another finding. This command does **not** initialize a missing database or change existing permissions. It reports diagnostic status, not a cybersecurity certification, comprehensive ancestor/ACL assessment or release approval. For live WAL databases, SQLite may need its normal shared-memory sidecars to perform read-only checks; use a consistent offline backup for isolated verification.

## Local read-only HTTP API

Generate a secret token and keep it outside source control (for example, in your shell's secret environment configuration). The API **requires** a bearer token of at least 32 characters on every request, including health checks. The CLI validates that the token and port are acceptable before initializing a missing database; a refused listener does not create storage.

```sh
export GOREE_CHANGELOGS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
goree-changelogs serve --port 8765
```

In a separate shell with the same token:

```sh
curl -H "Authorization: Bearer $GOREE_CHANGELOGS_API_TOKEN" \
  "http://127.0.0.1:8765/v1/entries?product=goreecloud-mesh&limit=100"
```

Endpoints: `GET /health`, `GET /v1/entries`, and `GET /v1/search?q=sync` (literal case-insensitive search across product, version, title, description and author) with optional `product`, `version`, and `limit` (1–1000). List and search endpoints support `offset` (0–1,000,000) for bounded pagination and return `limit`, `offset`, and a conservative `has_more` flag (a full page may still be the final page). The API also exposes `GET /v1/summary` for aggregate counts by change kind and product (optional `product` filter). The server binds **only to 127.0.0.1**. It does not provide cross-origin browser access or write endpoints. The standard listener caps active connections at 16, returns HTTP 503 when saturated, closes idle sockets after eight seconds, and rejects request targets longer than 4,096 characters (HTTP 414). These are local resource limits, not authorization, DDoS immunity, or a license to expose the service externally. Do not expose it through an unauthenticated reverse proxy or tunnel. Token access is not equivalent to GoreeCloud Identity integration.

## Optional local web viewer

Use the existing token-authenticated loopback API with `--web` to enable the included accessible, responsive GoreeCloud UI-style changelog browser:

```sh
export GOREE_CHANGELOGS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
goree-changelogs serve --web --port 8765
```

Open `http://127.0.0.1:8765/` on **the same computer**, then paste the token. The UI supports viewing, searching, filtering, and paging records, browsing grouped releases, and opening one release's changes. It aborts and invalidates stale requests on disconnect, mode changes, and refresh so late responses cannot repopulate a cleared session. Its small offline semantic-color bridge references verified `GoreeCloud/gc-ui` alpha tokens; full design-system migration and device/browser acceptance remain open. It is **read-only**: add/edit/delete stay in the CLI. The page itself is unprivileged static HTML; API data always requires the bearer token. The token is held in browser-tab memory, never placed in a URL or local storage. The UI is not published to the public internet and no remote web access is enabled.

The API also supports authenticated `GET /v1/entries/{id}` to view a specific entry, in addition to the existing list, search and summary routes. All HTTP write methods remain disabled. HTTP is restricted to `127.0.0.1`; never expose this service over a tunnel or reverse proxy without a reviewed encrypted, authenticated gateway and GoreeCloud Identity/privilege design.

## Optional Android reader (source preview)

The `android-app/` directory contains a native Android Java/SDK app with no third-party runtime libraries. It reads from the same authenticated, **read-only** API; it does not require a GoreeCloud cloud account. The current local-only connection is intended for developers using an authorized USB-connected device or emulator:

```sh
adb reverse tcp:8765 tcp:8765
goree-changelogs serve --port 8765
```

Install/run the Android source with Android Studio and the installed Android SDK, then provide the API token in-app. The app contacts **only** `127.0.0.1:8765` and does not persist the token. Android does not access your host's loopback port without a configured reverse tunnel. Remote cellular/Wi-Fi access, secure Identity integration, and signed Android release builds are not implemented. See [android-app/README.md](android-app/README.md).

## Tests

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Production readiness gates

This repository remains a development release until the following gates are evidenced:

- [x] Local CLI/API regression suite, SQLite integrity checks, and authenticated loopback API tests
- [x] GitHub Actions Android debug source compilation (Gradle 8.9 / SDK 35 / JDK 17); device acceptance remains open
- [x] Verified consistent backup snapshots under a concurrent-writer test, including WAL-mode snapshot cleanup
- [x] Recovery snapshot, collision rejection, and invalid-source preservation regression tests
- [ ] Verify interruption and crash recovery, including database restore failure injection
- [ ] Validate exclusive maintenance procedures for restore (stop writers, take recovery snapshot, verify rollback)
- [ ] Review file and directory permissions, backup retention, encryption at rest, and secret handling in the intended deployment
- [ ] Complete threat modeling, dependency/supply-chain review, and performance/load evaluation
- [ ] Confirm all supported Python CI versions pass on the final release commit
- [ ] Perform an authorized staging deployment, monitoring/alerting verification, and rollback drill before production approval

A passing test suite is not proof of deployment safety or authorization to change production systems.

## Roadmap

- Extend the loopback read-only API with scoped authorization, audited writes, and GoreeCloud Identity integration
- Expand the implemented local web viewer into a scoped, audited editing client after authentication review
- Expand the implemented Android read-only client after Android build/device validation and secure remote-access design
- Backups, restore, import, migrations and retention controls
- GoreeCloud Mesh integration, GoreeCloud Identity access controls, GoreeShield privacy governance and Wardveil security review

No MIPS integration or remote service is currently claimed.

## Security

The CLI uses local SQLite without application-level encryption. Newly created database files use owner-only permissions (`0600` on POSIX systems), and new immediate containing directories default to `0700`; permissions on existing databases and directories are not automatically changed. Direct symlink parents are refused, but this does not replace a full ancestor-path/ACL audit. Protect containing directories and existing files with OS permissions, disk encryption, and backups. Never put secrets into changelog metadata. Do not expose the database publicly. This is a development baseline, not a security-certified release.

## License

MIT. See [LICENSE](LICENSE).
