# GoreeCloud Changelogs

Self-hosted, local-first changelog management for applications, services, APIs, and infrastructure.

**Status:** 0.1.0 development CLI. Web and Android clients are planned, not implemented or deployed.

## Install

Python 3.10+:

```sh
python -m pip install .
goree-changelogs --help
```

## Usage

```sh
goree-changelogs add goreecloud-mesh 0.1.0 added "Initial sync engine" --description "Local-first synchronization" --author GoreeCloud
goree-changelogs list --product goreecloud-mesh
goree-changelogs show 1
goree-changelogs edit 1 --description "Updated release details"
goree-changelogs export --format markdown > CHANGELOG.md
goree-changelogs export --format json > changelogs.json
goree-changelogs delete 1
```

Deletion requires typing `delete` interactively, or explicitly passing `--yes` for automation. Back up the database before deletion.

Database defaults to `~/.local/share/goreecloud/changelogs.sqlite3`. Set `GOREE_CHANGELOGS_DB` or global `--db` to override. SQLite stores entries with product, version, kind, title, description, author, release date, JSON metadata, and creation/update timestamps. Filtering by product and version is supported.

## Tests

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Roadmap

- Authenticated, versioned HTTP API with scoped authorization and audit events
- Optional GoreeCloud UI-based responsive web application
- Optional Android application sharing the API
- Backups, restore, import, migrations and retention controls
- GoreeCloud Mesh integration, GoreeCloud Identity access controls, GoreeShield privacy governance and Wardveil security review

No MIPS integration or remote service is currently claimed.

## Security

The CLI uses local SQLite without application-level encryption. Protect files with OS permissions, disk encryption, and backups. Never put secrets into changelog metadata. Do not expose the database publicly. This is a development baseline, not a security-certified release.

## License

MIT. See [LICENSE](LICENSE).
