"""Knowledge registry metadata from ``kb.active_chunk``.

Chunk text and embeddings are not selected. The active-set digest matches
``copilot.kb.active_set_hash``: sha256 of the sorted chunk ids joined by
newlines.
"""

from __future__ import annotations

import hashlib
from typing import Any

from data_api.db import rows

DOCUMENTS_SQL = """
SELECT doc_id, version, title, classification, count(*)::bigint AS chunk_count
FROM kb.active_chunk
GROUP BY doc_id, version, title, classification
ORDER BY doc_id, version
"""

CHUNK_IDS_SQL = """
SELECT chunk_id
FROM kb.active_chunk
"""


def active_set_hash(chunk_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(chunk_ids)).encode()).hexdigest()


def list_documents(conn: Any) -> list[dict]:
    return [
        {
            "doc_id": row["doc_id"],
            "version": row["version"],
            "title": row["title"],
            "classification": row["classification"],
            "chunk_count": int(row["chunk_count"]),
        }
        for row in rows(conn, DOCUMENTS_SQL)
    ]


def read_active_set(conn: Any) -> dict:
    identifiers = [row["chunk_id"] for row in rows(conn, CHUNK_IDS_SQL)]
    return {"active_set_hash": active_set_hash(identifiers), "chunk_count": len(identifiers)}
