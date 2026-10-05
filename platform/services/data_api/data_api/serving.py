"""Serving registry: publication metadata and per-table row counts.

No customer columns are selected. Table names come from the catalog and
are counted only after an allow-list check.
"""

from __future__ import annotations

from typing import Any

from data_api.db import SERVING_SCHEMAS, count_query, rows, scalar

PUBLICATIONS_SQL = """
SELECT table_name, row_count, content_digest, lineage_run_id, published_at
FROM serving.publication_log
ORDER BY published_at DESC, publication_id DESC
"""

TABLES_SQL = """
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema = ANY(%s)
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name
"""


def map_publication(row: dict) -> dict:
    return {
        "table": row["table_name"],
        "rows": int(row["row_count"]),
        "digest": row["content_digest"],
        "run_id": row["lineage_run_id"],
        "published_at": _iso(row["published_at"]),
    }


def list_publications(conn: Any) -> list[dict]:
    return [map_publication(row) for row in rows(conn, PUBLICATIONS_SQL)]


def list_tables(conn: Any) -> list[dict]:
    found = rows(conn, TABLES_SQL, (list(SERVING_SCHEMAS),))
    tables = []
    for row in found:
        schema = row["table_schema"]
        table = row["table_name"]
        tables.append(
            {"schema": schema, "table": table, "rows": scalar(conn, count_query(schema, table))}
        )
    return tables


def _iso(value: object) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)
