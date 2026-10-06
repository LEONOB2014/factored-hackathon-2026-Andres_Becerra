"""Live reads against pg-core. Skipped when the database is not reachable."""

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from data_api.app import create_app
from data_api.db import KNOWLEDGE_DB, SERVING_DB, rows, session
from data_api.knowledge import CHUNK_IDS_SQL, active_set_hash

pytestmark = pytest.mark.integration

_FORBIDDEN = {"customer_id", "content", "embedding", "feature_snapshot"}


def _reachable() -> bool:
    try:
        with session(SERVING_DB) as conn:
            conn.execute("SELECT 1")
        with session(KNOWLEDGE_DB) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return False
    return True


def _keys(value: object):
    if isinstance(value, dict):
        yield from value
        for item in value.values():
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_live_endpoints_return_metadata_only() -> None:
    if not _reachable():
        pytest.skip("pg-core is not reachable as app_reader")
    client = TestClient(create_app())
    publications = client.get("/serving/publications")
    tables = client.get("/serving/tables")
    documents = client.get("/knowledge/documents")
    active = client.get("/knowledge/active-set")
    for response in (publications, tables, documents, active):
        assert response.status_code == 200
        assert _FORBIDDEN.isdisjoint(_keys(response.json()))

    for row in publications.json()["publications"]:
        assert set(row) == {"table", "rows", "digest", "run_id", "published_at"}
    found = {(row["schema"], row["table"]) for row in tables.json()["tables"]}
    assert ("serving", "publication_log") in found
    assert ("online_features", "customer_state") in found
    assert ("decisions", "fraud_decision_log") in found
    for row in tables.json()["tables"]:
        assert row["schema"] in {"serving", "online_features", "decisions"}
        assert isinstance(row["rows"], int)
    for row in documents.json()["documents"]:
        assert set(row) == {"doc_id", "version", "title", "classification", "chunk_count"}
    body = active.json()
    assert set(body) == {"active_set_hash", "chunk_count"}
    with session(KNOWLEDGE_DB) as conn:
        identifiers = [row["chunk_id"] for row in rows(conn, CHUNK_IDS_SQL)]
    assert body["chunk_count"] == len(identifiers)
    assert body["active_set_hash"] == active_set_hash(identifiers)


def test_reader_rejects_writes() -> None:
    if not _reachable():
        pytest.skip("pg-core is not reachable as app_reader")
    with session(SERVING_DB) as conn, pytest.raises(psycopg.Error):
        conn.execute("CREATE TABLE serving.data_api_should_not_exist (id int)")
