"""Build the bundled knowledge-base index for the deployed copilot, and verify it against the dev stack.

The index holds the active set of knowledge/*.md (approved, in their effective window) chunked and embedded exactly
as the platform's kb_sync pipeline does. --verify checks that its active-set hash equals the one in pgvector, and
that Neo4j marks the same versions active, so the deployed app serves what the governed registry serves.

    cd copilot && uv sync --extra rag --extra stores
    uv run python scripts/build_kb_index.py --verify      # data/copilot/kb_index/ (git-ignored)
"""

from __future__ import annotations

import argparse
import sys

from copilot.kb import INDEX, GraphRetriever, PgVectorRetriever, active_set_hash, build_index


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    meta = build_index()
    docs = sorted({(c["doc_id"], c["version"], c["classification"]) for c in meta["chunks"]})
    print(
        f"wrote {INDEX}: {len(meta['chunks'])} chunks from {len(docs)} documents, hash {meta['active_set_hash'][:12]}"
    )
    for d in docs:
        print("  ", *d)
    if not args.verify:
        return 0
    pg_hash = active_set_hash(PgVectorRetriever().chunk_ids())
    recs, _, _ = GraphRetriever().driver.execute_query(
        "MATCH (v:DocVersion {active: true})-[:HAS_CHUNK]->(c:Chunk) RETURN c.chunk_id AS id"
    )
    neo_hash = active_set_hash([r["id"] for r in recs])
    ok = meta["active_set_hash"] == pg_hash == neo_hash
    print(
        f"pgvector {pg_hash[:12]}  neo4j {neo_hash[:12]}  bundled {meta['active_set_hash'][:12]}  ->",
        "MATCH" if ok else "MISMATCH",
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
