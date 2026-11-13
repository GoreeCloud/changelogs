# Migrate existing local CLI changelogs to your self-hosted server

**Applies to v1.1 development source, not published v1.0.0.** No server has been deployed by this document.

This utility migrates existing SQLite changelog entries from a local CLI database into the **single authoritative database on your VPS or later home server**. It is optional. The usual `goree-changelogs --server HTTPS-ORIGIN add ...` writes directly to the server and needs no migration.

## Requirements

The HTTPS self-hosted server must already be accessible through a verified approved reverse proxy. Create a local administrator using `host init`, then sign in on CLI to get a short-lived bearer token for uploads. The migration source must be an **existing** local SQLite database; this operation does not initialize or delete local data.

## Step 1 — Preview, no uploads

```sh
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST \
  migrate --source ~/.local/share/goreecloud/changelogs.sqlite3
```

This prints a row count, number of bounded batches and a SHA-256 fingerprint of the selected records without sending network requests or printing private changelog entries. Review the expected count, source path and target origin.

## Step 2 — Authorize the exact reviewed snapshot

```sh
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST \
  login --username admin
# Provide the printed bearer token securely via an environment variable:
export GOREE_CHANGELOGS_REMOTE_TOKEN='<YOUR-FRESH-TOKEN>'
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST \
  migrate --source ~/.local/share/goreecloud/changelogs.sqlite3 \
  --expect-sha256 <64-CHARACTER-SHA-FROM-PREVIEW> --yes
```

The CLI **re-reads** the local records and refuses to upload if the SHA-256 has changed since preview. Each batch is limited to 100 rows and 60 KiB, is validated atomically on the server, and skips exact duplicates on retry. A multi-batch migration is **not a global transaction**; if a network error occurs after some batches, take a new preview and repeat. Previously imported rows are skipped.

The existing local SQLite database remains untouched. After upload, sign in to the web and Android apps at the same HTTPS origin and verify the expected entries in both.

## Large databases and moving offsets

One preview/export is limited to 5,000 entries and 8 MiB. To migrate more, work from a verified **offline SQLite backup** or otherwise frozen source so concurrent writes cannot shift offset pagination:

```sh
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST \
  migrate --source /path/to/frozen.sqlite3 --limit 500 --offset 0
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST \
  migrate --source /path/to/frozen.sqlite3 --limit 500 --offset 500
```

Review and pin the unique fingerprint printed for **each chunk**, then rerun that same command with `--yes --expect-sha256`. Use smaller limits if one record or total body exceeds server constraints. SQLite row IDs remain local to each database; product, version, dates, kinds, titles, descriptions, authors and metadata are preserved. The remote server has one shared workspace; it is not an isolated account-per-tenant store.

## Security and operational limitations

The preview is read-only SQLite access; SQLite itself may interact with WAL/SHM files if the source uses WAL journal mode. Use a frozen backup for strong immutability. Require a valid OS certificate chain, exact trusted HTTPS origin and short-lived admin token; the client refuses redirects and inherited proxy settings. Data is not end-to-end encrypted within the application beyond TLS and the host's encryption/ACL policy. Do not attach private changelog exports to public issues or backups.

Verify remote counts and restore readiness before deleting any local database. No production VPS deployment, user/account migration, automatic background sync or Android stable release is implied.
