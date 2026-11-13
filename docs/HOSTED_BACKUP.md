# Self-hosted Changelogs backup pair — v1.1 development

This is an **offline maintenance** procedure for a self-hosted VPS or future private server. It does not deploy any service, restart any production process or perform a restore. The public v1.0.0 release is separate and does not include this hosted feature.

## What is backed up?

The hosted service uses two different SQLite databases in one private data directory: `changelogs.sqlite3` stores entries/releases and `accounts.sqlite3` stores locally managed user roles/password hashes and revocable session hashes.

A hosted backup must preserve **both** databases. The command creates a new owner-only directory with:

- `changelogs.sqlite3` — a consistent SQLite snapshot of the changelog records
- `accounts.sqlite3` — an account snapshot with **all sessions deliberately deleted**; after restoration users sign in again
- `manifest.json` — nonsecret counts, UTC time and SHA-256 checksums for both files

All files and the new directory use owner-only POSIX permissions. Backups never replace an existing destination. An interrupted operation may leave an **incomplete backup directory**; it must fail verification and should be investigated before manually retiring it. The tool does not delete it automatically.

## Mandatory safety preconditions

**Stop all writers and the hosted service before taking the pair.** SQLite's online backup API makes each individual database snapshot consistent, but snapshots of two files are **not one cross-database transaction**. The `--offline-ack` option means you have independently verified the service is stopped; it does **not** stop it for you. Use a separately authorized maintenance window with a tested rollback plan.

Ensure the source changelog DB, account DB and containing directories are private and not symbolic links. Pre-create a private backup **parent** with an appropriate unprivileged service account and encrypted storage:

```sh
umask 077
mkdir -m 700 -p /var/backups/goreecloud-changelogs
```

Review ownership, encrypted storage, filesystem snapshots, retention and any external backup provider before deployment. The backup contains account password hashes and private changelog content, so treat it as sensitive even though session hashes are removed.

## Create a new immutable backup directory

```sh
goree-changelogs host backup \
  --data-dir /var/lib/goreecloud/changelogs \
  --destination /var/backups/goreecloud-changelogs/backup-2026-11-13 \
  --offline-ack
```

The output reports row/user counts and hashes; it does not print user names, passwords, raw records or tokens. The destination must not already exist, and its parent must be owner-only.

## Verify without making changes

```sh
goree-changelogs host verify-backup \
  --source /var/backups/goreecloud-changelogs/backup-2026-11-13
```

Verification checks the expected file manifest, SHA-256 hashes, private permissions, SQLite integrity, strict changelog schema and metadata, account tables/indexes, foreign-key integrity, valid user roles and the presence of an administrator. Any unexpected file, modified byte, missing half of the pair, unauthorized permissions or backup session will be rejected.

## Restoring or migrating to a new VPS / home server

Do **not** directly copy live WAL-mode SQLite files. Stop source and destination services and first verify the backup pair and independently restore to a disposable test directory, then test administrator login and several representative changelogs. Account sessions will not survive migration by design. Only a separately reviewed operational plan should replace the authoritative databases, reconnect the HTTPS domain, and resume writers.

This command does not yet automate combined restores; that is a deliberate release gate to prevent accidental overwrites of service identity. It also does not validate external disk encryption, backup retention, host ACLs, long-term cryptographic signatures or production power-loss recovery.

GoreeShield governs minimization and backup privacy; Wardveil reviews security and incident response; GoreeCloud Mesh coordinates connectivity; GoreeCloud UI governs web-client design. A successful CI backup simulation does not certify an actual VPS deployment.
