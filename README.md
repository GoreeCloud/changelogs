# GoreeCloud Changelogs

Self-hosted, local-first changelog management for applications, services, APIs, and infrastructure.

**Status:** **1.0.0 stable source scope — local CLI and token-authenticated 127.0.0.1 read-only API only.** The optional `serve --web` viewer and native Android reader are **experimental previews**, expressly outside stable support. No production host deployment, remote-access gateway, or Android release is included. See [v1.0.0 release scope](docs/releases/v1.0.0.md) and the separate deployment acceptance gates below.

## Install

Python 3.10+:

```sh
python -m pip install .
goree-changelogs --help
```

## Self-hosted server — v1.1 development

**Docker Compose-first development path (Linux only):** [Docker Compose hosted deployment guide](docs/self-hosted-compose.md) stages the v1.1 server without publishing its loopback port. This is an **unreleased development deployment option**, not a production-ready or v1.0.0 Stable hosted service. It requires operator-controlled HTTPS ingress, private storage, and separate validation; Podman and other deployment methods remain outstanding.

**This is the intended multi-client deployment model.** One instance runs on your VPS or a local server and stores the authoritative changelogs plus separate local user/session data. The CLI can write directly to that host; the hosted web app signs in with local accounts, displays shared changelogs, and permits administrator-only creation of entries. The browser offers Changes/Releases views, groups by product and version, and drills into one version with change-type counts and bounded pagination; reader accounts are view-only. The Android preview is designed for HTTPS login and read-only shared history on that server. The published v1.0.0 tag is immutable and remains a local CLI/API release; these hosted changes are an unreleased v1.1 development branch.

An operator bootstraps the first administrator locally, then runs the application **bound to 127.0.0.1**, behind independently configured HTTPS/TLS ingress. The server offers no public registration, no default passwords, no insecure external HTTP, no third-party analytics or automatic exports. Authentication uses salted 600,000-iteration PBKDF2-HMAC-SHA256 hashes, generic login errors and a persistent rate limit, with revocable, expiring sessions. The web app uses Secure HttpOnly SameSite cookies and an anti-CSRF token; CLI/Android obtain short-lived bearer sessions. **Do not expose the HTTP listener directly or treat this work as production deployed.**

```bash
# On a selected trusted host, interactive bootstrap (once):
goree-changelogs host init --data-dir /var/lib/goreecloud/changelogs --username admin
# After setting up a reviewed HTTPS reverse proxy:
goree-changelogs host serve --data-dir /var/lib/goreecloud/changelogs \
  --origin https://YOUR-APPROVED-DOMAIN --port 8876

# On a client machine: obtain a short-lived token (do not commit/store in a file):
goree-changelogs --server https://YOUR-APPROVED-DOMAIN login --username admin
# Supply that token securely via GOREE_CHANGELOGS_REMOTE_TOKEN:
goree-changelogs --server https://YOUR-APPROVED-DOMAIN add mesh 1.0.0 added "Feature launched"
```

See [self-hosted installation, client access and migration](docs/HOSTED_SERVER.md) for safe operational prerequisites. Hosting on an owned VPS or physical server is supported by the same service design; changing locations requires a reviewed database and account backup/restore, not a new cloud account.

## Self-hosted staging preflight

The v1.1 development CLI provides `goree-changelogs host doctor --data-dir
HOST-DATA`, a read-only privacy/schema/account audit with sanitized JSON and
a failing exit status on invalid storage. It runs before the host listener in
the reviewed example service unit; no production service is installed by CI.

## Hosting backups, accounts and future server migration

The **v1.1 development** hosted service stores changelog entries and local
account/session information in separate SQLite files. Once the hosted service
has been **stopped and its writers quiesced**, `goree-changelogs host backup
--data-dir HOST-DATA --destination NEW-PRIVATE-DIRECTORY --offline-ack`
creates a verified, no-overwrite pair and clears sessions from the account
backup. `goree-changelogs host verify-backup --source DIRECTORY` performs
read-only validation. An actual server restore/deployment is not automated.
See [self-hosted backup and recovery boundaries](docs/HOSTED_BACKUP.md).

## Bringing older local CLI entries onto the hosted server

Previously created local SQLite entries are not automatically uploaded. The new
`goree-changelogs --server https://APPROVED-HOST migrate --source LOCAL.sqlite3`
command previews them without network access, then supports SHA-256-pinned
and explicitly confirmed HTTPS migration to the authoritative server. Each
batch is validated transactionally and duplicates can be retried safely.
See [legacy CLI migration](docs/HOSTED_MIGRATION.md).

## Usage

```sh
goree-changelogs add goreecloud-mesh 0.1.0 added "Initial sync engine" --description "Local-first synchronization" --author GoreeCloud
goree-changelogs list --product goreecloud-mesh --kind security --limit 50 --offset 0
goree-changelogs search "synchronization" --product goreecloud-mesh --kind fixed
goree-changelogs summary --product goreecloud-mesh
goree-changelogs show 1
goree-changelogs edit 1 --description "Updated release details"
goree-changelogs export --format markdown --output CHANGELOG.md
goree-changelogs export --format json --output changelogs.json
goree-changelogs delete 1
```

Deletion requires typing `delete` interactively, or explicitly passing `--yes` for automation. Malformed add/edit inputs and refused or cancelled deletes are rejected before the CLI initializes storage in an otherwise missing database location. Back up the database before deletion.

Database defaults to `~/.local/share/goreecloud/changelogs.sqlite3`. Set `GOREE_CHANGELOGS_DB` or global `--db` to override. SQLite stores entries with product, version, kind, title, description, author, release date, JSON metadata, and creation/update timestamps. Filtering by product, version and **change kind** (e.g., `added`, `fixed`, `security`) is supported on list; search supports optional product and kind filters. JSON metadata is a strictly parsed object; duplicate keys, NaN/Infinity, non-JSON values and metadata larger than 64 KiB are rejected before insertion or update.

## Release notes and version history

View all versions grouped by product, or filter one application/service. Release groups are ordered by latest recorded release date; versions are treated as literal strings (not assumed to follow semantic versioning):

```sh
goree-changelogs releases --product goreecloud-mesh --limit 25 --offset 0
goree-changelogs release-notes goreecloud-mesh 0.1.0
goree-changelogs release-notes goreecloud-mesh 0.1.0 --format json
goree-changelogs release-notes goreecloud-mesh 0.1.0 > RELEASE_NOTES.md
```

The `releases` command reports each version's earliest and latest recorded release date, entry count, and counts by change kind. `release-notes` groups individual changes in familiar Added/Changed/Deprecated/Removed/Fixed/Security sections, escaping content as literal Markdown text to prevent accidental rendered HTML. A missing version or release larger than 10,000 entries fails rather than silently returning incomplete notes. The loopback API adds authenticated `GET /v1/releases?product=...&limit=...&offset=...`, keeping all endpoints read-only. Release notes contain whatever product names, authors and descriptions you recorded—review before publishing them.

## Complete, private exports

Export is **complete by default**. It either returns all matching entries that fit in one file or refuses the operation without printing a partial document. Portable JSON exports validate each record against the importer contract and must fit within **5,000 entries and 8 MiB**. Markdown defaults to a 10,000-entry ceiling. For larger collections use explicit bounded chunks (preferably from a consistent offline SQLite backup so concurrent insertions cannot shift offsets):

```sh
goree-changelogs export --format json --limit 3000 --offset 0 --output part-1.json
goree-changelogs export --format json --limit 3000 --offset 3000 --output part-2.json
```

An explicitly supplied `--limit` opts into **partial** output; `--offset` is valid only with `--limit`. Adjust the chunk size if an export still exceeds 8 MiB. To avoid shell redirection creating an empty file on validation failure, prefer `--output FILE`: it writes a same-directory, owner-only temporary file, fsyncs it, and atomically installs the destination without overwriting existing files. The containing directory is created private when new; existing directory permissions are left unchanged. Output contains recorded product names, authors and descriptions—review before publishing. Chunks may be imported separately using preview-first JSON import and its SHA-256 pin.

## Portable JSON import (preview-first)

Export your entries to inert UTF-8 JSON. Preview a JSON import **without creating a database** and then explicitly opt in to adding validated entries:

```sh
goree-changelogs export --format json --output changelogs.json
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

Endpoints: `GET /health`, `GET /v1/entries`, and `GET /v1/search?q=sync` (literal case-insensitive search across product, version, title, description and author) with optional `product`, `version`, and `limit` (1–1000). List and search endpoints support `offset` (0–1,000,000) for bounded pagination and return `limit`, `offset`, and an **exact, lookahead-backed** `has_more` indicator for the queried snapshot. An exactly full last page reports false. The same applies to grouped `/v1/releases` responses. Beyond the maximum supported offset there is no navigable next page. Like all offset pagination, independently requested pages can drift if another process edits the database between requests; export a consistent SQLite backup for immutable history. List and search API queries additionally accept `kind=added|changed|fixed|removed|security|deprecated|other`; invalid values fail with HTTP 400 and grouped release/summary endpoints reject this parameter. The optional web viewer includes a keyboard-accessible change-type selector. The API also exposes `GET /v1/summary` for aggregate counts by change kind and product (optional `product` filter). The server binds **only to 127.0.0.1**. It does not provide cross-origin browser access or write endpoints. The standard listener caps active connections at 16, returns HTTP 503 when saturated, closes idle sockets after eight seconds, and rejects request targets longer than 4,096 characters (HTTP 414). These are local resource limits, not authorization, DDoS immunity, or a license to expose the service externally. Do not expose it through an unauthenticated reverse proxy or tunnel. Token access is not equivalent to GoreeCloud Identity integration.

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

## Distribution smoke verification

GitHub Actions additionally builds and installs a wheel, then tests the installed CLI, database lifecycle, release notes, JSON portability and token-protected web/API resources from **outside the source checkout**. This catches missing bundled web assets and packaging regressions that source-tree unit tests alone can miss. It does not certify Android hardware behavior or a production deployment.

## Stable source release and deployment boundaries

The supported **v1.0.0 source release** consists of the locally installed Python CLI, SQLite storage and recovery commands, and the single-host bearer-token read-only HTTP API. Release checks include Python 3.10–3.13 on Linux, a built-and-installed wheel, API method/authentication tests, disposable restore fault injection and a separate release-branch gate. The package requires no third-party runtime dependencies. The Android reader and opt-in web viewer remain unpromoted previews even though they ship as source/bundled files; they must not be advertised as stable clients. Source distribution is distinct from deployed production readiness.

**Unmet host-specific deployment gates:** actual authorized target-machine staging, filesystem/ACL/ownership and encryption review, incident/monitoring verification, physical power-loss and maintenance-window restore/rollback drill, real web browser/Android acceptance, and hardened branch ruleset enforcement. These are not waived by a successful source release. No server is installed, exposed or restarted by the GitHub release process.

Before operating on real data, make a validated recovery snapshot and verify database permissions. Do not expose the API beyond `127.0.0.1`. See [the release notes and boundaries](docs/releases/v1.0.0.md) and [read-only staging acceptance](docs/STAGING_READ_ONLY_ACCEPTANCE.md).

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
