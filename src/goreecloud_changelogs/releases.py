"""Read-only, bounded release-level summaries and notes.

All SQL identifiers are fixed and user-supplied product/version values are bound.
No schema migration or release ordering inference from version strings.
"""
import re

KINDS_ORDER = ("added", "changed", "deprecated", "removed", "fixed", "security", "other")
COUNT_FIELDS = ", ".join(
    f"SUM(CASE WHEN kind = '{kind}' THEN 1 ELSE 0 END) AS n_{kind}"
    for kind in KINDS_ORDER
)


def _validate_pagination(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Release limit must be between 1 and 1000")
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("Release offset must be between 0 and 1000000")


def list_releases(store, product=None, limit=100, offset=0):
    """Group entries by (product, version), ordering by latest release date."""
    _validate_pagination(limit, offset)
    return _grouped_releases(store, product, limit, offset)


def page_releases(store, product=None, limit=100, offset=0):
    """Return an exact continuation indicator from one grouped read."""
    _validate_pagination(limit, offset)
    rows = _grouped_releases(store, product, limit + 1, offset)
    return rows[:limit], len(rows) > limit and offset + limit <= 1000000


def _grouped_releases(store, product, limit, offset):
    if product is not None and not isinstance(product, str):
        raise ValueError("Product must be text")
    where = " WHERE product = ?" if product is not None else ""
    params = (product,) if product is not None else ()
    sql = (
        "SELECT product, version, MIN(released_at) AS first_released_at, "
        "MAX(released_at) AS released_at, COUNT(*) AS entries, " + COUNT_FIELDS +
        " FROM entries" + where + " GROUP BY product, version "
        "ORDER BY released_at DESC, product ASC, version ASC LIMIT ? OFFSET ?"
    )
    with store.connect() as db:
        rows = db.execute(sql, (*params, limit, offset)).fetchall()
    return [{
        "product": row["product"], "version": row["version"],
        "first_released_at": row["first_released_at"],
        "released_at": row["released_at"], "entries": row["entries"],
        "by_kind": {kind: row["n_" + kind] for kind in KINDS_ORDER
                    if row["n_" + kind] > 0},
    } for row in rows]


def release_details(store, product, version):
    """Render exactly one bounded release; fail rather than silently truncate."""
    for name, value in (("product", product), ("version", version)):
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ValueError(f"{name} must have 1 to 256 nonblank characters")
    with store.connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM entries WHERE product = ? AND version = ?",
            (product, version)
        ).fetchone()[0]
    if not count:
        raise ValueError("Release not found")
    if count > 10000:
        raise ValueError("Release exceeds 10000 entries; use filtered export")
    rows = store.list(product=product, version=version, limit=10000, offset=0)
    return {
        "product": product, "version": version,
        "released_at": max(row["released_at"] for row in rows),
        "entries": rows,
    }


def _plain_markdown(value):
    """Escape untrusted plain text rather than interpreting HTML or Markdown."""
    text = str(value).replace("&", "&amp;")
    return re.sub(r"([\\`*_{}\[\]()#+.<>!|~-])", r"\\\1", text)


def markdown_release(release):
    """Keep a Changelog-style sections in a single release notes document."""
    title = f"# {_plain_markdown(release['product'])} {_plain_markdown(release['version'])}"
    output = [title, "", f"Release date: {_plain_markdown(release['released_at'])}", ""]
    for kind in KINDS_ORDER:
        matching = [item for item in release["entries"] if item["kind"] == kind]
        if not matching:
            continue
        output.extend([f"## {kind.capitalize()}", ""])
        for item in matching:
            output.append("- **" + _plain_markdown(item["title"]) + "**")
            if item["description"]:
                for line in item["description"].splitlines():
                    output.append("  " + _plain_markdown(line))
            if item["author"]:
                output.append("  Author: " + _plain_markdown(item["author"]))
        output.append("")
    return "\n".join(output).rstrip() + "\n"
