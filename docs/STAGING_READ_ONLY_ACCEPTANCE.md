# GoreeCloud Changelogs — Staging Read-Only Acceptance

**Status:** Source-level rehearsal only. No production or staging host has been certified by this document. Follow current GoreeCloud Instructions, GoreeShield privacy controls and Wardveil security review.

Use after you have independently selected an authorized staging environment and a disposable or approved **existing** database. The command will not create a missing database, modify permissions, restore a backup, run migrations, persist a token or write changelog records.

## Local use

Install the package and run the script from the repository checkout:

```sh
python -m pip install .
python scripts/stage_acceptance.py --db ./authorized-staging.sqlite3
```

To check the optional **loopback-only** read-only API in the same host namespace, start an authorized local instance separately and provide its token through your secret environment management:

```sh
python scripts/stage_acceptance.py --db ./authorized-staging.sqlite3 \
  --api-port 8765
```

The JSON report includes a boolean `passed` and outcomes for SQLite integrity/schema/metadata, filesystem permission audit, and optionally local API bearer authorization, health, read-only rejection, no-store/security headers, entries and release endpoints. Exit status is 0 only when all selected checks pass. The report deliberately excludes database paths, changelog content, token values and raw exception messages. API requests go only to `127.0.0.1`, never a remote hostname, and include a write-method rejection probe with **no body**.

## Limitations

- SQLite read-only connections may involve ordinary locks or WAL sidecar behavior; run against an offline snapshot when strong immutability is required.
- This is not a full ACL/ancestor-directory or encryption review. Check ownership, mount policies, filesystem backups, logging and retention separately.
- Loopback auth tests are **not** GoreeCloud Identity integration, public exposure approval, or a network penetration test.
- A passing report is not evidence of a host power-loss recovery drill, Android device acceptance, a visual/accessibility review, signed app release, or production deployment.
- Never run destructive restore simulations on a live production database. The existing dedicated crash-injection suite uses disposable SQLite files.

Keep release-gate Todoist items open until independent acceptance evidence exists.
