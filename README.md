# GoreeCloud Changelogs

Self-hosted, local-first changelog management for applications, services, APIs, and infrastructure.

**Status:** 0.1.0 development CLI. A read-only, loopback HTTP API is available for local integrations. Web and Android clients are planned, not implemented or deployed.

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

Database defaults to `~/.local/share/goreecloud/changelogs.sqlite3`. Set `GOREE_CHANGELOGS_DB` or global `--db` to override. SQLite stores entries with product, version, kind, title, description, author, release date, JSON metadata, and creation/update timestamps. Filtering by product and version is supported.

## Backups and recovery

Create a consistent SQLite backup without overwriting an existing file:

```sh
goree-changelogs backup ./snapshot.sqlite3
goree-changelogs verify-backup ./snapshot.sqlite3
```

Preflight a restore without creating or modifying the live database:\n\n```sh\ngoree-changelogs restore ./snapshot.sqlite3 --dry-run\n```\n\nRestore from a validated backup (replaces all current entries; back up the live database first):

```sh
goree-changelogs restore ./snapshot.sqlite3 --yes --recovery-backup ./before-restore.sqlite3
```

Backups are checked for SQLite integrity and compatible entry columns. `verify-backup` performs a non-mutating check and prints JSON containing `valid` and `entries`; it does not initialize a live database. A dry run validates the source and reports its entry count but does not lock the live database or guarantee that a subsequent restore will succeed. The restore command requires explicit confirmation. The optional `--recovery-backup` creates a validated, non-overwriting snapshot of the current database before replacing records. This is not an automatic rollback mechanism, and concurrent writers must be stopped during recovery. These commands operate on the selected local database; no remote backup or cloud synchronization is implied.

## Local read-only HTTP API

Generate a secret token and keep it outside source control (for example, in your shell's secret environment configuration). The API **requires** a bearer token of at least 32 characters on every request, including health checks.

```sh
export GOREE_CHANGELOGS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
goree-changelogs serve --port 8765
```

In a separate shell with the same token:

```sh
curl -H "Authorization: Bearer $GOREE_CHANGELOGS_API_TOKEN" \
  "http://127.0.0.1:8765/v1/entries?product=goreecloud-mesh&limit=100"
```

Endpoints: `GET /health`, `GET /v1/entries`, and `GET /v1/search?q=sync` (literal case-insensitive search across product, version, title, description and author) with optional `product`, `version`, and `limit` (1–1000). List and search endpoints support `offset` (0–1,000,000) for bounded pagination and return `limit`, `offset`, and a conservative `has_more` flag (a full page may still be the final page). The API also exposes `GET /v1/summary` for aggregate counts by change kind and product (optional `product` filter). The server binds **only to 127.0.0.1**. It does not provide cross-origin browser access or write endpoints. Do not expose it through an unauthenticated reverse proxy or tunnel. Token access is not equivalent to GoreeCloud Identity integration.

## Tests

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Production readiness gates

This repository remains a development release until the following gates are evidenced:

- [x] Local CLI/API regression suite, SQLite integrity checks, and authenticated loopback API tests
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
- Optional GoreeCloud UI-based responsive web application
- Optional Android application sharing the API
- Backups, restore, import, migrations and retention controls
- GoreeCloud Mesh integration, GoreeCloud Identity access controls, GoreeShield privacy governance and Wardveil security review

No MIPS integration or remote service is currently claimed.

## Security

The CLI uses local SQLite without application-level encryption. Newly created database files use owner-only permissions (`0600` on POSIX systems); permissions on existing databases are not automatically changed. Protect containing directories and existing files with OS permissions, disk encryption, and backups. Never put secrets into changelog metadata. Do not expose the database publicly. This is a development baseline, not a security-certified release.

## License

MIT. See [LICENSE](LICENSE).
