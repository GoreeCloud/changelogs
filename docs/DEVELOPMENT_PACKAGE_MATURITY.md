# Changelogs package maturity classifier — November 13, 2026

The original **v1.0.0** scope remains a separately released local CLI plus token-authenticated loopback read-only API. It is not retroactively downgraded by this note.

The currently developed **1.1.0.dev0** source tree also contains an experimental hosted web/API service and Android preview outside the v1.0 stable acceptance scope. Its `pyproject.toml` previously declared `Development Status :: 5 - Production/Stable` for that entire development package, which overstated maturity despite the README's explicit development warning.

This narrowly scoped source-only correction sets the prerelease package classifier to **Alpha** and updates its package description accordingly. A Python 3.10-compatible regression test ensures future prerelease metadata cannot silently claim a Stable classifier. The code, database, hosting, release tag and CI deployment configuration are unchanged.

This is **metadata honesty and release hygiene**, not a runtime reliability fix, signed release, staging deployment, backup/restore acceptance, or proof that hosted service isolation and mobile clients are safe. The relevant hosting recovery, staging and crash-injection Todoist gates remain open.
