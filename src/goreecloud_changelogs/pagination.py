"""Precise single-statement, bounded API entry pagination.

A one-row lookahead distinguishes an exactly full final page from a page
with a navigable successor; query values remain parameterized.
"""


from .store import KINDS


def entries_page(store, product=None, version=None, query=None, limit=100, offset=0, kind=None):
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("Limit must be between 1 and 1000")
    if type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("Offset must be between 0 and 1000000")
    for name, value in (("product", product), ("version", version)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{name} must be text")
    if kind is not None and kind not in KINDS:
        raise ValueError("Invalid change kind")
    clauses, params = [], []
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise ValueError("Search query must contain 1-256 characters")
        if version is not None:
            raise ValueError("Search cannot filter by version")
        needle = query.strip().lower()
        clauses.append(
            "(instr(lower(product), ?) > 0 OR instr(lower(version), ?) > 0 OR "
            "instr(lower(title), ?) > 0 OR instr(lower(description), ?) > 0 OR "
            "instr(lower(author), ?) > 0)"
        )
        params.extend([needle] * 5)
    for name, value in (("product", product), ("version", version), ("kind", kind)):
        if value is not None:
            clauses.append(name + " = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = ("SELECT * FROM entries" + where +
           " ORDER BY released_at DESC, id DESC LIMIT ? OFFSET ?")
    with store.connect() as db:
        result = db.execute(sql, (*params, limit + 1, offset)).fetchall()
        rows = [store._decode(row) for row in result[:limit]]
    return rows, len(result) > limit and offset + limit <= 1000000
