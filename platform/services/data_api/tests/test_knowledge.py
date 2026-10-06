"""Knowledge documents and the active-set hash. The database is a fake."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from data_api.app import create_app
from data_api.knowledge import (
    CHUNK_IDS_SQL,
    DOCUMENTS_SQL,
    active_set_hash,
    list_documents,
    read_active_set,
)
from data_api.store import PostgresStore


class Cursor:
    def __init__(self, records: list[tuple], names: list[str]) -> None:
        self._records = records
        self.description = [SimpleNamespace(name=name) for name in names]

    def fetchall(self) -> list[tuple]:
        return self._records

    def fetchone(self) -> tuple | None:
        return self._records[0] if self._records else None


class ScriptedConn:
    def __init__(self, script: list[tuple[str, Cursor]]) -> None:
        self.script = list(script)
        self.statements: list[tuple] = []
        self.closed = False

    def execute(self, query, params=None):
        self.statements.append((query, params))
        text = query if isinstance(query, str) else "COMPOSED"
        for index, (needle, cursor) in enumerate(self.script):
            if needle in text:
                self.script.pop(index)
                return cursor
        return Cursor([], [])

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def test_knowledge_sql_does_not_select_text_or_embeddings() -> None:
    for statement in (DOCUMENTS_SQL, CHUNK_IDS_SQL):
        lowered = statement.lower()
        assert re.search(r"select\s+\*", lowered) is None
        for banned in ("content", "embedding", "customer_id"):
            assert re.search(rf"\b{banned}\b", lowered) is None


def test_active_set_hash_sorts_and_joins() -> None:
    assert active_set_hash(["b", "a", "b"]) == hashlib.sha256(b"a\nb\nb").hexdigest()
    assert active_set_hash([]) == hashlib.sha256(b"").hexdigest()


def test_hash_expression_matches_copilot() -> None:
    source = (Path(__file__).resolve().parents[4] / "copilot/src/copilot/kb.py").read_text()
    needle = 'hashlib.sha256("\\n".join(sorted(chunk_ids)).encode()).hexdigest()'
    assert needle in source


def test_list_documents_returns_metadata_only() -> None:
    cursor = Cursor(
        [("fees", "1.2.0", "Card fees", "public", 3)],
        ["doc_id", "version", "title", "classification", "chunk_count"],
    )
    assert list_documents(ScriptedConn([("kb.active_chunk", cursor)])) == [
        {
            "doc_id": "fees",
            "version": "1.2.0",
            "title": "Card fees",
            "classification": "public",
            "chunk_count": 3,
        }
    ]


def test_read_active_set_hashes_sorted_ids() -> None:
    cursor = Cursor([("b",), ("a",)], ["chunk_id"])
    found = read_active_set(ScriptedConn([("chunk_id", cursor)]))
    assert found == {
        "active_set_hash": active_set_hash(["b", "a"]),
        "chunk_count": 2,
    }


def test_store_opens_knowledge_read_only() -> None:
    conn = ScriptedConn([])
    seen: list[str] = []
    store = PostgresStore(connector=lambda db: seen.append(db) or conn)
    assert store.documents() == []
    assert store.active_set()["chunk_count"] == 0
    assert seen == ["knowledge", "knowledge"]
    texts = [item[0] for item in conn.statements]
    assert texts.count("SET TRANSACTION READ ONLY") == 2
    assert conn.closed is True


def test_knowledge_routes() -> None:
    digest = active_set_hash(["only"])

    class Memory:
        def documents(self) -> list[dict]:
            return [
                {
                    "doc_id": "fees",
                    "version": "1.2.0",
                    "title": "Card fees",
                    "classification": "internal",
                    "chunk_count": 2,
                }
            ]

        def active_set(self) -> dict:
            return {"active_set_hash": digest, "chunk_count": 1}

    client = TestClient(create_app(store=Memory()))
    documents = client.get("/knowledge/documents")
    active = client.get("/knowledge/active-set")
    assert documents.status_code == 200
    assert documents.json()["documents"][0]["doc_id"] == "fees"
    assert "content" not in documents.json()["documents"][0]
    assert active.json() == {"active_set_hash": digest, "chunk_count": 1}
