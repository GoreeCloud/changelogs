# GoreeCloud Changelogs — Self-hosted VPS / Local Server (v1.1 development)

**Status: experimental source; one owner-operated HTTPS development instance was verified November 14, 2026 at changelogs.goreecloud.com, but no Stable hosted release is certified.** The immutable v1.0.0 GitHub release is limited to a local CLI/read-only API. The intended product is a centrally stored Changelogs server on an authorized GoreeCloud VPS or an owned local server later, with accounts and a common API for CLI, web and Android. This is a development-operations runbook; the observed owner-operated service does not establish general production readiness or a published stable hosted package.

## Architecture

```text
CLI with --server        Browser with HTTPS login       Android HTTPS login
        \                      |                         /
         \---- validated HTTPS/TLS ingress (GoreeCloud Gateway or reviewed proxy)
                                |
                      127.0.0.1:8876 (self-hosted Python server)
                                |
                 +--------------+---------------+
                 |                              |
      changelogs.sqlite3                accounts.sqlite3
      entries and releases              users, hashed passwords,
                                       expiring/revocable sessions
```

One host is the source of truth for entries. `goree-changelogs --server https://approved-host add ...` performs a direct POST to that authoritative database; the web and Android apps read the same entries. The local-only CLI remains available without `--server`. **No automatic background sync** of disconnected local CLI databases is claimed, and local CLI entries do not appear remotely unless created in remote mode or subsequently migrated.

Local accounts are an interim first-party self-hosted authentication mode. GoreeCloud Identity OIDC SSO, MFA, account federation, and centralized revocation are planned but cannot be claimed: GoreeCloud Identity and Gateway currently have development-only integration and no authorized production login ingress. Do not expose their development Keycloak configuration.

## Deployment prerequisites

Before any VPS installation, independently verify the selected hostname, DNS ownership, available network ports, approved TLS certificate and renewal, server OS and security updates, service account, storage mount, disk encryption/ACLs, backups, and rollback method. Avoid interfering with GoreeCloud VPS migration, stopped Docker containers or existing ingress services. Use a dedicated unprivileged service identity. **Never forward the Python service port directly to the public internet.**

Requirements: Python 3.10–3.13, a controlled package install, and a reviewed HTTPS ingress. The v1.1-dev branch/package is not a published stable server release. Install in a private virtual environment from a reviewed commit only after staging acceptance.

## First local operator bootstrap

The following paths are *examples*, not evidence of installation:

```sh
# Install reviewed development version on an authorized staging host.
python3 -m venv /opt/goreecloud/changelogs/.venv
/opt/goreecloud/changelogs/.venv/bin/python -m pip install .
# Prompt interactively. No password is accepted in process arguments or files.
goree-changelogs host init --data-dir /var/lib/goreecloud/changelogs --username admin
# A separate reviewed HTTPS reverse proxy should reach only this loopback listener:
GOREE_CHANGELOGS_PUBLIC_ORIGIN=https://YOUR-APPROVED-CHANGELOGS-HOST \
  goree-changelogs host serve --data-dir /var/lib/goreecloud/changelogs --port 8876
```

Run `host init` under the final unprivileged service user, not root. Additional accounts can be managed only through the host CLI, **not** public self-registration:

```sh
goree-changelogs host user-add --data-dir /var/lib/goreecloud/changelogs --username viewer --role reader
goree-changelogs host user-add --data-dir /var/lib/goreecloud/changelogs --username operator --role admin
goree-changelogs host user-password --data-dir /var/lib/goreecloud/changelogs --username viewer
goree-changelogs host user-remove --data-dir /var/lib/goreecloud/changelogs --username viewer
```

Reader accounts can view the server history but cannot create, edit or delete entries. Authentication preserves per-account persistent lockouts and caps records for never-provisioned usernames at 256; registered-account lockouts are not removed by this cap. This bounds authentication metadata growth but is not a network-level rate limit or a defense against sustained CPU-heavy login floods; enforce appropriate Gateway limits without collecting unnecessary client information. Password rotation revokes all existing account sessions; deleting an account revokes sessions and refuses to remove the final administrator. Provisioning and password rotation use interactive prompts, not arguments. This command creates `changelogs.sqlite3` and `accounts.sqlite3` (both owner-only on POSIX). The immediate data directory must be owner-only, and the account database will refuse startup with group/other permission bits. There is no public self-signup, sample admin password, or password in a source-controlled configuration.

The server always binds `127.0.0.1` even if provided an external origin. The `--origin` setting supplies the exact HTTPS origin for browser CSRF validation; it **does not** enable TLS. Configure the HTTPS reverse proxy independently and verify trusted certificates and access logs omit secrets.

An example `systemd` unit and reverse proxy route are in `ops/` for operator review; neither is installed automatically.

## Read-only staging and startup diagnostics

Before and after any authorized host rollout, run the non-mutating two-database preflight as the service identity:

```sh
goree-changelogs host doctor --data-dir /var/lib/goreecloud/changelogs
```

A successful report verifies private changelog and account storage, SQLite integrity/schema and entry metadata, valid local accounts and an administrator, plus limited aggregate counts. Failures return nonzero with sanitized error types, without usernames, tokens, raw changelog content or file paths. The example systemd unit also includes this command as an `ExecStartPre` safety check. It is a local host diagnostic, not a public unauthenticated health endpoint, a penetration test, or production deployment approval. SQLite itself may interact with WAL sidecars while reading.

## Web sign-in

Visit `https://YOUR-APPROVED-CHANGELOGS-HOST/` after the gateway, TLS and backend are verified. Enter the locally bootstrapped username/password. The server sets a `Secure; HttpOnly; SameSite=Strict` host-only session cookie (12-hour absolute lifetime); the frontend does not store account passwords or tokens in local/session storage. A CSRF token is delivered through the authenticated same-origin API and required on browser writes and logout. Administrators can create changes in the web app; reader accounts cannot modify history. The browser can browse all changes or group releases by product and version, inspect counts by change type, search and paginate, and drill down into the selected release's entries. The UI renders user-supplied release text as plain content rather than HTML. Release views are not automatically synchronized offline.

Use a modern browser; login over plain HTTP from a remote device is unsupported. Session logout revokes the web token server-side. The browser temporarily blocks another sign-in while logout is in flight so a late cookie-clearing response cannot invalidate a new session; the logout request has an eight-second abort deadline. If revocation cannot be confirmed, the page explicitly says so. This is a browser-session ordering safeguard, not proof that an interrupted server-side revocation succeeded.

## CLI direct writes and reads

After a trusted HTTPS endpoint exists:

```sh
# Login prompts for password and prints a short-lived token once.
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST login --username admin
# Supply the token securely in this shell (never in shell history or repository):
export GOREE_CHANGELOGS_REMOTE_TOKEN='<TOKEN_FROM_LOGIN>'
# Write directly to the authoritative database, rather than local SQLite:
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST add mesh 1.0.0 fixed "Resolved gateway issue"
goree-changelogs --server https://YOUR-APPROVED-CHANGELOGS-HOST list --product mesh
```

A trusted environment variable `GOREE_CHANGELOGS_SERVER_URL` may set the default server origin. Every supported CLI command (add, list, search, summary, releases, show, edit, delete) routes to the server when that setting is present. `--db` and `--server` are mutually exclusive to prevent accidental local/remote writes. Backup/restore/export/import are **local maintenance-only** and not transparently redirected. Access tokens are held in process environment, not persisted by the CLI; rotate/revoke sessions when necessary.

## Android preview

The default Android launcher shows an HTTPS server address, username and password. After authentication it fetches entry pages from the same server. The app does not use Android WebView or bypass TLS verification; token and password are not saved to disk. It remains an **unsigned preview**, not a stable app. Android sign-out now clears credentials locally immediately and attempts server-side revocation; if offline, the token remains valid until expiry and the user is informed. Test physical hardware and certificate rejection before relying on it.

## Migration to a different VPS or future owned local server

Plan an authorized maintenance window and **stop all writers and the application**. Back up both SQLite files *consistently* using SQLite's backup API (not raw copying while active). Verify page-level integrity, restore to a separate disposable staging target first, and preserve permissions/ownership. The two-file set must be migrated together to preserve entries and user accounts/sessions. Clear/revoke old sessions when transferring trust domains. Reconfigure and verify public HTTPS URL, DNS, certificate renewal, gateway route and app connections before switching traffic. Keep the source system intact for rollback until a verified backup/restore and acceptance.

The v1.1 development CLI supports a separately verified **paired** backup and a no-clobber staging action, without modifying or restarting the serving instance. First stop all writers before creating a coherent account/changelog backup pair; do not use `--offline-ack` while the service is running.

```sh
goree-changelogs host backup --data-dir /var/lib/goreecloud/changelogs --destination /private/backups/snapshot-1 --offline-ack
goree-changelogs host verify-backup --source /private/backups/snapshot-1
# The destination must NOT already exist and its parent must be owner-only.
goree-changelogs host stage-restore --source /private/backups/snapshot-1 --destination /private/recovery/new-host-data
goree-changelogs host doctor --data-dir /private/recovery/new-host-data
```

Staging creates two private databases (0700 directory, 0600 files on POSIX), verifies each copied database against the backup SHA-256 manifest and runs independent account/changelog checks. Backup sessions are deliberately absent, so users must sign in again after any future, separately approved cutover. On an error, the new incomplete staging directory is left for manual inspection; an existing destination is never overwritten. This command **does not** activate or replace a live server, alter active accounts, or prove interruption/crash resilience. The v1.0.0 entry-only `verify-backup` remains distinct from the v1.1 development paired-host commands. Live cutover, interrupted-operation rollback, and full account recovery remain release gates.

## Remaining acceptance gates

- Real authorized VPS staging install with isolated service user, verified storage/ACL/encryption, HTTPS DNS and certificate renewal
- Admin password lifecycle, bootstrap recovery, rate limiting and incident response; later GoreeCloud Identity OIDC/MFA integration
- Real browser end-to-end sign-in, cookie/CSRF, logout, same-origin and accessibility verification
- Real Android HTTPS login, certificate pinning policy (if adopted), server revocation, and UI/accessibility QA
- Concurrent writers, migration compatibility, load tests, storage capacity, backup/restore and rollback under actual interruption
- Live Gateway and GoreeCloud Mesh interoperability and Wardveil review under GoreeShield privacy requirements
- Signed and tagged stable server/mobile releases after all relevant validation

**CI evidence is source-level only. No production host, domain or device has been modified by this repository change.**
