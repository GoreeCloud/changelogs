# Docker Compose — hosted Changelogs development deployment

| Metadata | Value |
| --- | --- |
| Product | GoreeCloud Changelogs |
| Status | Experimental **v1.1 hosted development preview**; **not** the v1.0.0 Stable CLI/API scope and **not production accepted** |
| Scope | Docker Compose on a trusted **Linux** host with a separately reviewed HTTPS reverse proxy |
| Last reviewed | November 14, 2026 |
| Repository source | [GoreeCloud/changelogs](https://github.com/GoreeCloud/changelogs) |
| Requirement | Docker Compose first; independently qualified Podman and other deployment paths remain outstanding |

## Why this deployment is restricted

I require Docker Compose as the **first-priority deployment path** for self-hosted GoreeCloud services. This pilot preserves Changelogs' intentionally loopback-bound server: the Python application binds only to `127.0.0.1:8876` and authenticates clients through a public HTTPS origin validated at the application layer. Containers have separate loopback namespaces by default, so this Linux Compose configuration deliberately uses `network_mode: host`. It must **not** be used on an untrusted/shared host or treated as a portable Windows/macOS or Podman installation.

The Compose file **does not publish a port** or provide a TLS proxy. Operate a separately reviewed HTTPS ingress on the same trusted Linux host, proxying to `127.0.0.1:8876`; preserve the expected `Host` and HTTPS origin. Never map `8876` to a public interface, bypass authentication, or expose this development preview as a production service.

## Prerequisites and initial installation

- A trusted Linux host with Docker Engine and the Docker Compose v2 plugin, adequate filesystem permissions, and an explicitly reviewed local HTTPS ingress.
- A **new, empty, private, persistent** host data directory whose effective container ownership is `10001:10001`; never alter ownership or modes of a live Changelogs data directory without a separate review. User-namespace remapping and rootless engines may require different mapped host ownership.
- An exact approved HTTPS hostname for `GOREE_CHANGELOGS_PUBLIC_ORIGIN`; certificates and DNS are configured separately.

For a fresh installation on a **new empty directory only**, an administrator may prepare `/srv/goreecloud/changelogs` using an appropriate privileged host command such as `install -d -m 0700 -o 10001 -g 10001 /srv/goreecloud/changelogs`. Do **not** run this command against an existing data directory.

From the checked-out source:

```sh
cp deploy/compose.env.example .env
# Edit .env: real HTTPS origin and an existing absolute private data directory.
docker compose config --quiet
docker compose build
# Interactive, one-time bootstrap; prompts for a private administrator password.
docker compose run --rm --no-deps changelogs host init --data-dir /data --username admin
# Only after configuring the reviewed HTTPS reverse proxy on this trusted host:
docker compose up -d --no-build
docker compose logs --tail=50 changelogs
```

Do not put passwords, bearer tokens, account databases, or database files in images, Git, environment examples, or Compose configuration. The `.env` file holds **only** the non-secret HTTPS origin and local data path; it is ignored by Git. Keep the host data directory mode `0700` and database files mode `0600`.

## Operation and recovery

Use `docker compose ps` and the application's private diagnostics to inspect health:

```sh
docker compose run --rm --no-deps changelogs host doctor --data-dir /data
docker compose stop
```

Stop all writers before any offline backup, migration, restore or rollback. The existing application-specific `host backup`, `host verify-backup`, and `host stage-restore` commands are the applicable recovery interfaces; read and follow the main Changelogs README before using them. Never treat a container image or a bind mount as a backup. When updating, stage and verify an independent rollback and database recovery plan, then rebuild the image from a reviewed source revision and run controlled acceptance checks before resuming service.

The image runs as a non-root UID and uses a read-only root filesystem, dropped capabilities, no-new-privileges and a private bind mount. Host networking still shares the host network namespace, so it does **not** provide standard container network isolation. Existing GoreeShield privacy, Wardveil cybersecurity, Identity, Mesh, TLS, provenance and release gates remain applicable.

## Evidence and remaining gates

A Compose manifest and image definition do **not** establish that a deployment has started, accepted credentials, served HTTPS or passed recovery. Independent proof is required for clean install, configuration validation, image build, interactive bootstrap, secure storage permissions, localhost-only binding, HTTPS reverse-proxy behavior, authentication failures, account/session lifecycle, upgrades, backups, restores and rollback.

**Podman**, Quadlet, native systemd and other runtime options remain separate implementation and test workstreams; Docker Compose is the first priority, not a reason to omit those alternatives. Do not claim full ecosystem-wide compliance or production readiness based on this development pilot.
